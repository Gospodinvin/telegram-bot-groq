# menus/menu_builder.py
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def get_back_button() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ Назад в меню", callback_data="back_to_menu")]
    ])

def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("📝 Создать / Обработать", callback_data="menu_create")],
        [InlineKeyboardButton("📤 Экспорт", callback_data="menu_export")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="menu_settings")],
        [InlineKeyboardButton("💳 Подписка", callback_data="subscribe")],
        [InlineKeyboardButton("💸 Разовые услуги", callback_data="one_time_services")],  # НОВОЕ
        [InlineKeyboardButton("ℹ️ Помощь", callback_data="help")],
    ]
    return InlineKeyboardMarkup(buttons)

def get_create_menu() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("📝 Транскрибировать", callback_data="transcribe")],
        [InlineKeyboardButton("📚 Конспект", callback_data="summarize")],
        [InlineKeyboardButton("📝 Шпоргалка", callback_data="cheatsheet")],
        [InlineKeyboardButton("✨ Гуманизировать", callback_data="humanize")],
        [InlineKeyboardButton("🖊 Рукописный текст", callback_data="handwrite")],
        [InlineKeyboardButton("🎓 Дипломная работа", callback_data="diploma")],
        [InlineKeyboardButton("❓ Тест по конспекту", callback_data="quiz")],
        [InlineKeyboardButton("🧠 Ментальная карта", callback_data="mindmap")],
        [InlineKeyboardButton("⏹ Отменить задачу", callback_data="cancel_task")],
        [InlineKeyboardButton("◀️ Назад в меню", callback_data="back_to_menu")],
    ]
    return InlineKeyboardMarkup(buttons)

def get_export_menu() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("📤 Экспорт PDF", callback_data="export_pdf")],
        [InlineKeyboardButton("📤 Экспорт DOCX", callback_data="export_docx")],
        [InlineKeyboardButton("📊 Экспорт PPTX", callback_data="export_pptx")],
        [InlineKeyboardButton("📇 Экспорт Anki", callback_data="export_anki")],
        [InlineKeyboardButton("◀️ Назад в меню", callback_data="back_to_menu")],
    ]
    return InlineKeyboardMarkup(buttons)

def get_settings_menu() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("✍️ Курсив", callback_data="set_font_cursive")],
        [InlineKeyboardButton("🖨 Печатный", callback_data="set_font_print")],
        [InlineKeyboardButton("✒️ Рукописный", callback_data="set_font_handwritten")],
        [InlineKeyboardButton("🎩 Элегантный", callback_data="set_font_elegant")],
        [InlineKeyboardButton("👤 Свой шрифт (загрузить)", callback_data="set_font_user")],
        [InlineKeyboardButton("◀️ Назад в меню", callback_data="back_to_menu")],
    ]
    return InlineKeyboardMarkup(buttons)

def get_subscription_menu() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("⭐ Базовый (30 дн.) — 428 ⭐", callback_data="pay_basic")],
        [InlineKeyboardButton("⭐ Про (90 дн.) — 999 ⭐", callback_data="pay_pro")],
        [InlineKeyboardButton("⭐ Безлимитный (365 дн.) — 2856 ⭐", callback_data="pay_unlimited")],
        [InlineKeyboardButton("◀️ Назад в меню", callback_data="back_to_menu")],
    ]
    return InlineKeyboardMarkup(buttons)

# ===== НОВОЕ: меню разовых услуг =====
def get_one_time_menu() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("🎙 Транскрибация — 143 ⭐", callback_data="pay_one_time_transcribe")],
        [InlineKeyboardButton("📚 Конспект — 215 ⭐", callback_data="pay_one_time_summarize")],
        [InlineKeyboardButton("📝 Шпоргалка — 115 ⭐", callback_data="pay_one_time_cheatsheet")],
        [InlineKeyboardButton("✨ Гуманизация — 143 ⭐", callback_data="pay_one_time_humanize")],
        [InlineKeyboardButton("🖊 Рукописный — 72 ⭐", callback_data="pay_one_time_handwrite")],
        [InlineKeyboardButton("❓ Тест — 115 ⭐", callback_data="pay_one_time_quiz")],
        [InlineKeyboardButton("🧠 Ментальная карта — 115 ⭐", callback_data="pay_one_time_mindmap")],
        [InlineKeyboardButton("📄 Экспорт PDF/DOCX/PPTX — 72 ⭐", callback_data="pay_one_time_export")],
        [InlineKeyboardButton("📇 Экспорт Anki — 72 ⭐", callback_data="pay_one_time_anki")],
        [InlineKeyboardButton("◀️ Назад в меню", callback_data="back_to_menu")],
    ]
    return InlineKeyboardMarkup(buttons)