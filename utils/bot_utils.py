# utils/bot_utils.py
import logging
import logging.handlers
from pathlib import Path
from telegram import Update, Message
from telegram.ext import ContextTypes

from db import get_subscription, get_user_prefs, set_user_pref, get_user_flag, set_user_flag
from menus.menu_builder import get_back_button

logger = logging.getLogger(__name__)

def setup_logging():
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "bot.log"
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=10*1024*1024, backupCount=5, encoding='utf-8'
    )
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    root_logger.addHandler(file_handler)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    root_logger.addHandler(console_handler)

async def reply_and_save(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, reply_markup=None, **kwargs):
    if update.message:
        sent = await update.message.reply_text(text, reply_markup=reply_markup, **kwargs)
    elif update.callback_query:
        sent = await update.callback_query.message.reply_text(text, reply_markup=reply_markup, **kwargs)
    else:
        return None
    await save_bot_message(context, sent)
    return sent

async def edit_and_save(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, reply_markup=None, **kwargs):
    query = update.callback_query
    try:
        await query.edit_message_text(text, reply_markup=reply_markup, **kwargs)
    except Exception as e:
        logger.error(f"Ошибка редактирования: {e}")
        sent = await query.message.reply_text(text, reply_markup=reply_markup, **kwargs)
        await save_bot_message(context, sent)
        return sent
    msg = query.message
    if msg and msg.message_id not in context.user_data.get('bot_message_ids', []):
        await save_bot_message(context, msg)
    return msg

async def save_bot_message(context: ContextTypes.DEFAULT_TYPE, message: Message):
    if not context.user_data.get('bot_message_ids'):
        context.user_data['bot_message_ids'] = []
    context.user_data['bot_message_ids'].append(message.message_id)
    if len(context.user_data['bot_message_ids']) > 50:
        context.user_data['bot_message_ids'] = context.user_data['bot_message_ids'][-50:]

async def clear_bot_messages(context: ContextTypes.DEFAULT_TYPE, chat_id: int, keep_last: int = 1):
    ids = context.user_data.get('bot_message_ids', [])
    if not ids:
        return
    to_delete = ids[:-keep_last] if keep_last > 0 else ids
    if not to_delete:
        return
    for mid in to_delete:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=mid)
        except Exception:
            pass
    context.user_data['bot_message_ids'] = ids[-keep_last:] if keep_last > 0 else []

async def check_subscription(user_id: int) -> bool:
    sub = get_subscription(user_id)
    return sub.get("active", False)

# ===== НОВОЕ: проверка доступа к услуге (подписка ИЛИ купленная разовая) =====
async def check_service_access(user_id: int, service: str) -> bool:
    """
    Проверяет, может ли пользователь использовать услугу:
    - если есть активная подписка → доступ есть
    - если есть флаг one_time_{service} → доступ есть (и флаг сбрасывается после использования)
    """
    if await check_subscription(user_id):
        return True
    flag = f"one_time_{service}"
    if get_user_flag(user_id, flag):
        # Сразу сбрасываем флаг, чтобы услугу можно было использовать только один раз
        set_user_flag(user_id, flag, False)
        return True
    return False

def get_payment_info() -> str:
    return """
💳 **Реквизиты для перевода:**

Получатель: `Виктория Т`
Номер карты: `СБП ВТБ`
Номер телефона: `+7 912 654-27-76`
Сумма: 299 ₽ (базовый), 699 ₽ (про), 1999 ₽ (безлимит)

После перевода нажмите кнопку «Я оплатил» и отправьте скриншот чека.
"""