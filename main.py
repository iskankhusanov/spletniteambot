import time
import asyncio
import logging
from telegram import Update
from telegram.error import BadRequest
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CommandHandler,
    filters,
    ContextTypes
)

# ---------------- CONFIG ----------------
BOT_TOKEN = "8466367669:AAGjz9x10TjagQdMsQQ7UufoaSuD_JX_RoQ"
CHANNEL_ID = "@spletniteam"   # or numeric ID, e.g. -1001234567890
ADMIN_ID = 3322252            # your Telegram user ID
COOLDOWN_SECONDS = 15
POST_DELAY_SECONDS = 30       # updated to 30 seconds
# ----------------------------------------

# runtime stores
last_message_time = {}
admin_map = {}
user_thread_header = {}
scheduled_posts = {}

# logging
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------------- HELPERS ----------------
async def schedule_post(context: ContextTypes.DEFAULT_TYPE, user_id: int, orig_message_id: int):
    key = (user_id, orig_message_id)
    try:
        logger.info("Will post user=%s msg_id=%s in %s seconds", user_id, orig_message_id, POST_DELAY_SECONDS)
        await asyncio.sleep(POST_DELAY_SECONDS)

        await context.bot.copy_message(
            chat_id=CHANNEL_ID,
            from_chat_id=user_id,
            message_id=orig_message_id
        )
        logger.info("Posted message from user=%s msg_id=%s to channel %s", user_id, orig_message_id, CHANNEL_ID)

        # Notify admin
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"✅ Message from `{user_id}` posted to channel.",
                parse_mode="Markdown"
            )
        except Exception as exc:
            logger.warning("Couldn't notify admin: %s", exc)

    except asyncio.CancelledError:
        logger.info("Scheduled post for %s cancelled.", key)
    except BadRequest as e:
        logger.warning("Failed to post message from %s msg %s: %s", user_id, orig_message_id, e.message)
        try:
            await context.bot.send_message(chat_id=ADMIN_ID, text=f"⚠️ Failed to post message from `{user_id}`: {e.message}", parse_mode="Markdown")
        except Exception:
            pass
    except Exception as e:
        logger.exception("Unexpected error while scheduling post: %s", e)
    finally:
        scheduled_posts.pop(key, None)

# ---------------- HANDLERS ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Что там!\n\n"
        "Напишите нам анонимное сообщение, и мы его опубликуем на канале в ближайшее время.\n\n"
        "🇬🇧 What's up!\n\n"
        "Write us an anonymous message and we will post it on the channel as soon as possible."
    )

async def send_anonymously(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or msg.chat.type != "private":
        return

    if msg.from_user and msg.from_user.is_bot:
        return

    user_id = msg.from_user.id
    now = time.time()
    last_time = last_message_time.get(user_id, 0)

    # cooldown
    if now - last_time < COOLDOWN_SECONDS:
        remaining = int(COOLDOWN_SECONDS - (now - last_time))
        await msg.reply_text(
            f"⏳ Подождите {remaining} сек. перед следующей отправкой.\n\n"
            f"🇬🇧 Please wait {remaining} sec before sending another message."
        )
        logger.info("User %s hit cooldown (remaining %ss)", user_id, remaining)
        return

    last_message_time[user_id] = now
    await msg.reply_text("Heard you\n\nУслышал вас")
    logger.info("Received message from user=%s msg_id=%s", user_id, msg.message_id)

    # Admin thread header
    if user_thread_header.get(user_id) is None:
        try:
            header_msg = await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"💬 New conversation with user `{user_id}` (anonymous).",
                parse_mode="Markdown"
            )
            user_thread_header[user_id] = header_msg.message_id
            admin_map[header_msg.message_id] = user_id
        except Exception as e:
            logger.warning("Could not create admin thread header: %s", e)

    # Copy message to admin
    try:
        copied = await context.bot.copy_message(
            chat_id=ADMIN_ID,
            from_chat_id=user_id,
            message_id=msg.message_id
        )
        admin_map[copied.message_id] = user_id
    except Exception as e:
        logger.warning("Could not copy message to admin: %s", e)

    # Schedule posting for all messages (text or media)
    key = (user_id, msg.message_id)
    if key in scheduled_posts:
        logger.info("Scheduled post already exists for %s; skipping.", key)
        return

    task = asyncio.create_task(schedule_post(context, user_id, msg.message_id))
    scheduled_posts[key] = task
    logger.info("Scheduled post for user=%s orig_msg=%s in %s seconds", user_id, msg.message_id, POST_DELAY_SECONDS)

async def admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or msg.chat_id != ADMIN_ID or not msg.reply_to_message:
        return

    replied_admin_msg_id = msg.reply_to_message.message_id
    user_id = admin_map.get(replied_admin_msg_id)
    if not user_id:
        await msg.reply_text("⚠️ Could not find which user this reply should go to.")
        return

    try:
        if msg.text:
            await context.bot.send_message(chat_id=user_id, text=msg.text)
            await msg.reply_text("✅ Sent your reply to the user (anonymously).")
            try:
                copied_back = await context.bot.copy_message(chat_id=ADMIN_ID, from_chat_id=ADMIN_ID, message_id=msg.message_id)
                admin_map[copied_back.message_id] = user_id
            except Exception:
                pass
    except Exception as e:
        await msg.reply_text("⚠️ Failed to send reply.")
        logger.exception("Error sending admin reply: %s", e)

# ---------------- MAIN ----------------
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.REPLY & filters.TEXT, admin_reply))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, send_anonymously))

    logger.info("Bot started. Cooldown=%ss. Post delay=%ss. Channel=%s", COOLDOWN_SECONDS, POST_DELAY_SECONDS, CHANNEL_ID)
    app.run_polling()
