import os
import re
import logging
from datetime import datetime
from collections import defaultdict

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is missing.")

MAX_TEXT_LENGTH = 100_000  # chars, protects against abuse
SUPPORT_USERNAME = "@YourSupportUsername"  # change this

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# In-memory stats (per-process, resets on restart — fine for a Render worker)
STATS = {
    "started_at": datetime.utcnow(),
    "total_texts": 0,
    "total_words": 0,
    "unique_users": set(),
}

# ---------------------------------------------------------------------------
# TEXT ANALYSIS
# ---------------------------------------------------------------------------
# Word = sequence of letters/digits/apostrophes, in any Unicode script.
# This correctly handles English, Arabic, Chinese (each char = word),
# Russian, emojis-in-words, and copy-pasted text.
WORD_PATTERN = re.compile(r"[^\W_]+(?:['’-][^\W_]+)*", re.UNICODE)
NUMBER_PATTERN = re.compile(r"^\d+$")
SENTENCE_PATTERN = re.compile(r"[.!?。！？…]+", re.UNICODE)
PARAGRAPH_SPLIT = re.compile(r"\n\s*\n", re.UNICODE)
EMOJI_PATTERN = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E0-\U0001F1FF]+",
    re.UNICODE,
)


def analyze_text(text: str) -> dict:
    """Return a dict with all counts for the given text."""
    if not text:
        return {
            "words": 0, "characters_with_spaces": 0, "characters_without_spaces": 0,
            "sentences": 0, "paragraphs": 0, "numbers": 0, "emojis": 0,
            "lines": 0, "unique_words": 0, "reading_time_min": 0.0,
        }

    words = WORD_PATTERN.findall(text)
    word_count = len(words)
    chars_with = len(text)
    chars_without = len(re.sub(r"\s", "", text))

    # Sentences: count terminators, minimum 1 if there's visible text
    sentence_terminators = SENTENCE_PATTERN.findall(text)
    sentences = len(sentence_terminators)
    if sentences == 0 and text.strip():
        sentences = 1
    # If text ends without punctuation but contains trailing words, add 1
    elif text.strip() and not SENTENCE_PATTERN.search(text.rstrip()[-1:]):
        sentences += 1

    paragraphs = len([p for p in PARAGRAPH_SPLIT.split(text) if p.strip()]) or (1 if text.strip() else 0)
    numbers = sum(1 for w in words if NUMBER_PATTERN.match(w))
    emojis = sum(len(m) for m in EMOJI_PATTERN.findall(text))
    lines = text.count("\n") + 1 if text else 0
    unique_words = len({w.lower() for w in words})
    reading_time = round(word_count / 200, 1)  # avg adult reading speed

    return {
        "words": word_count,
        "characters_with_spaces": chars_with,
        "characters_without_spaces": chars_without,
        "sentences": sentences,
        "paragraphs": paragraphs,
        "numbers": numbers,
        "emojis": emojis,
        "lines": lines,
        "unique_words": unique_words,
        "reading_time_min": reading_time,
    }


def format_result(stats: dict) -> str:
    """Pretty Markdown output for the user."""
    return (
        "📊 **Text Analysis Result**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📝 **Words:** `{stats['words']:,}`\n"
        f"🔤 **Characters (with spaces):** `{stats['characters_with_spaces']:,}`\n"
        f"🔡 **Characters (no spaces):** `{stats['characters_without_spaces']:,}`\n"
        f"📄 **Sentences:** `{stats['sentences']:,}`\n"
        f"📑 **Paragraphs:** `{stats['paragraphs']:,}`\n"
        f"🔢 **Numbers:** `{stats['numbers']:,}`\n"
        f"😀 **Emojis:** `{stats['emojis']:,}`\n"
        f"📏 **Lines:** `{stats['lines']:,}`\n"
        f"🎯 **Unique words:** `{stats['unique_words']:,}`\n"
        f"⏱️ **Reading time:** `~{stats['reading_time_min']} min`"
    )


# ---------------------------------------------------------------------------
# MENUS
# ---------------------------------------------------------------------------
MAIN_MENU = InlineKeyboardMarkup([
    [InlineKeyboardButton("📊 How to Use", callback_data="menu_help")],
    [InlineKeyboardButton("ℹ️ About", callback_data="menu_about"),
     InlineKeyboardButton("📈 Stats", callback_data="menu_stats")],
    [InlineKeyboardButton("💬 Support", callback_data="menu_support")],
])


# ---------------------------------------------------------------------------
# COMMAND HANDLERS
# ---------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    STATS["unique_users"].add(user.id)
    text = (
        f"👋 **Hi {user.first_name or 'there'}!**\n\n"
        "I'm **@Wordscountterbot** — your instant text analyzer.\n\n"
        "**Just send me any text** and I'll count:\n"
        "📝 Words • 🔤 Characters • 📄 Sentences • 📑 Paragraphs\n"
        "🔢 Numbers • 😀 Emojis • 🎯 Unique words • ⏱️ Reading time\n\n"
        "Works with **any language**, emojis, and long texts.\n\n"
        "Commands: /count • /help • /about • /stats"
    )
    await update.message.reply_text(text, reply_markup=MAIN_MENU, parse_mode=ParseMode.MARKDOWN)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "📖 **How to Use @Wordscountterbot**\n\n"
        "**Simplest way:**\n"
        "Just **send me any text** — I'll reply with a full analysis instantly.\n\n"
        "**Commands:**\n"
        "• /start – Welcome menu\n"
        "• /count – Get a reminder to paste text\n"
        "• /help – This message\n"
        "• /about – About the bot\n"
        "• /stats – Global usage statistics\n\n"
        "**What I count:**\n"
        "• Words (any language)\n"
        "• Characters (with & without spaces)\n"
        "• Sentences (recognizes . ! ? 。 ！ ？)\n"
        "• Paragraphs (split by blank lines)\n"
        "• Numbers, emojis, lines\n"
        "• Unique words & estimated reading time\n\n"
        f"⚠️ Max length: {MAX_TEXT_LENGTH:,} characters."
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def count_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # If the user sent "/count some text", analyze the remainder
    if context.args:
        text = " ".join(context.args)
        await process_text(update, text)
        return
    await update.message.reply_text(
        "✍️ **Paste or type the text you want me to count.**\n\n"
        "I'll automatically analyze your next message.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "👨‍💻 **About @Wordscountterbot**\n\n"
        "A fast, accurate, multilingual text analyzer for Telegram.\n\n"
        "**Built with:**\n"
        "• Python 3.11\n"
        "• python-telegram-bot v21.6\n"
        "• Deployed on Render\n\n"
        f"**Support:** {SUPPORT_USERNAME}\n"
        "Version: 1.0.0"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uptime = datetime.utcnow() - STATS["started_at"]
    hours, rem = divmod(int(uptime.total_seconds()), 3600)
    minutes, seconds = divmod(rem, 60)
    text = (
        "📈 **Global Bot Statistics**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 **Unique users:** `{len(STATS['unique_users']):,}`\n"
        f"📨 **Texts analyzed:** `{STATS['total_texts']:,}`\n"
        f"📝 **Total words counted:** `{STATS['total_words']:,}`\n"
        f"⏱️ **Uptime:** `{hours}h {minutes}m {seconds}s`\n\n"
        "_Stats reset when the bot restarts._"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


# ---------------------------------------------------------------------------
# CALLBACK HANDLER
# ---------------------------------------------------------------------------
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "menu_help":
        await query.edit_message_text(
            "📖 **How to Use**\n\n"
            "**Just send me any text** — I'll reply instantly with a full analysis.\n\n"
            "Works with any language, emojis, and long texts.\n\n"
            "Commands: /count /help /about /stats",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data="menu_back")]]
            ),
        )
    elif data == "menu_about":
        await query.edit_message_text(
            "👨‍💻 **About @Wordscountterbot**\n\n"
            "Fast, accurate, multilingual text analyzer.\n"
            "Python 3.11 + python-telegram-bot v21.6 on Render.\n\n"
            f"Support: {SUPPORT_USERNAME}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data="menu_back")]]
            ),
        )
    elif data == "menu_stats":
        uptime = datetime.utcnow() - STATS["started_at"]
        hours, rem = divmod(int(uptime.total_seconds()), 3600)
        minutes, seconds = divmod(rem, 60)
        await query.edit_message_text(
            "📈 **Global Statistics**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"👥 Unique users: `{len(STATS['unique_users']):,}`\n"
            f"📨 Texts analyzed: `{STATS['total_texts']:,}`\n"
            f"📝 Total words: `{STATS['total_words']:,}`\n"
            f"⏱️ Uptime: `{hours}h {minutes}m {seconds}s`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data="menu_back")]]
            ),
        )
    elif data == "menu_support":
        await query.edit_message_text(
            f"💬 **Contact Support**\n\nReach out to: {SUPPORT_USERNAME}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data="menu_back")]]
            ),
        )
    elif data == "menu_back":
        await query.edit_message_text(
            "🏠 **Main Menu**\n\nSend me any text to analyze, or pick an option below:",
            reply_markup=MAIN_MENU,
            parse_mode=ParseMode.MARKDOWN,
        )


# ---------------------------------------------------------------------------
# MESSAGE HANDLER
# ---------------------------------------------------------------------------
async def process_text(update: Update, text: str) -> None:
    """Validate, analyze, and reply with results."""
    if not text or not text.strip():
        await update.message.reply_text(
            "⚠️ **Empty message detected.**\n\n"
            "Please send some text for me to count.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if len(text) > MAX_TEXT_LENGTH:
        await update.message.reply_text(
            f"⚠️ **Text too long.**\n\n"
            f"Maximum length is `{MAX_TEXT_LENGTH:,}` characters. "
            f"Your text has `{len(text):,}` characters.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    try:
        stats = analyze_text(text)
    except Exception:
        logger.exception("Analysis failed")
        await update.message.reply_text(
            "❌ Sorry, I couldn't analyze that text. Please try again."
        )
        return

    # Update global stats
    STATS["total_texts"] += 1
    STATS["total_words"] += stats["words"]
    STATS["unique_users"].add(update.effective_user.id)

    await update.message.reply_text(format_result(stats), parse_mode=ParseMode.MARKDOWN)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Only plain text messages
    if not update.message or not update.message.text:
        return
    await process_text(update, update.message.text)


# ---------------------------------------------------------------------------
# ERROR HANDLER
# ---------------------------------------------------------------------------
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling update:", exc_info=context.error)
    try:
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text(
                "❌ Something went wrong. Please try again or use /start."
            )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main() -> None:
    application = Application.builder().token(BOT_TOKEN).build()

    # Commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("count", count_command))
    application.add_handler(CommandHandler("about", about_command))
    application.add_handler(CommandHandler("stats", stats_command))

    # Buttons
    application.add_handler(CallbackQueryHandler(button_handler))

    # Plain text messages (excludes commands — commands have their own handlers)
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    # Errors
    application.add_error_handler(error_handler)

    logger.info("Bot started. Polling...")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
