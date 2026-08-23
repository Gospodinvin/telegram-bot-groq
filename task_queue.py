# task_queue.py — очередь задач с поддержкой отмены, логирования, безопасности
import threading
import time
import json
import logging
import asyncio
from pathlib import Path
from typing import Callable, Optional, Any

from db import add_task, get_pending_task, update_task_status, reset_running_tasks, get_task_status
from llm_client import call_llm
from utils_common import clean_markdown
import config
import constants

logger = logging.getLogger(__name__)


class TaskQueue:
    def __init__(self, bot=None, loop=None, result_callback=None):
        self.bot = bot
        self.loop = loop
        self.result_callback = result_callback
        self.gpu_lock = threading.Lock()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._running = False
        self._audio_processor = None
        self._humanizer = None
        self._handwriter = None
        self._current_task_id = None
        self._cancel_requested = False

        # Если внешний цикл не передан – создаём свой собственный
        if self.loop is None:
            self.loop = asyncio.new_event_loop()
            self._owns_loop = True
            logger.info("TaskQueue: создан собственный event loop")
        else:
            self._owns_loop = False
            logger.info("TaskQueue: использует внешний event loop")

    def start(self):
        self._running = True
        reset_running_tasks()
        self._thread.start()
        logger.info("TaskQueue: воркер запущен")

    def stop(self):
        self._running = False
        self._thread.join(timeout=constants.WORKER_SHUTDOWN_TIMEOUT)
        # Закрываем цикл ТОЛЬКО если он наш собственный
        if self._owns_loop and self.loop and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.loop.close()
        logger.info("TaskQueue: воркер остановлен")

    def submit(self, user_id: int, task_type: str, payload: dict) -> int:
        tid = add_task(user_id, task_type, payload)
        logger.info(f"TaskQueue: задача {tid} ({task_type}) от user {user_id} добавлена")
        self._notify(user_id, f"🕐 Задача поставлена в очередь (№{tid})")
        return tid

    def cancel_task(self, user_id: int, task_id: int) -> bool:
        status = get_task_status(task_id)
        if not status:
            return False
        if status["user_id"] != user_id:
            return False
        if status["status"] in ("done", "error", "cancelled"):
            return False

        if status["status"] == "running" and self._current_task_id == task_id:
            self._cancel_requested = True
            update_task_status(task_id, "cancelling")
            self._notify(user_id, f"⏹ Задача №{task_id} отменяется...")
            return True

        update_task_status(task_id, "cancelled")
        self._notify(user_id, f"✅ Задача №{task_id} отменена.")
        return True

    def _worker(self):
        # Устанавливаем созданный цикл для этого потока (если он наш)
        if self._owns_loop and self.loop:
            asyncio.set_event_loop(self.loop)

        while self._running:
            try:
                task = get_pending_task()
                if task is None:
                    time.sleep(constants.TASK_POLL_INTERVAL)
                    continue
                self._process_task(task)
            except Exception as e:
                logger.exception("TaskQueue: критическая ошибка воркера")
                time.sleep(5)

    def _process_task(self, task: dict):
        tid = task["id"]
        uid = task["user_id"]
        ttype = task["task_type"]
        payload = json.loads(task["payload"])

        self._current_task_id = tid
        self._cancel_requested = False

        self._notify(uid, f"⏳ Задача №{tid} начала выполняться…")
        update_task_status(tid, "running")

        try:
            with self.gpu_lock:
                result = self._execute(ttype, payload, uid, tid)

            if self._cancel_requested:
                update_task_status(tid, "cancelled")
                self._notify(uid, f"⏹ Задача №{tid} отменена пользователем.")
                return

            update_task_status(tid, "done")
            self._notify(uid, f"✅ Задача №{tid} выполнена!")
            if self.result_callback:
                # Используем наш цикл для вызова колбэка
                asyncio.run_coroutine_threadsafe(
                    self.result_callback(uid, ttype, result, payload),
                    self.loop
                )
        except Exception as e:
            logger.exception(f"TaskQueue: ошибка в задаче {tid}")
            if not self._cancel_requested:
                update_task_status(tid, f"error: {str(e)}")
                self._notify(uid, "❌ При выполнении задачи произошла ошибка.\nПопробуйте позже или с другим файлом.")
            else:
                update_task_status(tid, "cancelled")
                self._notify(uid, f"⏹ Задача №{tid} отменена.")
        finally:
            self._current_task_id = None
            self._cancel_requested = False

    def _execute(self, ttype: str, payload: dict, user_id: int, task_id: int) -> Any:
        def check_cancelled():
            if self._cancel_requested:
                raise RuntimeError("Task cancelled by user")
            status = get_task_status(task_id)
            if status and status.get("status") == "cancelled":
                self._cancel_requested = True
                raise RuntimeError("Task cancelled by user")

        if ttype == "transcribe":
            if self._audio_processor is None:
                from audio_processor import AudioProcessor
                self._audio_processor = AudioProcessor()
            result = self._audio_processor.transcribe(payload["audio_path"])
            try:
                Path(payload["audio_path"]).unlink(missing_ok=True)
            except Exception as e:
                logger.warning(f"Не удалось удалить аудиофайл: {e}")
            return result

        if ttype == "summarize":
            raw = call_llm(
                payload["prompt"],
                payload.get("system"),
                model="fast",
                num_predict=payload.get("num_predict", 4000),
            )
            return clean_markdown(raw)

        if ttype == "humanize":
            if self._humanizer is None:
                from humanizer import Humanizer
                self._humanizer = Humanizer()
            raw = self._humanizer.humanize(payload["text"])
            return clean_markdown(raw)

        if ttype == "diploma_full":
            from diploma_generator import generate_diploma
            return generate_diploma(payload, user_id, self._notify, check_cancelled)

        if ttype == "handwrite":
            if self._handwriter is None:
                from handwriter_v2 import HandwriterV2
                self._handwriter = HandwriterV2()
            return self._handwriter.generate(
                payload["text"],
                uid=payload.get("user_id"),
                style=payload.get("style", "cursive"),
            )

        raise ValueError(f"Неизвестный тип задачи: {ttype}")

    def _notify(self, user_id: int, text: str):
        if not self.bot or not self.loop:
            return
        try:
            asyncio.run_coroutine_threadsafe(
                self.bot.send_message(chat_id=user_id, text=text),
                self.loop
            )
        except Exception as e:
            logger.error(f"TaskQueue: не удалось уведомить {user_id}: {e}", exc_info=True)