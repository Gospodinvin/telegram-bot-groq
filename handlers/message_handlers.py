# handlers/message_handlers.py
import logging
import os
import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

import config
import db
import constants
from utils.bot_utils import (
    reply_and_save, save_bot_message, clear_bot_messages,
    check_subscription, check_service_access
)
from utils.file_utils import safe_temp_file
from menus.menu_builder import get_back_button, get_main_menu_keyboard
from llm_client import call_llm  # <--- ИЗМЕНЕНО: вместо ollama_client
from handlers.command_handlers import send_main_menu

logger = logging.getLogger(__name__)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # ---- Чек для подписки ----
    if context.user_data.get('waiting_for_receipt'):
        photo = update.message.photo[-1]
        file = await photo.get_file()
        with safe_temp_file(suffix='.jpg') as tmp_path:
            await file.download_to_drive(tmp_path)

            plan = context.user_data.get('pending_plan', 'basic')
            days = context.user_data.get('pending_days', 30)
            price_rub = context.user_data.get('pending_price_rub', 0)
            price_stars = context.user_data.get('pending_price_stars', 0)

            payment_id = db.add_payment(
                user_id=user_id,
                service_type='subscription',
                plan=plan,
                amount_rub=price_rub,
                amount_stars=price_stars,
                screenshot_file_id=file.file_id
            )

            caption = (
                f"📥 Новый платёж от @{update.effective_user.username or user_id} (ID: {user_id})\n"
                f"Желаемый тариф: {plan}\n"
                f"Сумма: {price_rub}₽ / {price_stars}⭐\n\n"
                f"Для активации нажмите кнопку ниже."
            )
            buttons = [
                [InlineKeyboardButton("✅ Подтвердить", callback_data=f"confirm_payment_{payment_id}"),
                 InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_payment_{payment_id}")]
            ]
            with open(tmp_path, 'rb') as f:
                await context.bot.send_photo(
                    chat_id=config.ADMIN_ID,
                    photo=f,
                    caption=caption,
                    reply_markup=InlineKeyboardMarkup(buttons)
                )

        await update.message.reply_text(
            "✅ Спасибо! Чек отправлен администратору. После активации подписки вы получите уведомление."
        )
        context.user_data.pop('waiting_for_receipt', None)
        context.user_data.pop('pending_plan', None)
        context.user_data.pop('pending_days', None)
        context.user_data.pop('pending_price_rub', None)
        context.user_data.pop('pending_price_stars', None)
        await send_main_menu(update, context)
        return

    if context.user_data.get('waiting_for_one_time_receipt'):
        photo = update.message.photo[-1]
        file = await photo.get_file()
        service = context.user_data.get('one_time_service', 'неизвестно')
        price = config.ONE_TIME_PRICES.get(service, {}).get('stars', 0)

        with safe_temp_file(suffix='.jpg') as tmp_path:
            await file.download_to_drive(tmp_path)

            payment_id = db.add_payment(
                user_id=user_id,
                service_type='one_time',
                service_name=service,
                amount_stars=price,
                screenshot_file_id=file.file_id
            )

            caption = (
                f"📥 Новая разовая оплата от @{update.effective_user.username or user_id} (ID: {user_id})\n"
                f"Услуга: {service}\n"
                f"Стоимость: {price} ⭐\n\n"
                f"Активируйте услугу нажатием кнопки."
            )
            buttons = [
                [InlineKeyboardButton("✅ Подтвердить", callback_data=f"confirm_payment_{payment_id}"),
                 InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_payment_{payment_id}")]
            ]
            with open(tmp_path, 'rb') as f:
                await context.bot.send_photo(
                    chat_id=config.ADMIN_ID,
                    photo=f,
                    caption=caption,
                    reply_markup=InlineKeyboardMarkup(buttons)
                )

        await update.message.reply_text(
            "✅ Спасибо! Чек отправлен администратору. После активации вы сможете воспользоваться услугой."
        )
        context.user_data.pop('waiting_for_one_time_receipt', None)
        context.user_data.pop('one_time_service', None)
        await send_main_menu(update, context)
        return

    await update.message.reply_text("Я не ожидал фото. Если вы хотите оплатить подписку, выберите тариф в разделе «Подписка».")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    text = context.user_data.pop("text_from_file", None)
    if text is None:
        text = update.message.text

    action = context.user_data.get("action")

    # Обработка ввода ID для отмены
    if context.user_data.get("awaiting_cancel_id"):
        try:
            task_id = int(text.strip())
        except ValueError:
            sent = await update.message.reply_text("❌ Введите число — ID задачи.")
            await save_bot_message(context, sent)
            return
        context.user_data.pop("awaiting_cancel_id", None)
        task_queue = context.bot_data.get('task_queue')
        if not task_queue:
            sent = await update.message.reply_text("❌ Система очереди не инициализирована.")
            await save_bot_message(context, sent)
            return
        success = task_queue.cancel_task(user_id, task_id)
        if success:
            sent = await update.message.reply_text(f"✅ Задача №{task_id} отменена.")
        else:
            sent = await update.message.reply_text(
                f"❌ Не удалось отменить задачу №{task_id}.\n"
                "Возможно, она уже выполнена, не принадлежит вам или не существует."
            )
        await save_bot_message(context, sent)
        return

    if action == "diploma_start":
        context.user_data.pop("action", None)
        from conversations.diploma_conversation import diploma_start
        await diploma_start(update, context)
        return

    await clear_bot_messages(context, chat_id, keep_last=1)
    task_queue = context.bot_data.get('task_queue')
    if not task_queue:
        await update.message.reply_text("❌ Система очереди не готова, попробуйте позже.")
        return

    if action == "summarize":
        if not await check_service_access(user_id, "summarize"):
            sent = await update.message.reply_text(
                "⚠️ У вас нет доступа к услуге «Конспект».\n"
                "Оформите подписку или купите разовую услугу в разделе «Разовые услуги».",
                reply_markup=get_back_button()
            )
            await save_bot_message(context, sent)
            return
        if len(text) < constants.MIN_TEXT_FOR_SUMMARY:
            sent = await update.message.reply_text("Текст слишком короткий.")
            await save_bot_message(context, sent)
            return
        if await check_subscription(user_id):
            sub = db.get_subscription(user_id)
            plan_key = sub.get("plan", "trial")
            plan = config.SUBSCRIPTION_PLANS.get(plan_key, config.SUBSCRIPTION_PLANS["trial"])
            limit = plan["limits"].get("daily_summaries", 99999)
            if not db.check_limit(user_id, "summarize", limit):
                sent = await update.message.reply_text("Дневной лимит конспектов исчерпан.")
                await save_bot_message(context, sent)
                return
            db.use_limit(user_id, "summarize")
        payload = {
            "prompt": f"Сделай подробный конспект следующего текста:\n\n{text}",
            "system": "Ты — ассистент-конспектор. Выдели главные мысли, структурируй.",
            "num_predict": 4000,
        }
        tid = task_queue.submit(user_id, "summarize", payload)
        sent = await update.message.reply_text(f"🕐 Задача на конспектирование поставлена в очередь (№{tid}). Ожидайте…")
        await save_bot_message(context, sent)
        context.user_data.pop("action", None)
        return

    if action == "humanize":
        if not await check_service_access(user_id, "humanize"):
            sent = await update.message.reply_text(
                "⚠️ У вас нет доступа к услуге «Гуманизация».\n"
                "Оформите подписку или купите разовую услугу в разделе «Разовые услуги».",
                reply_markup=get_back_button()
            )
            await save_bot_message(context, sent)
            return
        if len(text) < 20:
            sent = await update.message.reply_text("Слишком короткий текст.")
            await save_bot_message(context, sent)
            return
        payload = {
            "text": text,
            "is_file": context.user_data.pop("is_file", False),
            "filename": context.user_data.pop("original_filename", "humanized.docx"),
        }
        tid = task_queue.submit(user_id, "humanize", payload)
        sent = await update.message.reply_text(f"🕐 Задача на гуманизацию в очереди (№{tid}).")
        await save_bot_message(context, sent)
        context.user_data.pop("action", None)
        return

    if action == "handwrite":
        if not await check_service_access(user_id, "handwrite"):
            sent = await update.message.reply_text(
                "⚠️ У вас нет доступа к услуге «Рукописный текст».\n"
                "Оформите подписку или купите разовую услугу в разделе «Разовые услуги».",
                reply_markup=get_back_button()
            )
            await save_bot_message(context, sent)
            return
        if len(text) < 5:
            sent = await update.message.reply_text("Слишком короткий текст.")
            await save_bot_message(context, sent)
            return
        prefs = db.get_user_prefs(user_id)
        style = prefs.get("font_style", "cursive")
        payload = {"text": text, "user_id": user_id, "style": style}
        tid = task_queue.submit(user_id, "handwrite", payload)
        sent = await update.message.reply_text(f"🕐 Задача на генерацию рукописного текста в очереди (№{tid}).")
        await save_bot_message(context, sent)
        context.user_data.pop("action", None)
        return

    if action == "cheatsheet":
        if not await check_service_access(user_id, "cheatsheet"):
            sent = await update.message.reply_text(
                "⚠️ У вас нет доступа к услуге «Шпоргалка».\n"
                "Оформите подписку или купите разовую услугу в разделе «Разовые услуги».",
                reply_markup=get_back_button()
            )
            await save_bot_message(context, sent)
            return
        if len(text.strip()) < 3:
            sent = await update.message.reply_text("Пожалуйста, введите тему поконкретнее.")
            await save_bot_message(context, sent)
            return
        prompt = f"Составь краткую шпаргалку по теме: {text}. Выдели ключевые определения, формулы, факты. Будь лаконичен, но информативен."
        system = "Ты — помощник-репетитор. Твоя задача — дать чёткую, структурированную выжимку по запросу. Используй списки и короткие абзацы. Не более 800 символов."
        result = call_llm(  # <--- ИЗМЕНЕНО: call_ollama → call_llm
            prompt=prompt,
            system=system,
            model="fast",   # <--- ДОБАВЛЕН ПАРАМЕТР model
            num_predict=1000
        )
        sent = await update.message.reply_text(f"📝 Шпоргалка по теме «{text}»:\n\n{result[:4000]}")
        await save_bot_message(context, sent)
        await send_main_menu(update, context)
        context.user_data.pop("action", None)
        return

    if action == "quiz":
        if not await check_service_access(user_id, "quiz"):
            sent = await update.message.reply_text(
                "⚠️ У вас нет доступа к услуге «Тест».\n"
                "Оформите подписку или купите разовую услугу в разделе «Разовые услуги».",
                reply_markup=get_back_button()
            )
            await save_bot_message(context, sent)
            return
        if len(text) < constants.MIN_TEXT_FOR_QUIZ:
            sent = await update.message.reply_text("Текст слишком короткий для теста.")
            await save_bot_message(context, sent)
            return
        try:
            from quiz_generator import QuizGenerator
            qg = QuizGenerator()
            quiz_list = qg.generate(text, count=5)
            if not quiz_list:
                sent = await update.message.reply_text("Не удалось сгенерировать тест.")
                await save_bot_message(context, sent)
                return
            for q in quiz_list[:5]:
                params = qg.to_poll_params(q)
                await update.message.reply_poll(**params)
            await send_main_menu(update, context)
        except Exception as e:
            logger.error(f"Quiz error: {e}")
            sent = await update.message.reply_text(f"Ошибка генерации теста: {e}")
            await save_bot_message(context, sent)
        context.user_data.pop("action", None)
        return

    if action == "mindmap":
        if not await check_service_access(user_id, "mindmap"):
            sent = await update.message.reply_text(
                "⚠️ У вас нет доступа к услуге «Ментальная карта».\n"
                "Оформите подписку или купите разовую услугу в разделе «Разовые услуги».",
                reply_markup=get_back_button()
            )
            await save_bot_message(context, sent)
            return
        if len(text) < 100:
            sent = await update.message.reply_text("Слишком короткий текст для ментальной карты.")
            await save_bot_message(context, sent)
            return
        try:
            from mindmap import MindMapGenerator
            mg = MindMapGenerator()
            png_bytes = mg.generate(text, title="Конспект")
            if png_bytes:
                await update.message.reply_photo(photo=png_bytes, caption="🧠 Ментальная карта")
            else:
                sent = await update.message.reply_text("Не удалось создать ментальную карту. Убедитесь, что graphviz установлен.")
                await save_bot_message(context, sent)
            await send_main_menu(update, context)
        except Exception as e:
            logger.error(f"Mindmap error: {e}")
            sent = await update.message.reply_text(f"Ошибка: {e}")
            await save_bot_message(context, sent)
        context.user_data.pop("action", None)
        return

    # ---- Экспорты ----
    if action == "export_pdf":
        if not await check_service_access(user_id, "export_pdf"):
            sent = await update.message.reply_text(
                "⚠️ У вас нет доступа к экспорту PDF.\n"
                "Оформите подписку или купите разовую услугу в разделе «Разовые услуги».",
                reply_markup=get_back_button()
            )
            await save_bot_message(context, sent)
            return
        if len(text) < 100:
            sent = await update.message.reply_text("Слишком короткий текст.")
            await save_bot_message(context, sent)
            return
        try:
            from pdf_gost import build_gost_pdf
            from utils.diploma_utils import parse_diploma_text
            sections = parse_diploma_text(text)
            if not sections:
                sections = [("Текст", text)]
            meta = {
                "author": "Пользователь",
                "university": "Университет",
                "city": "Москва",
                "year": datetime.now().year,
                "include_abstract": False,
            }
            pdf_bytes = build_gost_pdf("Экспорт", sections, "gost_7.32-2017", meta)
            await update.message.reply_document(
                document=pdf_bytes,
                filename=f"export_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                caption="📄 PDF экспорт"
            )
            await send_main_menu(update, context)
        except Exception as e:
            logger.error(f"PDF export error: {e}")
            sent = await update.message.reply_text(f"Ошибка экспорта PDF: {e}")
            await save_bot_message(context, sent)
        context.user_data.pop("action", None)
        return

    if action == "export_docx":
        if not await check_service_access(user_id, "export_docx"):
            sent = await update.message.reply_text(
                "⚠️ У вас нет доступа к экспорту DOCX.\n"
                "Оформите подписку или купите разовую услугу в разделе «Разовые услуги».",
                reply_markup=get_back_button()
            )
            await save_bot_message(context, sent)
            return
        if len(text) < 100:
            sent = await update.message.reply_text("Слишком короткий текст.")
            await save_bot_message(context, sent)
            return
        try:
            from docx_export import build_simple_docx
            docx_bytes = build_simple_docx("Экспорт", text)
            await update.message.reply_document(
                document=docx_bytes,
                filename=f"export_{datetime.now().strftime('%Y%m%d_%H%M')}.docx",
                caption="📄 DOCX экспорт"
            )
            await send_main_menu(update, context)
        except Exception as e:
            logger.error(f"DOCX export error: {e}")
            sent = await update.message.reply_text(f"Ошибка экспорта DOCX: {e}")
            await save_bot_message(context, sent)
        context.user_data.pop("action", None)
        return

    if action == "export_pptx":
        if not await check_service_access(user_id, "export_pptx"):
            sent = await update.message.reply_text(
                "⚠️ У вас нет доступа к экспорту PPTX.\n"
                "Оформите подписку или купите разовую услугу в разделе «Разовые услуги».",
                reply_markup=get_back_button()
            )
            await save_bot_message(context, sent)
            return
        if len(text) < 100:
            sent = await update.message.reply_text("Слишком короткий текст.")
            await save_bot_message(context, sent)
            return
        try:
            from pptx_export import build_pptx
            pptx_bytes = build_pptx("Экспорт", text)
            await update.message.reply_document(
                document=pptx_bytes,
                filename=f"export_{datetime.now().strftime('%Y%m%d_%H%M')}.pptx",
                caption="📊 PPTX экспорт"
            )
            await send_main_menu(update, context)
        except Exception as e:
            logger.error(f"PPTX export error: {e}")
            sent = await update.message.reply_text(f"Ошибка экспорта PPTX: {e}")
            await save_bot_message(context, sent)
        context.user_data.pop("action", None)
        return

    if action == "export_anki":
        if not await check_service_access(user_id, "export_anki"):
            sent = await update.message.reply_text(
                "⚠️ У вас нет доступа к экспорту Anki.\n"
                "Оформите подписку или купите разовую услугу в разделе «Разовые услуги».",
                reply_markup=get_back_button()
            )
            await save_bot_message(context, sent)
            return
        if len(text) < 20:
            sent = await update.message.reply_text("Слишком короткий текст.")
            await save_bot_message(context, sent)
            return
        try:
            from anki_export import AnkiExporter
            exporter = AnkiExporter()
            cards = exporter.extract_cards_from_summary(text)
            if not cards:
                sent = await update.message.reply_text("Не удалось извлечь карточки из текста.")
                await save_bot_message(context, sent)
                return
            anki_bytes = exporter.generate(cards, "LectureX Cards")
            await update.message.reply_document(
                document=anki_bytes,
                filename=f"anki_{datetime.now().strftime('%Y%m%d_%H%M')}.apkg",
                caption="📇 Anki экспорт"
            )
            await send_main_menu(update, context)
        except ImportError:
            sent = await update.message.reply_text("❌ Модуль genanki не установлен. Установите: pip install genanki")
            await save_bot_message(context, sent)
        except Exception as e:
            logger.error(f"Anki export error: {e}")
            sent = await update.message.reply_text(f"Ошибка экспорта Anki: {e}")
            await save_bot_message(context, sent)
        context.user_data.pop("action", None)
        return

    else:
        await send_main_menu(update, context)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    action = context.user_data.get("action")
    doc = update.message.document or update.message.audio or update.message.video

    if not doc:
        sent = await update.message.reply_text("Пожалуйста, отправьте файл.")
        await save_bot_message(context, sent)
        return

    task_queue = context.bot_data.get('task_queue')
    if not task_queue:
        await update.message.reply_text("❌ Система очереди не готова.")
        return

    # Загрузка пользовательского шрифта
    if context.user_data.get("waiting_font"):
        if doc.file_name and doc.file_name.endswith(".ttf"):
            if doc.file_size and doc.file_size > 10 * 1024 * 1024:
                sent = await update.message.reply_text("❌ Файл шрифта слишком большой (макс. 10 МБ).")
                await save_bot_message(context, sent)
                return
            file = await doc.get_file()
            with safe_temp_file(suffix='.ttf') as tmp_path:
                await file.download_to_drive(tmp_path)
                with open(tmp_path, 'rb') as f:
                    header = f.read(4)
                    if header not in (b'\x00\x01\x00\x00', b'\x4F\x54\x54\x4F'):
                        sent = await update.message.reply_text("❌ Похоже, это не TTF-шрифт.")
                        await save_bot_message(context, sent)
                        return
                font_path = config.FONTS_DIR / f"user_{user_id}.ttf"
                shutil.move(tmp_path, font_path)
            from handwriter_v2 import HandwriterV2
            hw = HandwriterV2()
            if hw.load_user(user_id, str(font_path)):
                db.set_user_pref(user_id, "font_style", "user")
                sent = await update.message.reply_text("✅ Шрифт загружен и установлен как пользовательский.")
                await save_bot_message(context, sent)
                await send_main_menu(update, context)
            else:
                sent = await update.message.reply_text("❌ Не удалось загрузить шрифт.")
                await save_bot_message(context, sent)
            context.user_data.pop("waiting_font", None)
            return
        else:
            sent = await update.message.reply_text("Пожалуйста, отправьте TTF-файл шрифта.")
            await save_bot_message(context, sent)
            return

    # Транскрипция
    if action == "transcribe" or (not action and context.user_data.get("auto_transcribe")):
        if not await check_service_access(user_id, "transcribe"):
            sent = await update.message.reply_text(
                "⚠️ У вас нет доступа к услуге «Транскрибация».\n"
                "Оформите подписку или купите разовую услугу в разделе «Разовые услуги».",
                reply_markup=get_back_button()
            )
            await save_bot_message(context, sent)
            return
        if doc.file_size and doc.file_size > constants.MAX_UPLOAD_SIZE_BYTES:
            sent = await update.message.reply_text(f"Файл слишком большой (макс. {constants.MAX_AUDIO_SIZE_MB} МБ).")
            await save_bot_message(context, sent)
            return

        file = await doc.get_file()
        ext = Path(doc.file_name).suffix if doc.file_name else ".tmp"
        with safe_temp_file(suffix=ext) as tmp_path:
            await file.download_to_drive(tmp_path)

            file_hash = hashlib.sha256()
            with open(tmp_path, "rb") as f:
                while chunk := f.read(8192):
                    file_hash.update(chunk)
            hash_hex = file_hash.hexdigest()

            cached = db.get_cached_transcription(hash_hex)
            if cached:
                sent = await update.message.reply_text(
                    f"📝 Распознанный текст (из кеша):\n\n{cached[:4000]}{'…' if len(cached)>4000 else ''}"
                )
                await save_bot_message(context, sent)
                await send_main_menu(update, context)
                return

            audio_path = tmp_path
            if doc.mime_type and doc.mime_type.startswith("video/"):
                if not shutil.which("ffmpeg"):
                    sent = await update.message.reply_text(
                        "❌ Для извлечения аудио из видео требуется ffmpeg. Установите его и повторите попытку."
                    )
                    await save_bot_message(context, sent)
                    return
                with safe_temp_file(suffix=".mp3") as audio_tmp:
                    try:
                        subprocess.run(
                            ["ffmpeg", "-i", tmp_path, "-q:a", "0", "-map", "a", audio_tmp, "-y"],
                            check=True, capture_output=True, timeout=120
                        )
                        audio_path = audio_tmp
                    except subprocess.CalledProcessError as e:
                        logger.error(f"ffmpeg error: {e.stderr}", exc_info=True)
                        sent = await update.message.reply_text(f"Ошибка извлечения аудио из видео: {e.stderr}")
                        await save_bot_message(context, sent)
                        return
                    except Exception as e:
                        logger.error(f"Ошибка при извлечении аудио: {e}", exc_info=True)
                        sent = await update.message.reply_text(f"Ошибка: {e}")
                        await save_bot_message(context, sent)
                        return

            payload = {
                "audio_path": audio_path,
                "file_hash": hash_hex,
                "file_name": doc.file_name or "unknown"
            }
            tid = task_queue.submit(user_id, "transcribe", payload)
            sent = await update.message.reply_text(
                f"🕐 Распознавание запущено (№{tid}). Ожидайте…\n"
                "⏳ Это может занять несколько минут в зависимости от длины файла."
            )
            await save_bot_message(context, sent)
            context.user_data.pop("action", None)
        return

    # Обработка текстовых файлов (TXT, DOCX)
    if doc.file_name and (doc.file_name.endswith(".txt") or doc.file_name.endswith(".docx")):
        file = await doc.get_file()
        with safe_temp_file(suffix=".txt") as tmp_path:
            await file.download_to_drive(tmp_path)
            try:
                if doc.file_name.endswith(".txt"):
                    encodings = ['utf-8', 'windows-1251', 'cp1251', 'latin-1']
                    text_content = None
                    for enc in encodings:
                        try:
                            with open(tmp_path, "r", encoding=enc) as f:
                                text_content = f.read()
                                break
                        except UnicodeDecodeError:
                            continue
                    if text_content is None:
                        raise UnicodeDecodeError("Не удалось декодировать файл ни в одной из кодировок.")
                elif doc.file_name.endswith(".docx"):
                    from docx import Document
                    docx = Document(tmp_path)
                    text_content = "\n".join([p.text for p in docx.paragraphs])
                else:
                    sent = await update.message.reply_text("Неподдерживаемый формат файла.")
                    await save_bot_message(context, sent)
                    return
            except Exception as e:
                logger.error(f"Ошибка чтения файла: {e}", exc_info=True)
                sent = await update.message.reply_text(f"Ошибка чтения файла: {e}")
                await save_bot_message(context, sent)
                return

        context.user_data["is_file"] = True
        context.user_data["original_filename"] = doc.file_name
        context.user_data["text_from_file"] = text_content
        await handle_text(update, context)
        return

    sent = await update.message.reply_text("Не могу обработать этот файл. Используйте команды из меню.")
    await save_bot_message(context, sent)