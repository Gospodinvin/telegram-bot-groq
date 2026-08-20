# handlers/command_handlers.py
import logging
import tempfile
import os
from datetime import datetime
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

import config
import db
from utils.bot_utils import reply_and_save, save_bot_message, clear_bot_messages, check_subscription, get_payment_info
from menus.menu_builder import get_main_menu_keyboard, get_back_button, get_subscription_menu, get_settings_menu
from data_collector import DataCollector
from llm_client import call_llm  # <--- ИЗМЕНЕНО: вместо ollama_client
import constants

logger = logging.getLogger(__name__)
data_collector_instance = DataCollector()

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.ensure_user(user.id, user.username, user.first_name)
    if not db.get_user_flag(user.id, "offer_accepted"):
        text = (
            "👋 Добро пожаловать в LectureX Bot!\n\n"
            "Перед использованием пожалуйста ознакомьтесь с условиями:\n"
            "📄 [Пользовательское соглашение]"
        )
        buttons = [
            [InlineKeyboardButton("📄 Показать оферту", callback_data="show_offer")],
            [InlineKeyboardButton("✅ Я ознакомлен, далее", callback_data="agree_offer")],
        ]
        sent = await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))
        await save_bot_message(context, sent)
    else:
        await send_main_menu(update, context)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📖 Помощь по командам:\n\n"
        "/start - Главное меню\n"
        "/help - Эта справка\n"
        "/subscribe - Управление подпиской\n"
        "/settings - Настройки (шрифт и т.д.)\n"
        "/transcribe - Распознать аудио/видео (отправьте файл)\n"
        "/summarize - Сделать конспект (отправьте текст или файл)\n"
        "/cheatsheet - Сгенерировать краткую шпаргалку по теме\n"
        "/humanize - Гуманизировать текст (отправьте текст)\n"
        "/diploma - Создать дипломную работу (пошагово)\n"
        "/handwrite - Сгенерировать рукописный текст (отправьте текст)\n"
        "/quiz - Сгенерировать тест (отправьте текст)\n"
        "/mindmap - Сгенерировать mind map (отправьте текст)\n"
        "/export_pdf - Экспорт текста в ГОСТ PDF\n"
        "/export_docx - Экспорт текста в DOCX\n"
        "/export_pptx - Экспорт текста в PowerPoint\n"
        "/export_anki - Экспорт терминов в Anki\n"
        "/cancel_task <id> - Отменить задачу по её номеру\n\n"
        "/admin - Админ-панель (только для администратора)\n\n"
        "Для большинства функций нужна активная подписка или разовая оплата."
    )
    sent = await reply_and_save(update, context, help_text)
    await save_bot_message(context, sent)

async def cmd_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_subscription_menu(update, context)

async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_settings_menu(update, context)

async def cmd_cheatsheet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sent = await update.message.reply_text(
        "Введите тему, по которой нужна шпаргалка:",
        reply_markup=get_back_button()
    )
    await save_bot_message(context, sent)
    context.user_data["action"] = "cheatsheet"

async def cmd_cancel_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    if not args:
        sent = await update.message.reply_text("⚠️ Укажите ID задачи: `/cancel_task <id>`")
        await save_bot_message(context, sent)
        return
    try:
        task_id = int(args[0])
    except ValueError:
        sent = await update.message.reply_text("❌ ID задачи должен быть числом.")
        await save_bot_message(context, sent)
        return
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

async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        sent = await update.message.reply_text("Введите запрос: /search что искать")
        await save_bot_message(context, sent)
        return
    query = " ".join(args)
    sent = await update.message.reply_text(f"🔍 Ищу: {query}...")
    await save_bot_message(context, sent)
    collected = data_collector_instance.collect(query, max_pages=2)
    prompt = f"Пользователь спросил: {query}\n\n"
    prompt += "Результаты поиска:\n"
    for item in collected["search_results"]:
        prompt += f"- {item['title']}\n  {item['link']}\n"
    prompt += "\nСодержание страниц:\n"
    for page in collected["pages_text"]:
        prompt += f"--- {page['url']} ---\n{page['text'][:1000]}\n\n"
    if collected["rss_news"]:
        prompt += "Свежие новости:\n"
        for news in collected["rss_news"]:
            prompt += f"- {news['title']} ({news['link']})\n"
    result = call_llm(  # <--- ИЗМЕНЕНО: call_ollama → call_llm
        prompt=prompt,
        system="Ты — ассистент. Отвечай на вопрос пользователя, используя только предоставленные данные. Будь кратким и точным. Если данных недостаточно, скажи об этом.",
        model="fast",  # <--- ДОБАВЛЕН ПАРАМЕТР model
        num_predict=2000
    )
    sent = await update.message.reply_text(result[:4000])
    await save_bot_message(context, sent)

# ---- Админские команды ----
async def cmd_activate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.ADMIN_ID:
        await update.message.reply_text("⛔ Только для администратора.")
        return
    args = context.args
    if len(args) < 3:
        await update.message.reply_text("Использование: /activate @username plan days\nПример: /activate @john basic 30")
        return
    username = args[0].lstrip('@')
    plan = args[1]
    try:
        days = int(args[2])
    except ValueError:
        await update.message.reply_text("❌ days должно быть числом.")
        return

    user_id = None
    try:
        user = await context.bot.get_chat(username)
        user_id = user.id
    except:
        await update.message.reply_text(f"❌ Пользователь @{username} не найден.")
        return

    if user_id:
        db.ensure_user(user_id, username, user.first_name if hasattr(user, 'first_name') else None)
        db.set_subscription(user_id, plan, days)
        await update.message.reply_text(f"✅ Подписка активирована для @{username} (план {plan}, {days} дней).")
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"🎉 Ваша подписка активирована! Тариф «{plan}» на {days} дней.\nТеперь вам доступны все функции бота."
            )
            await context.bot.send_message(
                chat_id=user_id,
                text="Выберите действие:",
                reply_markup=get_main_menu_keyboard()
            )
        except:
            pass

async def cmd_activate_one_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.ADMIN_ID:
        await update.message.reply_text("⛔ Только для администратора.")
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Использование: /activate_one_time user_id service_name")
        return
    try:
        user_id = int(args[0])
        service = args[1]
    except ValueError:
        await update.message.reply_text("❌ user_id должно быть числом.")
        return
    if service not in config.ONE_TIME_PRICES:
        await update.message.reply_text(f"❌ Услуга «{service}» не найдена. Доступные: {', '.join(config.ONE_TIME_PRICES.keys())}")
        return
    db.set_user_flag(user_id, f"one_time_{service}", True)
    await update.message.reply_text(f"✅ Разовая услуга «{service}» активирована для пользователя {user_id}.")
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"🎉 Ваша разовая услуга «{service}» активирована! Теперь вы можете воспользоваться ею.\n"
                 "Просто выберите её в меню «Создать / Обработать»."
        )
    except:
        pass

async def cmd_payments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.ADMIN_ID:
        await update.message.reply_text("⛔ Только для администратора.")
        return
    pending = db.get_pending_payments()
    if not pending:
        await update.message.reply_text("✅ Нет ожидающих платежей.")
        return
    text = "💳 **Ожидающие платежи:**\n\n"
    for p in pending:
        user_link = f"@{p['username']}" if p['username'] else f"ID: {p['user_id']}"
        text += f"• {user_link} – "
        if p['service_type'] == 'subscription':
            text += f"Подписка {p['plan']} (⭐{p['amount_stars']} / {p['amount_rub']}₽)"
        else:
            text += f"Разовая услуга «{p['service_name']}» (⭐{p['amount_stars']} / {p['amount_rub']}₽)"
        text += f"\n  Создан: {p['created_at'][:16]}\n\n"
    await update.message.reply_text(text[:4000], parse_mode='Markdown')

async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.ADMIN_ID:
        await update.message.reply_text("⛔ Только для администратора.")
        return
    buttons = [
        [InlineKeyboardButton("💳 Ожидающие платежи", callback_data="admin_payments")],
        [InlineKeyboardButton("👥 Пользователи (в разработке)", callback_data="admin_users")],
        [InlineKeyboardButton("📊 Статистика (в разработке)", callback_data="admin_stats")],
        [InlineKeyboardButton("◀️ Назад в меню", callback_data="back_to_menu")],
    ]
    await update.message.reply_text(
        "🔐 **Админ-панель**\n\nВыберите действие:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode='Markdown'
    )

# ---- Вспомогательные функции меню ----
async def send_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await clear_bot_messages(context, chat_id, keep_last=0)

    text = (
        "👋 Добро пожаловать в LectureX Bot!\n\n"
        "Я помогу вам:\n"
        "• Распознать речь из аудио/видео\n"
        "• Сделать конспект лекции\n"
        "• Гуманизировать текст\n"
        "• Создать рукописный текст\n"
        "• Написать дипломную работу по ГОСТ\n"
        "• Генерировать тесты, mind map, экспортировать в PDF/Word/Anki/PPTX\n\n"
        "Выберите категорию:"
    )
    if update.message:
        sent = await update.message.reply_text(text, reply_markup=get_main_menu_keyboard())
    elif update.callback_query:
        sent = await update.callback_query.message.reply_text(text, reply_markup=get_main_menu_keyboard())
        await update.callback_query.answer()
    else:
        return
    await save_bot_message(context, sent)

async def show_subscription_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, message=None):
    user_id = update.effective_user.id
    sub = db.get_subscription(user_id)
    status = "✅ Активна" if sub.get("active") else "❌ Неактивна"
    plan_name = sub.get("plan", "trial")
    if sub.get("active") and sub.get("end_date"):
        end_date = datetime.fromisoformat(sub["end_date"]).strftime("%d.%m.%Y")
        status = f"✅ Активна до {end_date}"

    text = (
        f"💳 **Статус подписки:** {status}\n"
        f"📋 **Тариф:** {plan_name}\n\n"
        "**Выберите тариф для оплаты:**\n"
        "⭐ Базовый — 428 Stars (вы получите 299₽)\n"
        "⭐ Про — 999 Stars (вы получите 699₽)\n"
        "⭐ Безлимитный — 2856 Stars (вы получите 1999₽)\n\n"
        "После перевода нажмите на кнопку с тарифом, чтобы увидеть реквизиты.\n"
        "Затем отправьте скриншот чека, и администратор активирует подписку."
    )
    if message:
        sent = await message.reply_text(text, reply_markup=get_subscription_menu(), parse_mode='Markdown')
    else:
        sent = await reply_and_save(update, context, text, reply_markup=get_subscription_menu(), parse_mode='Markdown')
    await save_bot_message(context, sent)

async def show_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, message=None):
    user_id = update.effective_user.id
    prefs = db.get_user_prefs(user_id)
    font_style = prefs.get("font_style", "cursive")
    text = f"⚙️ Настройки:\n\nШрифт для рукописного текста: {font_style}\n\nВыберите новый шрифт:"
    if message:
        sent = await message.reply_text(text, reply_markup=get_settings_menu())
    else:
        sent = await reply_and_save(update, context, text, reply_markup=get_settings_menu())
    await save_bot_message(context, sent)