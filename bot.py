#!/usr/bin/env python3
# bot.py — точка входа
import asyncio
import logging
from pathlib import Path
from typing import Any
from datetime import datetime
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, filters
from telegram import Update

import config
import db
from handlers.command_handlers import (
    cmd_start, cmd_help, cmd_subscribe, cmd_settings, cmd_cheatsheet,
    cmd_cancel_task, cmd_search, cmd_activate, cmd_payments,
    cmd_activate_one_time, cmd_admin
)
from handlers.callback_handlers import handle_callback
from handlers.message_handlers import handle_photo, handle_text, handle_document
from conversations.diploma_conversation import diploma_conv, set_task_queue
from task_queue import TaskQueue
from utils.bot_utils import setup_logging
from utils.file_utils import cleanup_old_temp_files

setup_logging()
logger = logging.getLogger(__name__)

application = None
task_queue = None

async def on_task_complete(user_id: int, task_type: str, result: Any, payload: dict):
    """Отправляет результат выполненной задачи."""
    global application
    if not application:
        return
    try:
        if task_type == "transcribe":
            text = result if result else "Не удалось распознать текст."
            file_hash = payload.get("file_hash")
            if file_hash and text and "Не удалось" not in text:
                db.set_cached_transcription(file_hash, payload.get("file_name", ""), text)
            await application.bot.send_message(chat_id=user_id, text=f"📝 Распознанный текст:\n\n{text[:4000]}{'…' if len(text)>4000 else ''}")
        elif task_type == "summarize":
            await application.bot.send_message(chat_id=user_id, text=f"📚 Конспект:\n\n{result[:4000]}{'…' if len(result)>4000 else ''}")
        elif task_type == "humanize":
            if payload.get("is_file", False):
                from docx_export import build_simple_docx
                buf = build_simple_docx("Гуманизированный текст", result)
                await application.bot.send_document(chat_id=user_id, document=buf, filename=payload.get("filename", "humanized.docx"), caption="✨ Гуманизированный текст")
            else:
                await application.bot.send_message(chat_id=user_id, text=f"✨ Гуманизированный текст:\n\n{result[:4000]}{'…' if len(result)>4000 else ''}")
        elif task_type == "handwrite":
            await application.bot.send_photo(chat_id=user_id, photo=result, caption="🖊 Рукописный текст")
        elif task_type == "diploma_full":
            try:
                from docx_export import build_gost_docx
                from utils.diploma_utils import parse_diploma_text
                sections = parse_diploma_text(result)
                if not sections:
                    sections = [("Содержание", result)]
                meta = {
                    "author": payload.get("author", "Пользователь"),
                    "university": payload.get("university", "Университет"),
                    "city": payload.get("city", "Москва"),
                    "year": datetime.now().year,
                    "goal": payload.get("goal", ""),
                    "include_abstract": True,
                    "volume_pages": payload.get("volume_pages", 60),
                }
                images = payload.get("images", {})
                buf = build_gost_docx(
                    title=f"Дипломная работа: {payload.get('topic', '')}",
                    sections=sections,
                    standard_key=payload.get("standard", "gost_7.32-2017"),
                    meta=meta,
                    work_type=payload.get("work_type", "diploma"),
                    images=images
                )
                await application.bot.send_document(chat_id=user_id, document=buf, filename=f"diploma_{datetime.now().strftime('%Y%m%d_%H%M')}.docx", caption="📄 Ваша дипломная работа")
            except Exception as e:
                logger.warning(f"Не удалось создать DOCX: {e}")
                await application.bot.send_message(chat_id=user_id, text=f"📄 Дипломная работа (текст):\n\n{result[:4000]}{'…' if len(result)>4000 else ''}")
        else:
            await application.bot.send_message(chat_id=user_id, text=f"Результат задачи {task_type}:\n{str(result)[:3000]}")
        from menus.menu_builder import get_main_menu_keyboard
        await application.bot.send_message(chat_id=user_id, text="✅ Задача выполнена. Выберите следующее действие:", reply_markup=get_main_menu_keyboard())
    except Exception as e:
        logger.error(f"Ошибка отправки результата: {e}", exc_info=True)

async def cleanup_task():
    """Фоновая задача для очистки старых временных файлов и БД."""
    while True:
        try:
            cleanup_old_temp_files()
            db.cleanup_old_records()
            logger.info("Периодическая очистка выполнена")
        except Exception as e:
            logger.error(f"Ошибка очистки: {e}")
        await asyncio.sleep(3600)  # каждый час

async def post_init(application: Application):
    """Запускается после инициализации приложения, запускает фоновую задачу очистки."""
    asyncio.create_task(cleanup_task())
    logger.info("Фоновая задача очистки запущена")

def main():
    global application, task_queue
    db.init_db()
    application = Application.builder() \
        .token(config.TELEGRAM_TOKEN) \
        .post_init(post_init) \
        .build()

    # Команды
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("subscribe", cmd_subscribe))
    application.add_handler(CommandHandler("settings", cmd_settings))
    application.add_handler(CommandHandler("cancel_task", cmd_cancel_task))
    application.add_handler(CommandHandler("search", cmd_search))
    application.add_handler(CommandHandler("cheatsheet", cmd_cheatsheet))
    application.add_handler(CommandHandler("activate", cmd_activate))
    application.add_handler(CommandHandler("activate_one_time", cmd_activate_one_time))
    application.add_handler(CommandHandler("payments", cmd_payments))
    application.add_handler(CommandHandler("admin", cmd_admin))

    # Диалог диплома
    application.add_handler(diploma_conv)

    # Callback-обработчик
    application.add_handler(CallbackQueryHandler(handle_callback, pattern="^(?!diploma_)"))

    # Обработчики сообщений
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(MessageHandler(filters.Document.ALL | filters.AUDIO | filters.VIDEO, handle_document))

    # Очередь задач – БЕЗ ПЕРЕДАЧИ LOOP (исправлено)
    task_queue = TaskQueue(
        bot=application.bot,
        result_callback=on_task_complete,
        # loop больше не передаём, TaskQueue создаст свой собственный
    )
    task_queue.start()

    # Сохраняем очередь в bot_data для доступа из других модулей
    application.bot_data['task_queue'] = task_queue

    # Передаём очередь в дипломный диалог (если нужно)
    set_task_queue(task_queue)

    logger.info("🚀 Бот запущен")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()