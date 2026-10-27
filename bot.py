import json
import os
import secrets
import logging

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ==================================================
# EXTRA CHEAT 🐍 — НАСТРОЙКИ
# ==================================================

TOKEN = "8757046363:AAH_sxbGCELk5divmluJVWCIrWuiTygmGzo"

ADMIN_ID = 7608889836

MAIN_CHANNEL_ID = -1003957801744
MAIN_CHANNEL_URL = "https://t.me/ExtraCheatStanddof2"

DISCUSSION_CHAT_ID = 0  # ID группы комментариев
BOT_USERNAME = "ExtraCheatbot"

POSTS_FILE = "posts.json"
CHANNELS_FILE = "channels.json"
USERS_FILE = "users.json"

START_IMAGE = "Start.jpg"

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger(__name__)

posts = {}
channels = {}
users = set()
states = {}


# ==================================================
# СОХРАНЕНИЕ ДАННЫХ
# ==================================================

def load_json(filename, default):
    if not os.path.exists(filename):
        return default

    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        log.exception("Ошибка чтения %s", filename)
        return default


def save_json(filename, data):
    temp = filename + ".tmp"

    with open(temp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    os.replace(temp, filename)


def load_data():
    global posts, channels, users

    posts = load_json(POSTS_FILE, {})
    channels = load_json(CHANNELS_FILE, {})
    users = set(load_json(USERS_FILE, []))

    # Главный канал всегда обязателен.
    channels[str(MAIN_CHANNEL_ID)] = {
        "id": MAIN_CHANNEL_ID,
        "title": "EXTRA CHEAT",
        "url": MAIN_CHANNEL_URL,
        "main": True,
    }

    save_json(CHANNELS_FILE, channels)


def save_users():
    save_json(USERS_FILE, sorted(users))


def save_posts():
    save_json(POSTS_FILE, posts)


def save_channels():
    save_json(CHANNELS_FILE, channels)


# ==================================================
# КЛАВИАТУРЫ
# ==================================================

def admin_keyboard():
    return ReplyKeyboardMarkup(
        [["⚙️ Админ-панель"]],
        resize_keyboard=True,
    )


def panel_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["🐍 Создать пост"],
            ["📡 Подписки", "📨 Рассылка"],
            ["🚪 Выйти"],
        ],
        resize_keyboard=True,
    )


def subscription_keyboard(post_id=None):
    buttons = []

    for channel in channels.values():
        url = channel.get("url")
        if url:
            buttons.append([
                InlineKeyboardButton(
                    f"📢 {channel.get('title', 'Канал')}",
                    url=url,
                )
            ])

    buttons.append([
        InlineKeyboardButton(
            "✅ Я подписался — проверить",
            callback_data=(f"check_post:{post_id}" if post_id else "check_subscriptions"),
        )
    ])

    return InlineKeyboardMarkup(buttons)


def password_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ Нет", callback_data="password_no"),
        InlineKeyboardButton("🔐 Да", callback_data="password_yes"),
    ]])


def generate_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "🐍 Сгенерировать ссылку",
            callback_data="generate",
        )
    ]])


def channel_management_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "➕ Добавить канал",
                callback_data="channel_add",
            )
        ],
        [
            InlineKeyboardButton(
                "📋 Список каналов",
                callback_data="channel_list",
            )
        ],
    ])


def channel_list_keyboard():
    buttons = []

    for channel in channels.values():
        channel_id = channel["id"]
        title = channel.get("title", str(channel_id))

        if channel.get("main"):
            buttons.append([
                InlineKeyboardButton(
                    f"🔒 {title} (главный)",
                    callback_data="channel_main",
                )
            ])
        else:
            buttons.append([
                InlineKeyboardButton(
                    f"🗑 Удалить: {title}",
                    callback_data=f"channel_remove:{channel_id}",
                )
            ])

    buttons.append([
        InlineKeyboardButton("⬅️ Назад", callback_data="channel_back")
    ])

    return InlineKeyboardMarkup(buttons)


def post_channel_keyboard(post_id=None):
    buttons = []

    for channel in channels.values():
        url = channel.get("url")
        if url:
            buttons.append([
                InlineKeyboardButton(
                    f"🐍 {channel.get('title', 'Наш канал')}",
                    url=url,
                )
            ])

    if post_id:
        buttons.append([
            InlineKeyboardButton(
                "✅ Проверить подписки",
                callback_data=f"check_post:{post_id}",
            )
        ])

    return InlineKeyboardMarkup(buttons)


# ==================================================
# ПОДПИСКИ
# ==================================================

async def check_channel(bot, user_id, channel_id):
    try:
        member = await bot.get_chat_member(
            chat_id=channel_id,
            user_id=user_id,
        )

        if member.status in ("creator", "administrator", "member"):
            return True

        if member.status == "restricted":
            return bool(getattr(member, "is_member", False))

        return False

    except Exception:
        log.exception("Не удалось проверить канал %s", channel_id)
        return False


async def missing_subscriptions(bot, user_id):
    missing = []

    for channel in channels.values():
        channel_id = channel["id"]

        if not await check_channel(bot, user_id, channel_id):
            missing.append(channel)

    return missing


async def send_subscription_required(bot, chat_id, post_id=None):
    await bot.send_message(
        chat_id=chat_id,
        text=(
            "❗ Для получения материала нужно подписаться "
            "на все обязательные каналы.\n\n"
            "📋 Список обязательных каналов 👇🏻"
        ),
        reply_markup=subscription_keyboard(post_id),
    )


# ==================================================
# МАТЕРИАЛЫ
# ==================================================

def get_material_type(message):
    if message.photo:
        return "photo"
    if message.video:
        return "video"
    if message.document:
        return "document"
    if message.animation:
        return "animation"
    if message.audio:
        return "audio"
    if message.voice:
        return "voice"
    if message.video_note:
        return "video_note"
    if message.sticker:
        return "sticker"
    if message.text is not None:
        return "text"

    return "other"


async def send_material(bot, chat_id, post):
    material_type = post["type"]
    source_chat_id = post["source_chat_id"]
    source_message_id = post["source_message_id"]
    description = post.get("description", "")

    if material_type == "text":
        text = post.get("original_text", "")

        if description:
            text += "\n\n" + description

        await bot.send_message(
            chat_id=chat_id,
            text=text or "🐍 EXTRA CHEAT",
            reply_markup=post_channel_keyboard(),
        )
        return

    if material_type in ("sticker", "video_note", "other"):
        await bot.copy_message(
            chat_id=chat_id,
            from_chat_id=source_chat_id,
            message_id=source_message_id,
        )

        if description:
            await bot.send_message(
                chat_id=chat_id,
                text=description,
                reply_markup=post_channel_keyboard(),
            )
        return

    caption = post.get("original_caption", "")

    if description:
        caption = f"{caption}\n\n{description}" if caption else description

    await bot.copy_message(
        chat_id=chat_id,
        from_chat_id=source_chat_id,
        message_id=source_message_id,
        caption=caption or None,
        reply_markup=post_channel_keyboard(),
    )


async def deliver_post(bot, chat_id, post_id):
    post = posts.get(post_id)

    if not post:
        await bot.send_message(chat_id, "❌ Материал не найден.")
        return

    try:
        await send_material(bot, chat_id, post)
    except Exception:
        log.exception("Ошибка выдачи поста %s", post_id)
        await bot.send_message(
            chat_id,
            "❌ Не удалось отправить материал. Попробуй позже.",
        )


async def request_post(bot, chat_id, user_id, post_id):
    post = posts.get(post_id)

    if not post:
        await bot.send_message(chat_id, "❌ Пост не найден.")
        return

    missing = await missing_subscriptions(bot, user_id)

    if missing:
        await send_subscription_required(bot, chat_id, post_id)
        return

    password = post.get("password", "")

    if password:
        states[user_id] = {
            "step": "get_password",
            "post_id": post_id,
        }

        await bot.send_message(
            chat_id,
            "🔐 EXTRA CHEAT — защищённый материал\n\n"
            "Введи код-пароль, чтобы получить файл и описание.",
        )
        return

    states.pop(user_id, None)
    await deliver_post(bot, chat_id, post_id)


# ==================================================
# START
# ==================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.effective_message

    if not user or not message:
        return

    if user.id not in users:
        users.add(user.id)
        try:
            save_users()
        except OSError:
            log.exception("Не удалось сохранить пользователя")

    if user.id == ADMIN_ID and not context.args:
        states.pop(user.id, None)
        await message.reply_text(
            "🐍 EXTRA CHEAT\n\nДобро пожаловать в админ-панель.",
            reply_markup=admin_keyboard(),
        )
        return

    if not context.args:
        text = (
            "🐍 EXTRA CHEAT • Приветствует\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "📦 Чтобы получить материал, подпишись на обязательные каналы.\n\n"
            "👇🏻 Выбери канал ниже, подпишись и нажми проверку."
        )

        keyboard = subscription_keyboard()

        if os.path.exists(START_IMAGE):
            try:
                with open(START_IMAGE, "rb") as photo:
                    await message.reply_photo(
                        photo=photo,
                        caption=text,
                        reply_markup=keyboard,
                    )
                return
            except Exception:
                log.exception("Не удалось отправить Start.jpg")

        await message.reply_text(text, reply_markup=keyboard)
        return

    argument = context.args[0]

    if not argument.startswith("post_"):
        await message.reply_text("❌ Неверная ссылка.")
        return

    post_id = argument[5:]

    if post_id not in posts:
        await message.reply_text("❌ Пост не найден или ссылка устарела.")
        return

    await request_post(
        context.bot,
        message.chat_id,
        user.id,
        post_id,
    )


# ==================================================
# ДОБАВЛЕНИЕ КАНАЛА
# ==================================================

async def add_channel_from_id(bot, raw_id):
    try:
        chat = await bot.get_chat(int(raw_id.strip()))
    except Exception:
        return False, (
            "❌ Не удалось найти канал.\n\n"
            "Проверь ID и убедись, что бот добавлен в канал "
            "администратором."
        )

    if chat.type != "channel":
        return False, "❌ Это не канал. Отправь ID именно канала."

    try:
        bot_user = await bot.get_me()
        member = await bot.get_chat_member(chat.id, bot_user.id)
        if member.status not in ("administrator", "creator"):
            return False, (
                "❌ Сначала добавь бота в канал администратором, "
                "затем попробуй снова."
            )
    except Exception:
        return False, (
            "❌ Бот не видит канал. Добавь его администратором "
            "и проверь ID."
        )

    key = str(chat.id)

    if key in channels:
        return False, "ℹ️ Этот канал уже есть в обязательных подписках."

    url = f"https://t.me/{chat.username}" if chat.username else ""

    if not url:
        try:
            invite = await bot.create_chat_invite_link(chat.id)
            url = invite.invite_link
        except Exception:
            return False, (
                "❌ Не удалось создать ссылку на канал.\n"
                "Проверь права бота на приглашение пользователей."
            )

    channels[key] = {
        "id": chat.id,
        "title": chat.title or str(chat.id),
        "url": url,
        "main": False,
    }

    save_channels()

    return True, (
        f"✅ Канал добавлен!\n\n"
        f"📢 {chat.title}\n"
        f"🆔 {chat.id}\n\n"
        "Теперь подписка на него обязательна для получения материалов."
    )


async def add_channel_from_forward(bot, message):
    origin = getattr(message, "forward_origin", None)

    if not origin or getattr(origin, "type", None) != "channel":
        return False, (
            "❌ Не вижу пересланную публикацию канала.\n\n"
            "Перешли сюда сообщение именно из канала "
            "или отправь ID канала."
        )

    chat = origin.chat

    return await add_channel_from_id(bot, str(chat.id))


# ==================================================
# АДМИН-ПАНЕЛЬ
# ==================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    message = update.effective_message
    user = update.effective_user

    if not message or not user:
        return

    # Пароль пользователя, который получает пост.
    state = states.get(user.id)

    if state and state.get("step") == "get_password":
        if not message.text:
            await message.reply_text("🔐 Отправь код обычным текстом.")
            return

        post = posts.get(state["post_id"])

        if not post:
            states.pop(user.id, None)
            await message.reply_text("❌ Материал больше не найден.")
            return

        entered = message.text.strip()
        correct = str(post.get("password", ""))

        if secrets.compare_digest(entered, correct):
            post_id = state["post_id"]
            states.pop(user.id, None)

            # Повторно проверяем подписки перед выдачей.
            missing = await missing_subscriptions(context.bot, user.id)

            if missing:
                await send_subscription_required(
                    context.bot,
                    message.chat_id,
                    post_id,
                )
                return

            await message.reply_text("✅ Код верный! Загружаю материал 🐍")
            await deliver_post(context.bot, message.chat_id, post_id)
        else:
            await message.reply_text("❌ Неверный код. Попробуй ещё раз.")
        return

    if user.id != ADMIN_ID:
        return

    text = message.text or ""

    if text == "⚙️ Админ-панель":
        states.pop(user.id, None)
        await message.reply_text(
            "🐍 EXTRA CHEAT — админ-панель",
            reply_markup=panel_keyboard(),
        )
        return

    if text == "🚪 Выйти":
        states.pop(user.id, None)
        await message.reply_text(
            "Ты вышел из админ-панели.",
            reply_markup=admin_keyboard(),
        )
        return

    if text == "📡 Подписки":
        states.pop(user.id, None)
        await message.reply_text(
            "📡 Управление обязательными подписками\n\n"
            "Главный канал EXTRA CHEAT всегда обязателен.\n"
            "Ты можешь добавить дополнительные каналы или удалить их.",
            reply_markup=channel_management_keyboard(),
        )
        return

    if text == "📨 Рассылка":
        states[user.id] = {"step": "broadcast"}
        await message.reply_text(
            "📨 Рассылка EXTRA CHEAT\n\n"
            "Отправь сообщение, фото, видео или файл, "
            "который нужно разослать всем пользователям бота.\n\n"
            "Для отмены напиши: отмена"
        )
        return

    if state and state.get("step") == "broadcast":
        if text.lower().strip() == "отмена":
            states.pop(user.id, None)
            await message.reply_text(
                "❌ Рассылка отменена.",
                reply_markup=panel_keyboard(),
            )
            return

        states.pop(user.id, None)

        sent = 0
        failed = 0

        await message.reply_text("⏳ Начинаю рассылку...")

        for user_id in list(users):
            try:
                await context.bot.copy_message(
                    chat_id=user_id,
                    from_chat_id=message.chat_id,
                    message_id=message.message_id,
                )
                sent += 1
            except Exception:
                failed += 1
                log.warning("Не удалось отправить рассылку пользователю %s", user_id)

        await message.reply_text(
            "✅ Рассылка завершена!\n\n"
            f"📨 Доставлено: {sent}\n"
            f"⚠️ Не доставлено: {failed}",
            reply_markup=panel_keyboard(),
        )
        return

    # Добавление канала по ID или пересланной публикации.
    if state and state.get("step") == "add_channel":
        if message.text and message.text.strip().lower() == "отмена":
            states.pop(user.id, None)
            await message.reply_text(
                "Добавление отменено.",
                reply_markup=panel_keyboard(),
            )
            return

        if getattr(message, "forward_origin", None):
            ok, result = await add_channel_from_forward(
                context.bot,
                message,
            )
        elif message.text:
            ok, result = await add_channel_from_id(
                context.bot,
                message.text,
            )
        else:
            await message.reply_text(
                "Отправь ID канала или перешли публикацию из него."
            )
            return

        if ok:
            states.pop(user.id, None)

        await message.reply_text(
            result,
            reply_markup=channel_management_keyboard(),
        )
        return

    if text == "🐍 Создать пост":
        states[user.id] = {"step": "choose_password"}
        await message.reply_text(
            "🐍 EXTRA CHEAT\n\n"
            "Придумать код-пароль для получения материала?",
            reply_markup=password_keyboard(),
        )
        return

    state = states.get(user.id)

    if not state:
        return

    if state.get("step") == "set_password":
        if not message.text:
            await message.reply_text("❌ Пароль нужно отправить текстом.")
            return

        password = message.text.strip()

        if not password or len(password) > 100:
            await message.reply_text(
                "❌ Пароль должен содержать от 1 до 100 символов."
            )
            return

        state["password"] = password
        state["step"] = "material"

        await message.reply_text(
            "🔐 Пароль сохранён!\n\n"
            "📦 Теперь отправь материал: фото, видео, файл или текст."
)
        return

    if state.get("step") == "material":
        material_type = get_material_type(message)
        post_id = secrets.token_hex(4)

        posts[post_id] = {
            "type": material_type,
            "source_chat_id": message.chat_id,
            "source_message_id": message.message_id,
            "password": state.get("password", ""),
            "description": "",
            "original_text": message.text if material_type == "text" else "",
            "original_caption": message.caption if material_type != "text" else "",
        }

        save_posts()
        states.pop(user.id, None)

        post_link = f"https://t.me/{BOT_USERNAME}?start=post_{post_id}"

        await message.reply_text(
            "✅ Материал успешно сохранён!\n\n"
            f"🔗 Ссылка для получения:\n<code>{post_link}</code>",
            parse_mode="HTML",
            reply_markup=panel_keyboard(),
        )
        return


# ==================================================
# ОБРАБОТЧИК КНОПОК (CALLBACK)
# ==================================================

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user

    if not query or not user:
        return

    await query.answer()
    data = query.data

    if data == "password_no":
        states[user.id] = {"password": "", "step": "material"}
        await query.message.edit_text(
            "📦 Без пароля.\n\nТеперь отправь материал (фото, видео, файл или текст) для поста:"
        )
        return

    if data == "password_yes":
        states[user.id] = {"step": "set_password"}
        await query.message.edit_text(
            "🔐 Введи кодовое слово (пароль) текстом для этого материала:"
        )
        return

    if data.startswith("check_post:"):
        post_id = data.split(":")[1]
        missing = await missing_subscriptions(context.bot, user.id)

        if missing:
            await query.message.reply_text(
                "❌ Ты подписался не на все каналы! Проверь список ниже 👇🏻"
            )
            return

        await query.message.delete()
        await deliver_post(context.bot, query.message.chat_id, post_id)
        return

    if data == "check_subscriptions":
        missing = await missing_subscriptions(context.bot, user.id)

        if missing:
            await query.message.reply_text("❌ Ты подписался ещё не на все каналы.")
        else:
            await query.message.edit_text("✅ Отлично! Все подписки подтверждены.")
        return

    if data == "channel_add":
        states[user.id] = {"step": "add_channel"}
        await query.message.edit_text(
            "➕ Добавление обязательного канала\n\n"
            "Перешли сюда любое сообщение из нужного канала "
            "или отправь его ID (например: <code>-100123456789</code>).\n\n"
            "Для отмены отправь: <code>отмена</code>",
            parse_mode="HTML"
        )
        return

    if data == "channel_list":
        await query.message.edit_text(
            "📋 Список обязательных каналов:",
            reply_markup=channel_list_keyboard()
        )
        return

    if data == "channel_back":
        await query.message.edit_text(
            "📡 Управление обязательными подписками",
            reply_markup=channel_management_keyboard()
        )
        return

    if data == "channel_main":
        await query.answer("🔒 Главный канал нельзя удалить из обязательных.", show_alert=True)
        return

    if data.startswith("channel_remove:"):
        channel_id = data.split(":")[1]
        if channel_id in channels:
            del channels[channel_id]
            save_channels()
        await query.message.edit_text(
            "🗑 Канал удален из обязательных подписок.",
            reply_markup=channel_list_keyboard()
        )
        return


# ==================================================
# ЗАПУСК БОТА
# ==================================================

def main():
    load_data()

    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(callback_handler))
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

    log.info("Бот запущен и готов к работе!")
    application.run_polling()


if __name__ == "__main__":
    main()