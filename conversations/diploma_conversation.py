# conversations/diploma_conversation.py
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from telegram.error import BadRequest

import db
from utils.bot_utils import reply_and_save, save_bot_message, clear_bot_messages, check_subscription
from menus.menu_builder import get_back_button
from gost_standards import WORK_TYPES, STANDARDS, detect_standard
from task_queue import TaskQueue

logger = logging.getLogger(__name__)

# Состояния (порядок изменён: сначала выбор типа)
(
    DIPLOMA_TYPE,          # 0 — выбор типа работы
    DIPLOMA_TOPIC,         # 1 — ввод темы
    DIPLOMA_STANDARD,      # 2 — выбор/подтверждение стандарта
    DIPLOMA_GOAL,          # 3 — цель
    DIPLOMA_AUTHOR,        # 4 — автор
    DIPLOMA_SUPERVISOR,    # 5 — научный руководитель
    DIPLOMA_UNIVERSITY,    # 6 — университет
    DIPLOMA_SOURCES,       # 7 — источники
    DIPLOMA_EXTRA,         # 8 — доп. данные
    STRUCTURE_EDIT,        # 9 — редактирование структуры
    EDIT_CHAPTER,          # 10
    ADD_CHAPTER,           # 11
    EDIT_SUBSECTION,       # 12
    RENAME_CHAPTER,        # 13
    RENAME_SUBSECTION,     # 14
    ADD_SUBSECTION,        # 15
) = range(16)

task_queue = None

def set_task_queue(tq):
    global task_queue
    task_queue = tq


def make_default_structure(work_type: str, chapters_count: int, subsections_per_chapter: int) -> list:
    structure = []
    for i in range(1, chapters_count + 1):
        chapter_title = f"Глава {i}"
        subs = [f"{i}.{j}" for j in range(1, subsections_per_chapter + 1)]
        structure.append({"title": chapter_title, "subsections": subs})
    return structure


async def diploma_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await check_subscription(user_id):
        if update.message:
            sent = await update.message.reply_text("⚠️ Для создания работы нужна подписка.")
            await save_bot_message(context, sent)
        elif update.callback_query:
            await update.callback_query.message.reply_text("⚠️ Для создания работы нужна подписка.")
            await update.callback_query.answer()
        return ConversationHandler.END

    chat_id = update.effective_chat.id
    await clear_bot_messages(context, chat_id, keep_last=0)

    # Показываем выбор типа работы
    buttons = []
    for key, wt in WORK_TYPES.items():
        buttons.append([InlineKeyboardButton(wt["name"], callback_data=f"diploma_type_{key}")])
    buttons.append([InlineKeyboardButton("◀️ Назад в меню", callback_data="back_to_menu")])

    text = "📚 **Выберите тип работы:**"
    if update.message:
        sent = await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode='Markdown')
        await save_bot_message(context, sent)
    elif update.callback_query:
        try:
            await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode='Markdown')
        except BadRequest:
            await update.callback_query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode='Markdown')
        await save_bot_message(context, update.callback_query.message)
        await update.callback_query.answer()
    return DIPLOMA_TYPE


async def diploma_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    work_type = query.data.replace("diploma_type_", "")
    context.user_data["diploma_work_type"] = work_type

    # Теперь запрашиваем тему
    sent = await query.edit_message_text(
        f"Вы выбрали: {WORK_TYPES[work_type]['name']}\n\nВведите тему работы:",
        reply_markup=get_back_button()
    )
    await save_bot_message(context, sent)
    return DIPLOMA_TOPIC


async def diploma_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topic = update.message.text
    context.user_data["diploma_topic"] = topic
    standard = detect_standard(topic)
    context.user_data["diploma_standard"] = standard

    buttons = [
        [InlineKeyboardButton("✅ Подтвердить", callback_data="diploma_std_confirm")],
        [InlineKeyboardButton("🔁 Выбрать другой", callback_data="diploma_std_change")],
        [InlineKeyboardButton("◀️ Назад в меню", callback_data="back_to_menu")]
    ]
    sent = await update.message.reply_text(
        f"Автоматически выбран стандарт: {standard}. Подтвердите или измените:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    await save_bot_message(context, sent)
    return DIPLOMA_STANDARD


async def diploma_standard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    message = query.message

    if data == "diploma_std_confirm":
        await message.edit_text("Введите цель работы (например: «Разработать метод…»):", reply_markup=get_back_button())
        await save_bot_message(context, message)
        return DIPLOMA_GOAL
    else:
        buttons = []
        for key in STANDARDS.keys():
            buttons.append([InlineKeyboardButton(key, callback_data=f"diploma_std_set_{key}")])
        buttons.append([InlineKeyboardButton("◀️ Назад в меню", callback_data="back_to_menu")])
        await message.edit_text("Выберите стандарт оформления:", reply_markup=InlineKeyboardMarkup(buttons))
        await save_bot_message(context, message)
        return DIPLOMA_STANDARD


async def diploma_std_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    std = query.data.replace("diploma_std_set_", "")
    context.user_data["diploma_standard"] = std
    await query.edit_message_text(f"Стандарт выбран: {std}. Введите цель работы:", reply_markup=get_back_button())
    await save_bot_message(context, query.message)
    return DIPLOMA_GOAL


async def diploma_goal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["diploma_goal"] = update.message.text
    sent = await update.message.reply_text("Введите ФИО автора (например: Иванов И. И.):", reply_markup=get_back_button())
    await save_bot_message(context, sent)
    return DIPLOMA_AUTHOR


async def diploma_author(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["diploma_author"] = update.message.text
    sent = await update.message.reply_text("Введите ФИО научного руководителя:", reply_markup=get_back_button())
    await save_bot_message(context, sent)
    return DIPLOMA_SUPERVISOR


async def diploma_supervisor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["diploma_supervisor"] = update.message.text
    sent = await update.message.reply_text("Введите название университета (например: УрФУ):", reply_markup=get_back_button())
    await save_bot_message(context, sent)
    return DIPLOMA_UNIVERSITY


async def diploma_university(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["diploma_university"] = update.message.text
    sent = await update.message.reply_text(
        "Введите ключевые слова для поиска литературы или перечислите известные вам источники (через запятую).\n"
        "Если не знаете, отправьте «-» — я сгенерирую список сам.",
        reply_markup=get_back_button()
    )
    await save_bot_message(context, sent)
    return DIPLOMA_SOURCES


async def diploma_sources(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sources_input = update.message.text
    context.user_data["diploma_sources"] = sources_input if sources_input != "-" else ""
    sent = await update.message.reply_text(
        "Введите дополнительные данные (город, год, факультет и т.д.) или отправьте «-» для пропуска:",
        reply_markup=get_back_button()
    )
    await save_bot_message(context, sent)
    return DIPLOMA_EXTRA


async def diploma_extra(update: Update, context: ContextTypes.DEFAULT_TYPE):
    extra = update.message.text
    if extra != "-":
        context.user_data["diploma_extra"] = extra
    await show_structure_editor(update, context)
    return STRUCTURE_EDIT


async def show_structure_editor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await clear_bot_messages(context, chat_id, keep_last=0)

    structure = context.user_data.get('structure')
    work_type = context.user_data.get('diploma_work_type', 'diploma')
    wt = WORK_TYPES.get(work_type, WORK_TYPES['diploma'])
    required_chapters = wt['chapters']
    required_subs = wt['subsections_per_chapter']

    # Проверка валидности структуры (без жёсткой привязки к "Глава 1")
    structure_valid = False
    if structure and isinstance(structure, list) and len(structure) >= required_chapters:
        # Проверяем, что каждый элемент содержит 'title' и 'subsections'
        for ch in structure:
            if not ch.get('title') or not isinstance(ch.get('subsections'), list):
                structure_valid = False
                break
        else:
            structure_valid = True

    if not structure_valid:
        structure = make_default_structure(work_type, required_chapters, required_subs)
        context.user_data['structure'] = structure
        logger.info(f"Создана новая структура для {work_type} с {required_chapters} главами")
    else:
        # Добавляем недостающие главы, не трогая существующие
        if len(structure) < required_chapters:
            for i in range(len(structure) + 1, required_chapters + 1):
                chapter_title = f"Глава {i}"
                subs = [f"{i}.{j}" for j in range(1, required_subs + 1)]
                structure.append({"title": chapter_title, "subsections": subs})
            context.user_data['structure'] = structure
            logger.info(f"Добавлены недостающие главы до {required_chapters}")
        # Дополняем подразделы в каждой главе
        for ch_idx, ch in enumerate(structure, start=1):
            subs = ch.get('subsections', [])
            if len(subs) < required_subs:
                current = len(subs)
                for j in range(current + 1, required_subs + 1):
                    subs.append(f"{ch_idx}.{j}")
                ch['subsections'] = subs
                logger.info(f"Добавлены недостающие подразделы в главу {ch_idx}")
        context.user_data['structure'] = structure

    text = "📋 **Текущая структура работы:**\n\n"
    for idx, ch in enumerate(structure, 1):
        text += f"**{idx}. {ch['title']}**\n"
        for sub in ch['subsections']:
            text += f"   • {sub}\n"
        text += "\n"

    buttons = []
    for idx, ch in enumerate(structure, 1):
        buttons.append([InlineKeyboardButton(f"✏️ {ch['title'][:20]}", callback_data=f"edit_chapter_{idx}")])
    buttons.append([InlineKeyboardButton("➕ Добавить главу", callback_data="add_chapter")])
    buttons.append([InlineKeyboardButton("✅ Подтвердить и сгенерировать", callback_data="confirm_structure")])
    buttons.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel_diploma")])
    buttons.append([InlineKeyboardButton("◀️ Назад в меню", callback_data="back_to_menu")])

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode='Markdown')
        await update.callback_query.answer()
    else:
        sent = await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode='Markdown')
        await save_bot_message(context, sent)


async def edit_chapter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    idx = int(query.data.split('_')[-1]) - 1
    context.user_data['editing_chapter_idx'] = idx
    structure = context.user_data['structure']
    ch = structure[idx]
    text = f"**Глава {idx+1}: {ch['title']}**\n\nПодразделы:\n"
    for i, sub in enumerate(ch['subsections'], 1):
        text += f"{i}. {sub}\n"
    buttons = [
        [InlineKeyboardButton("✏️ Переименовать главу", callback_data=f"chapter_rename_{idx}")],
        [InlineKeyboardButton("🗑 Удалить главу", callback_data=f"chapter_delete_{idx}")],
        [InlineKeyboardButton("📝 Редактировать подразделы", callback_data=f"chapter_edit_subs_{idx}")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_to_structure")],
        [InlineKeyboardButton("◀️ Назад в меню", callback_data="back_to_menu")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode='Markdown')
    await save_bot_message(context, query.message)
    return EDIT_CHAPTER


async def handle_edit_chapter_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    parts = data.split('_')
    action = parts[1]
    idx = int(parts[2])
    context.user_data['editing_chapter_idx'] = idx

    if action == 'rename':
        await query.edit_message_text("Введите новое название для главы:")
        await save_bot_message(context, query.message)
        return RENAME_CHAPTER
    elif action == 'delete':
        structure = context.user_data['structure']
        work_type = context.user_data.get('diploma_work_type', 'diploma')
        min_chapters = WORK_TYPES.get(work_type, WORK_TYPES['diploma'])['chapters']
        # Не даём удалить главу, если это первая глава или общее количество станет меньше минимального
        if idx == 0:
            await query.edit_message_text("❌ Нельзя удалить первую главу.")
            await save_bot_message(context, query.message)
            return EDIT_CHAPTER
        if len(structure) <= min_chapters:
            await query.edit_message_text(f"❌ Нельзя удалить главу, минимальное количество для данного типа работы: {min_chapters}.")
            await save_bot_message(context, query.message)
            return EDIT_CHAPTER
        del structure[idx]
        context.user_data['structure'] = structure
        await show_structure_editor(update, context)
        return STRUCTURE_EDIT
    elif action == 'edit_subs':
        return await show_subs_editor(update, context)
    return EDIT_CHAPTER


async def show_subs_editor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    idx = context.user_data['editing_chapter_idx']
    structure = context.user_data['structure']
    ch = structure[idx]
    text = f"**Подразделы главы {idx+1}: {ch['title']}**\n\n"
    for i, sub in enumerate(ch['subsections'], 1):
        text += f"{i}. {sub}\n"
    buttons = []
    for i, sub in enumerate(ch['subsections'], 1):
        buttons.append([InlineKeyboardButton(f"✏️ {sub[:20]}", callback_data=f"sub_rename_{idx}_{i-1}")])
        buttons.append([InlineKeyboardButton(f"🗑 Удалить", callback_data=f"sub_delete_{idx}_{i-1}")])
    buttons.append([InlineKeyboardButton("➕ Добавить подраздел", callback_data=f"sub_add_{idx}")])
    buttons.append([InlineKeyboardButton("◀️ Назад к главе", callback_data=f"back_to_chapter_{idx}")])
    buttons.append([InlineKeyboardButton("◀️ Назад в меню", callback_data="back_to_menu")])
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode='Markdown')
    await save_bot_message(context, update.callback_query.message)
    return EDIT_SUBSECTION


async def handle_edit_subsection_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    parts = data.split('_')
    action = parts[1]
    idx = int(parts[2])
    sub_idx = int(parts[3]) if len(parts) > 3 else None
    context.user_data['editing_chapter_idx'] = idx
    if sub_idx is not None:
        context.user_data['editing_sub_idx'] = sub_idx

    if action == 'rename':
        await query.edit_message_text("Введите новое название для подраздела:")
        await save_bot_message(context, query.message)
        return RENAME_SUBSECTION
    elif action == 'delete':
        structure = context.user_data['structure']
        ch = structure[idx]
        work_type = context.user_data.get('diploma_work_type', 'diploma')
        min_subs = WORK_TYPES.get(work_type, WORK_TYPES['diploma'])['subsections_per_chapter']
        if len(ch['subsections']) <= min_subs:
            await query.edit_message_text(f"❌ Нельзя удалить подраздел, минимальное количество для данного типа работы: {min_subs}.")
            await save_bot_message(context, query.message)
            return EDIT_SUBSECTION
        del ch['subsections'][sub_idx]
        context.user_data['structure'] = structure
        return await show_subs_editor(update, context)
    elif action == 'add':
        await query.edit_message_text("Введите название нового подраздела:")
        await save_bot_message(context, query.message)
        return ADD_SUBSECTION
    return EDIT_SUBSECTION


async def rename_chapter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_name = update.message.text.strip()
    idx = context.user_data['editing_chapter_idx']
    structure = context.user_data['structure']
    structure[idx]['title'] = new_name
    context.user_data['structure'] = structure
    await show_structure_editor(update, context)
    return STRUCTURE_EDIT


async def rename_subsection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_name = update.message.text.strip()
    idx = context.user_data['editing_chapter_idx']
    sub_idx = context.user_data['editing_sub_idx']
    structure = context.user_data['structure']
    structure[idx]['subsections'][sub_idx] = new_name
    context.user_data['structure'] = structure
    return await show_subs_editor(update, context)


async def add_subsection_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_name = update.message.text.strip()
    idx = context.user_data['editing_chapter_idx']
    structure = context.user_data['structure']
    structure[idx]['subsections'].append(new_name)
    context.user_data['structure'] = structure
    return await show_subs_editor(update, context)


async def add_chapter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.edit_message_text("Введите название новой главы:")
    await save_bot_message(context, update.callback_query.message)
    return ADD_CHAPTER


async def add_chapter_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_name = update.message.text.strip()
    structure = context.user_data['structure']
    wt = WORK_TYPES.get(context.user_data.get('diploma_work_type', 'diploma'), WORK_TYPES['diploma'])
    default_subs = wt['subsections_per_chapter']
    chapter_num = len(structure) + 1
    structure.append({"title": new_name, "subsections": [f"{chapter_num}.{i+1}" for i in range(default_subs)]})
    context.user_data['structure'] = structure
    await show_structure_editor(update, context)
    return STRUCTURE_EDIT


async def confirm_structure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    structure = context.user_data['structure']
    work_type = context.user_data['diploma_work_type']
    standard = context.user_data['diploma_standard']
    topic = context.user_data['diploma_topic']
    goal = context.user_data['diploma_goal']
    author = context.user_data['diploma_author']
    supervisor = context.user_data['diploma_supervisor']
    university = context.user_data['diploma_university']
    sources = context.user_data.get('diploma_sources', '')
    extra = context.user_data.get('diploma_extra', '')
    city = extra.split(",")[0] if extra != "-" else "Екатеринбург"

    payload = {
        "topic": topic,
        "work_type": work_type,
        "standard": standard,
        "structure": structure,
        "chapters": [ch['title'] for ch in structure],
        "goal": goal,
        "num_predict": WORK_TYPES.get(work_type, WORK_TYPES['diploma']).get('num_predict', 16000),
        "sources": sources,
        "author": author,
        "university": university,
        "city": city,
        "supervisor": supervisor,
    }
    global task_queue
    if task_queue:
        tid = task_queue.submit(update.effective_user.id, "diploma_full", payload)
        await query.edit_message_text(
            f"🕐 Работа поставлена в очередь (№{tid}). Ожидайте, это может занять несколько минут."
        )
        await save_bot_message(context, query.message)
    else:
        await query.edit_message_text("❌ Система очереди не инициализирована.")
    return ConversationHandler.END


async def cancel_diploma(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.edit_message_text("❌ Создание работы отменено.")
    await save_bot_message(context, update.callback_query.message)
    return ConversationHandler.END


async def back_to_structure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_structure_editor(update, context)
    return STRUCTURE_EDIT


async def back_to_chapter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await edit_chapter(update, context)


# ConversationHandler — обновлён порядок состояний
diploma_conv = ConversationHandler(
    entry_points=[
        CommandHandler("diploma", diploma_start),
        CallbackQueryHandler(diploma_start, pattern="^diploma$"),
    ],
    states={
        DIPLOMA_TYPE: [
            CallbackQueryHandler(diploma_type_callback, pattern="^diploma_type_"),
            CallbackQueryHandler(diploma_start, pattern="^back_to_menu$")
        ],
        DIPLOMA_TOPIC: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, diploma_topic),
            CallbackQueryHandler(diploma_start, pattern="^back_to_menu$")
        ],
        DIPLOMA_STANDARD: [
            CallbackQueryHandler(diploma_standard, pattern="^diploma_std_(?:confirm|change)$"),
            CallbackQueryHandler(diploma_std_set, pattern="^diploma_std_set_"),
            CallbackQueryHandler(diploma_start, pattern="^back_to_menu$")
        ],
        DIPLOMA_GOAL: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, diploma_goal),
            CallbackQueryHandler(diploma_start, pattern="^back_to_menu$")
        ],
        DIPLOMA_AUTHOR: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, diploma_author),
            CallbackQueryHandler(diploma_start, pattern="^back_to_menu$")
        ],
        DIPLOMA_SUPERVISOR: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, diploma_supervisor),
            CallbackQueryHandler(diploma_start, pattern="^back_to_menu$")
        ],
        DIPLOMA_UNIVERSITY: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, diploma_university),
            CallbackQueryHandler(diploma_start, pattern="^back_to_menu$")
        ],
        DIPLOMA_SOURCES: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, diploma_sources),
            CallbackQueryHandler(diploma_start, pattern="^back_to_menu$")
        ],
        DIPLOMA_EXTRA: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, diploma_extra),
            CallbackQueryHandler(diploma_start, pattern="^back_to_menu$")
        ],
        STRUCTURE_EDIT: [
            CallbackQueryHandler(edit_chapter, pattern="^edit_chapter_"),
            CallbackQueryHandler(add_chapter, pattern="^add_chapter$"),
            CallbackQueryHandler(confirm_structure, pattern="^confirm_structure$"),
            CallbackQueryHandler(cancel_diploma, pattern="^cancel_diploma$"),
            CallbackQueryHandler(back_to_structure, pattern="^back_to_structure$"),
            CallbackQueryHandler(diploma_start, pattern="^back_to_menu$")
        ],
        EDIT_CHAPTER: [
            CallbackQueryHandler(handle_edit_chapter_actions, pattern="^chapter_"),
            CallbackQueryHandler(back_to_structure, pattern="^back_to_structure$"),
            CallbackQueryHandler(diploma_start, pattern="^back_to_menu$")
        ],
        ADD_CHAPTER: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, add_chapter_name),
            CallbackQueryHandler(diploma_start, pattern="^back_to_menu$")
        ],
        EDIT_SUBSECTION: [
            CallbackQueryHandler(handle_edit_subsection_actions, pattern="^sub_"),
            CallbackQueryHandler(back_to_chapter, pattern="^back_to_chapter_"),
            CallbackQueryHandler(diploma_start, pattern="^back_to_menu$")
        ],
        RENAME_CHAPTER: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, rename_chapter),
            CallbackQueryHandler(diploma_start, pattern="^back_to_menu$")
        ],
        RENAME_SUBSECTION: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, rename_subsection),
            CallbackQueryHandler(diploma_start, pattern="^back_to_menu$")
        ],
        ADD_SUBSECTION: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, add_subsection_name),
            CallbackQueryHandler(diploma_start, pattern="^back_to_menu$")
        ],
    },
    fallbacks=[CommandHandler("cancel", lambda u,c: ConversationHandler.END)],
    per_message=False,
)