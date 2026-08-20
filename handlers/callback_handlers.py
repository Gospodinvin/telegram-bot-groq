# handlers/callback_handlers.py
import logging
import tempfile
import os
from datetime import datetime
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.error import BadRequest

import config
import db
from utils.bot_utils import (
    reply_and_save, edit_and_save, save_bot_message, clear_bot_messages,
    check_subscription, get_payment_info
)
from menus.menu_builder import (
    get_main_menu_keyboard, get_back_button, get_create_menu,
    get_export_menu, get_settings_menu, get_subscription_menu,
    get_one_time_menu
)
from handlers.command_handlers import send_main_menu, show_subscription_menu, show_settings_menu
import constants

logger = logging.getLogger(__name__)
task_queue = None

OFFER_TEXT = """
📄 **ПУБЛИЧНАЯ ОФЕРТА НА ОКАЗАНИЕ УСЛУГ**

Настоящая публичная оферта (далее – «Оферта») адресована неопределённому кругу лиц и является официальным предложением лица, указанного в разделе «Реквизиты Исполнителя» (далее – «Исполнитель»), заключить договор на оказание услуг с любым физическим лицом, принявшим условия Оферты (далее – «Заказчик»).

**1. Термины и определения**
1.1. **Бот** – программное обеспечение «LectureX Bot», функционирующее в мессенджере Telegram.
1.2. **Услуги** – предоставление доступа к функционалу Бота в соответствии с выбранным тарифом.
1.3. **Подписка** – платный доступ к расширенным возможностям Бота на определённый срок.
1.4. **Платёж** – добровольное перечисление денежных средств Заказчиком на реквизиты Исполнителя.

**2. Предмет Оферты**
2.1. Исполнитель обязуется предоставить Заказчику доступ к функционалу Бота, а Заказчик обязуется оплатить услуги в порядке, предусмотренном Офертой.
2.2. Услуги считаются оказанными с момента предоставления доступа к Боту.

**3. Порядок заключения договора**
3.1. Договор считается заключённым с момента совершения Заказчиком Платежа за выбранный тариф.
3.2. Факт Платежа является полным и безоговорочным согласием Заказчика со всеми условиями Оферты.

**4. Цена и порядок расчётов**
4.1. Стоимость Услуг определяется действующими тарифами, опубликованными в Боте.
4.2. Платёж осуществляется добровольно на реквизиты Исполнителя.
4.3. Исполнитель не возвращает денежные средства в случае отказа Заказчика от использования Услуг после оплаты.

**5. Ответственность сторон**
5.1. Исполнитель не несёт ответственности за:
   - качество и содержание информации, полученной с помощью Бота (включая, но не ограничиваясь: тексты, конспекты, дипломные работы, переводы, транскрипции);
   - любые косвенные убытки Заказчика, возникшие в результате использования Бота;
   - упущенную выгоду, потерю данных, прерывание в работе Бота;
   - действия третьих лиц, направленные на блокировку Бота или перехват данных.
5.2. Исполнитель предоставляет Услуги «как есть» (as is) без каких-либо гарантий, явных или подразумеваемых.
5.3. В случае предъявления претензий к результатам работы Бота, ответственность Исполнителя ограничивается суммой, уплаченной Заказчиком за конкретную Услугу.
5.4. Заказчик самостоятельно несёт ответственность за использование полученных материалов, включая их соответствие законодательству, академические нормы, авторские права и плагиат.

**6. Порядок разрешения споров**
6.1. Все споры решаются путём переговоров. Если стороны не достигли согласия, спор передаётся на рассмотрение в суд по месту регистрации Исполнителя.
6.2. Досудебный порядок обязателен – претензия рассматривается в течение 10 рабочих дней.

**7. Срок действия Оферты**
7.1. Оферта действует бессрочно до момента отзыва Исполнителем.
7.2. Исполнитель вправе изменять условия Оферты без предварительного уведомления. Новая редакция вступает в силу с момента публикации в Боте.

**8. Реквизиты Исполнителя**
ФИО: Виктория
ИНН: ***********
Телефон: +7 912 654-27-76
Email: ****************

**9. Заключительные положения**
9.1. Принятие Оферты означает, что Заказчик ознакомился и полностью согласен со всеми её пунктами.
9.2. Если Заказчик не согласен с условиями Оферты, он не вправе использовать Бота.

---

*Дата публикации: 01.01.2026*
"""

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data
    message = query.message
    chat_id = message.chat.id

    # ---- Оферта ----
    if data == "show_offer":
        try:
            await query.edit_message_text(
                OFFER_TEXT,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("◀️ Назад", callback_data="back_to_offer_start")],
                    [InlineKeyboardButton("✅ Я ознакомлен и согласен", callback_data="agree_offer")]
                ])
                # parse_mode убран – текст содержит спецсимволы, которые могут сломать Markdown
            )
        except BadRequest:
            await query.message.reply_text(
                OFFER_TEXT,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("◀️ Назад", callback_data="back_to_offer_start")],
                    [InlineKeyboardButton("✅ Я ознакомлен и согласен", callback_data="agree_offer")]
                ])
                # parse_mode убран
            )
        return

    if data == "back_to_offer_start":
        text = (
            "👋 Добро пожаловать в LectureX Bot!\n\n"
            "Перед использованием пожалуйста ознакомьтесь с условиями:\n"
            "📄 [Пользовательское соглашение]"
        )
        buttons = [
            [InlineKeyboardButton("📄 Показать оферту", callback_data="show_offer")],
            [InlineKeyboardButton("✅ Я ознакомлен, далее", callback_data="agree_offer")],
        ]
        try:
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))
        except BadRequest:
            await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))
        return

    if data == "agree_offer":
        db.set_user_flag(user_id, "offer_accepted", True)
        try:
            await query.delete_message()
        except BadRequest:
            pass
        await send_main_menu(update, context)
        return

    # ---- Навигация ----
    if data == "back_to_menu":
        await clear_bot_messages(context, chat_id, keep_last=0)
        try:
            await message.delete()
        except:
            pass
        for key in list(context.user_data.keys()):
            if key in ("action", "awaiting_cancel_id", "waiting_font", "text_from_file", "is_file", "original_filename",
                       "one_time_service", "waiting_for_one_time_receipt", "waiting_for_receipt", "pending_plan",
                       "pending_days", "pending_price_rub", "pending_price_stars"):
                context.user_data.pop(key, None)
        await send_main_menu(update, context)
        return

    # ---- Админ-панель ----
    if data == "admin_payments":
        if user_id != config.ADMIN_ID:
            await query.edit_message_text("⛔ Доступ запрещён.")
            return
        pending = db.get_pending_payments()
        if not pending:
            await query.edit_message_text(
                "✅ Нет ожидающих платежей.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("◀️ Назад в админ-панель", callback_data="admin_back")]
                ])
            )
            return
        for p in pending:
            user_link = f"@{p['username']}" if p['username'] else f"ID: {p['user_id']}"
            text = f"💳 **Платёж #{p['id']}**\n"
            text += f"👤 {user_link}\n"
            if p['service_type'] == 'subscription':
                text += f"📦 Подписка: {p['plan']}\n"
                text += f"💰 {p['amount_rub']}₽ / ⭐{p['amount_stars']}\n"
            else:
                text += f"🔧 Разовая услуга: {p['service_name']}\n"
                text += f"💰 ⭐{p['amount_stars']}\n"
            text += f"📅 Создан: {p['created_at'][:16]}"
            buttons = [
                [InlineKeyboardButton("✅ Подтвердить", callback_data=f"confirm_payment_{p['id']}"),
                 InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_payment_{p['id']}")]
            ]
            await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode='Markdown')
        await query.edit_message_text(
            "⬆️ Список платежей выведен выше.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ Назад в админ-панель", callback_data="admin_back")]
            ])
        )
        return

    if data.startswith("confirm_payment_"):
        if user_id != config.ADMIN_ID:
            await query.edit_message_text("⛔ Доступ запрещён.")
            return
        payment_id = int(data.split("_")[2])
        success = db.confirm_payment(payment_id)
        if success:
            await query.edit_message_text(f"✅ Платёж №{payment_id} подтверждён. Услуга активирована.")
            with db._conn() as conn:
                row = conn.execute("SELECT user_id, service_type, plan, service_name FROM payments WHERE id=?", (payment_id,)).fetchone()
                if row:
                    user_id_recipient = row['user_id']
                    if row['service_type'] == 'subscription':
                        await context.bot.send_message(
                            chat_id=user_id_recipient,
                            text=f"🎉 Ваша подписка «{row['plan']}» активирована! Теперь вам доступны все функции."
                        )
                    else:
                        await context.bot.send_message(
                            chat_id=user_id_recipient,
                            text=f"🎉 Ваша разовая услуга «{row['service_name']}» активирована! Можете воспользоваться ею."
                        )
        else:
            await query.edit_message_text("❌ Не удалось подтвердить платёж (возможно, уже обработан).")
        return

    if data.startswith("reject_payment_"):
        if user_id != config.ADMIN_ID:
            await query.edit_message_text("⛔ Доступ запрещён.")
            return
        payment_id = int(data.split("_")[2])
        success = db.reject_payment(payment_id)
        if success:
            await query.edit_message_text(f"❌ Платёж №{payment_id} отклонён.")
        else:
            await query.edit_message_text("❌ Не удалось отклонить платёж.")
        return

    if data == "admin_back":
        if user_id != config.ADMIN_ID:
            await query.edit_message_text("⛔ Доступ запрещён.")
            return
        buttons = [
            [InlineKeyboardButton("💳 Ожидающие платежи", callback_data="admin_payments")],
            [InlineKeyboardButton("👥 Пользователи (в разработке)", callback_data="admin_users")],
            [InlineKeyboardButton("📊 Статистика (в разработке)", callback_data="admin_stats")],
            [InlineKeyboardButton("◀️ Назад в меню", callback_data="back_to_menu")],
        ]
        await query.edit_message_text(
            "🔐 **Админ-панель**\n\nВыберите действие:",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode='Markdown'
        )
        return

    # ---- Остальные существующие обработчики (меню, оплата, настройки и т.д.) ----
    if data == "menu_create":
        await clear_bot_messages(context, chat_id, keep_last=1)
        await edit_and_save(update, context, "Выберите действие:", reply_markup=get_create_menu())
        return

    if data == "menu_export":
        await clear_bot_messages(context, chat_id, keep_last=1)
        await edit_and_save(update, context, "Выберите формат экспорта:", reply_markup=get_export_menu())
        return

    if data == "menu_settings":
        await clear_bot_messages(context, chat_id, keep_last=1)
        await edit_and_save(update, context, "Настройки:", reply_markup=get_settings_menu())
        return

    if data == "one_time_services":
        await clear_bot_messages(context, chat_id, keep_last=1)
        await edit_and_save(
            update, context,
            "💸 **Разовые услуги**\n\nВыберите нужную услугу. Оплата производится Telegram Stars.\n"
            "После оплаты вы сможете сразу воспользоваться услугой (один раз).\n\n"
            "Если у вас есть подписка – услуги доступны бесплатно.",
            reply_markup=get_one_time_menu(),
            parse_mode='Markdown'
        )
        return

    if data.startswith("pay_one_time_"):
        service = data.replace("pay_one_time_", "")
        if await check_subscription(user_id):
            await query.edit_message_text(
                "✅ У вас уже есть подписка! Услуга доступна бесплатно.\n"
                "Просто выберите её в меню «Создать / Обработать».",
                reply_markup=get_back_button()
            )
            return

        price = config.ONE_TIME_PRICES.get(service, {}).get('stars', 0)
        if not price:
            await query.edit_message_text("❌ Неизвестная услуга.")
            return

        context.user_data['one_time_service'] = service
        text = (
            f"💳 **Оплата разовой услуги**\n\n"
            f"Услуга: {service}\n"
            f"⭐ Стоимость: {price} Telegram Stars\n\n"
            "После оплаты нажмите **«Я оплатил»** и отправьте скриншот чека.\n"
            "Администратор проверит и активирует услугу."
        )
        buttons = [
            [InlineKeyboardButton("✅ Я оплатил", callback_data="one_time_payment_done")],
            [InlineKeyboardButton("◀️ Назад", callback_data="one_time_services")],
        ]
        try:
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode='Markdown')
        except BadRequest:
            await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode='Markdown')
        return

    if data == "one_time_payment_done":
        try:
            await query.edit_message_text(
                "📸 Отправьте скриншот чека (фото) для подтверждения оплаты.\n"
                "После проверки администратор активирует услугу.",
                reply_markup=get_back_button()
            )
        except BadRequest:
            await query.message.reply_text(
                "📸 Отправьте скриншот чека (фото) для подтверждения оплаты.\n"
                "После проверки администратор активирует услугу.",
                reply_markup=get_back_button()
            )
        context.user_data['waiting_for_one_time_receipt'] = True
        return

    if data.startswith("pay_"):
        plan_key = data.split("_")[1]
        plan_names = {'basic': 'Базовый (30 дн.)', 'pro': 'Про (90 дн.)', 'unlimited': 'Безлимитный (365 дн.)'}
        plan_name = plan_names.get(plan_key, plan_key)
        plan_config = config.SUBSCRIPTION_PLANS.get(plan_key, {})
        price_stars = plan_config.get('price_stars', 0)
        price_rub = plan_config.get('price', 0)

        context.user_data['pending_plan'] = plan_key
        context.user_data['pending_days'] = plan_config.get('days', 30)
        context.user_data['pending_price_rub'] = price_rub
        context.user_data['pending_price_stars'] = price_stars

        text = (
            f"💳 **Оплата тарифа «{plan_name}»**\n\n"
            f"⭐ Стоимость: {price_stars} Telegram Stars\n"
            f"📅 Срок: {context.user_data['pending_days']} дней\n\n"
            f"После вычета 30% комиссии Telegram вы получите **{price_rub}₽**.\n\n"
            "Оплата производится через Telegram Stars. Отправьте перевод на @Gospodinvin или нажмите кнопку ниже для оплаты через бота (если подключена интеграция).\n\n"
            "После оплаты нажмите **«Я оплатил»** и отправьте скриншот чека."
        )
        buttons = [
            [InlineKeyboardButton("✅ Я оплатил", callback_data="payment_done")],
            [InlineKeyboardButton("◀️ Назад", callback_data="subscribe")],
            [InlineKeyboardButton("◀️ Назад в меню", callback_data="back_to_menu")],
        ]
        try:
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode='Markdown')
        except BadRequest:
            await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode='Markdown')
        return

    if data == "payment_done":
        try:
            await query.edit_message_text(
                "📸 Отправьте, пожалуйста, скриншот чека (фото) для подтверждения оплаты.\n"
                "После проверки администратор активирует подписку.",
                reply_markup=get_back_button()
            )
        except BadRequest:
            await query.message.reply_text(
                "📸 Отправьте, пожалуйста, скриншот чека (фото) для подтверждения оплаты.\n"
                "После проверки администратор активирует подписку.",
                reply_markup=get_back_button()
            )
        context.user_data['waiting_for_receipt'] = True
        return

    if data.startswith("set_font_"):
        style = data.replace("set_font_", "")
        if style in ["cursive", "print", "handwritten", "elegant"]:
            db.set_user_pref(user_id, "font_style", style)
            try:
                await query.edit_message_text(f"✅ Шрифт изменён на «{style}».")
            except BadRequest:
                await query.message.reply_text(f"✅ Шрифт изменён на «{style}».")
            await send_main_menu(update, context)
        elif style == "user":
            try:
                await query.edit_message_text("Отправьте мне TTF-файл вашего шрифта, и я его загружу.")
            except BadRequest:
                await query.message.reply_text("Отправьте мне TTF-файл вашего шрифта, и я его загружу.")
            context.user_data["waiting_font"] = True
        return

    if data == "cancel_task":
        try:
            await query.edit_message_text(
                "Введите ID задачи для отмены:\n"
                "Пример: `/cancel_task 42`\n"
                "Вы можете узнать ID в сообщении о постановке в очередь."
            )
        except BadRequest:
            await query.message.reply_text(
                "Введите ID задачи для отмены:\n"
                "Пример: `/cancel_task 42`\n"
                "Вы можете узнать ID в сообщении о постановке в очередь."
            )
        context.user_data["awaiting_cancel_id"] = True
        return

    await clear_bot_messages(context, chat_id, keep_last=1)

    action_map = {
        "transcribe": "Отправьте аудио или видео файл для распознавания.",
        "summarize": "Отправьте текст или текстовый файл для создания конспекта.",
        "cheatsheet": "Введите тему, по которой нужна шпаргалка.",
        "humanize": "Отправьте текст или загрузите файл (DOCX, TXT) для гуманизации.\nБот автоматически извлечёт текст из документа.",
        "handwrite": "Отправьте текст для преобразования в рукописный.",
        "quiz": "Отправьте текст (конспект) для генерации теста.",
        "mindmap": "Отправьте текст для построения ментальной карты.",
        "export_pdf": "Отправьте текст для экспорта в PDF (ГОСТ).",
        "export_docx": "Отправьте текст для экспорта в DOCX.",
        "export_pptx": "Отправьте текст для экспорта в PowerPoint.",
        "export_anki": "Отправьте текст с терминами (парами через —, - или :) для экспорта в Anki.",
    }

    if data in action_map:
        try:
            await query.edit_message_text(action_map[data], reply_markup=get_back_button())
        except BadRequest:
            await query.message.reply_text(action_map[data], reply_markup=get_back_button())
        context.user_data["action"] = data
        return

    if data == "diploma":
        if not await check_subscription(user_id):
            try:
                await query.edit_message_text("⚠️ Для создания дипломной работы нужна подписка.")
            except BadRequest:
                await query.message.reply_text("⚠️ Для создания дипломной работы нужна подписка.")
            return
        try:
            await query.edit_message_text(
                "Введите тему дипломной работы:",
                reply_markup=get_back_button()
            )
        except BadRequest:
            await query.message.reply_text(
                "Введите тему дипломной работы:",
                reply_markup=get_back_button()
            )
        context.user_data["action"] = "diploma_start"
        return

    if data == "subscribe":
        await show_subscription_menu(update, context, message=message)
        return

    if data == "settings":
        await show_settings_menu(update, context, message=message)
        return

    if data == "help":
        from handlers.command_handlers import cmd_help
        await cmd_help(update, context)
        return

    try:
        await query.edit_message_text("Неизвестная команда.")
    except BadRequest:
        await query.message.reply_text("Неизвестная команда.")