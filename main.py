import os
import logging
import sqlite3
from datetime import datetime

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from google import genai
from google.genai import types

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

ADMIN_ID = int(os.getenv("ADMIN_ID", "7268036089"))
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "ahmu2021").lstrip("@")
TELEBIRR = os.getenv("TELEBIRR_NUMBER", "0920210606")
CBE_ACCOUNT = os.getenv("CBE_ACCOUNT", "1000384896287")
CBE_NAME = os.getenv("CBE_NAME", "Ahmed")

DB_PATH = os.getenv("DATABASE_PATH", "tirtira.db")

PACKAGES = {
    "50": (100, 50),
    "200": (500, 200),
    "350": (1000, 350),
    "900": (3000, 900),
}

if not TOKEN:
    raise RuntimeError("BOT_TOKEN is missing. Add it in Render Environment Variables.")

client = genai.Client(api_key=GEMINI_KEY) if GEMINI_KEY else None

MENU = [
    ["🤖 Business Assistant", "✍️ Writing & Ads"],
    ["🌐 Translation", "💡 Business Ideas"],
    ["📄 CV & Documents", "💬 Ask AI"],
    ["💰 My Credits", "💳 Buy Credits"],
    ["🎁 Earn Credits", "📊 My Jobs"],
    ["⚙️ Settings", "🆘 Support"],
]


def kb():
    return ReplyKeyboardMarkup(MENU, resize_keyboard=True)


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        credits INTEGER NOT NULL DEFAULT 20,
        referred_by INTEGER,
        referral_rewarded INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        credits INTEGER NOT NULL,
        amount INTEGER NOT NULL,
        transaction_ref TEXT,
        screenshot_file_id TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL,
        reviewed_at TEXT
    );

    CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        prompt TEXT NOT NULL,
        response TEXT,
        created_at TEXT NOT NULL
    );
    """)
    conn.commit()
    conn.close()


def ensure_user(tg_user, referred_by=None):
    conn = db()
    row = conn.execute(
        "SELECT * FROM users WHERE user_id=?", (tg_user.id,)
    ).fetchone()

    if row is None:
        ref = referred_by if referred_by and referred_by != tg_user.id else None
        conn.execute(
            """INSERT INTO users
               (user_id, username, first_name, credits, referred_by, created_at)
               VALUES (?, ?, ?, 20, ?, ?)""",
            (
                tg_user.id,
                tg_user.username or "",
                tg_user.first_name or "",
                ref,
                datetime.utcnow().isoformat(),
            ),
        )
        if ref:
            conn.execute(
                "UPDATE users SET credits=credits+20 WHERE user_id=?",
                (ref,),
            )
            conn.execute(
                "UPDATE users SET referral_rewarded=1 WHERE user_id=?",
                (tg_user.id,),
            )
            conn.commit()
            conn.close()
            return 20, True

        conn.commit()
        conn.close()
        return 20, False

    conn.execute(
        "UPDATE users SET username=?, first_name=? WHERE user_id=?",
        (tg_user.username or "", tg_user.first_name or "", tg_user.id),
    )
    conn.commit()
    credits = row["credits"]
    conn.close()
    return credits, False


def get_credits(user_id):
    conn = db()
    row = conn.execute(
        "SELECT credits FROM users WHERE user_id=?", (user_id,)
    ).fetchone()
    conn.close()
    return row["credits"] if row else 0


def change_credits(user_id, amount):
    conn = db()
    cur = conn.execute(
        "UPDATE users SET credits=credits+? WHERE user_id=? AND credits+? >= 0",
        (amount, user_id, amount),
    )
    conn.commit()
    ok = cur.rowcount == 1
    conn.close()
    return ok


def add_job(user_id, prompt, response):
    conn = db()
    conn.execute(
        "INSERT INTO jobs(user_id,prompt,response,created_at) VALUES(?,?,?,?)",
        (user_id, prompt, response, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def create_payment(user_id, credits, amount, transaction_ref, screenshot_file_id):
    conn = db()
    cur = conn.execute(
        """INSERT INTO payments
           (user_id,credits,amount,transaction_ref,screenshot_file_id,status,created_at)
           VALUES(?,?,?,?,?,'pending',?)""",
        (
            user_id,
            credits,
            amount,
            transaction_ref,
            screenshot_file_id,
            datetime.utcnow().isoformat(),
        ),
    )
    conn.commit()
    payment_id = cur.lastrowid
    conn.close()
    return payment_id


def get_payment(payment_id):
    conn = db()
    row = conn.execute(
        "SELECT * FROM payments WHERE id=?", (payment_id,)
    ).fetchone()
    conn.close()
    return row


def review_payment(payment_id, approve):
    conn = db()
    row = conn.execute(
        "SELECT * FROM payments WHERE id=?", (payment_id,)
    ).fetchone()

    if not row or row["status"] != "pending":
        conn.close()
        return None

    status = "approved" if approve else "rejected"
    conn.execute(
        "UPDATE payments SET status=?, reviewed_at=? WHERE id=?",
        (status, datetime.utcnow().isoformat(), payment_id),
    )

    if approve:
        conn.execute(
            "UPDATE users SET credits=credits+? WHERE user_id=?",
            (row["credits"], row["user_id"]),
        )

    conn.commit()
    conn.close()
    return row


def referral_link(username):
    # Bot username is filled at runtime in /start.
    return username


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ref_id = None

    if context.args:
        arg = context.args[0]
        if arg.startswith("ref_") and arg[4:].isdigit():
            ref_id = int(arg[4:])

    credits, referred = ensure_user(user, ref_id)

    welcome = (
        "🤖 Tirtira Business Bot\n\n"
        "እንኳን ደህና መጡ! 🇪🇹\n"
        f"🎁 አሁን {credits} Free Credits አለዎት።\n\n"
        "ከታች ያሉትን Shortcut Buttons ይጠቀሙ።"
    )
    if referred:
        welcome += "\n\n🎉 Referral bonus ተጨምሯል!"

    await update.message.reply_text(welcome, reply_markup=kb())


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_user(update.effective_user)
    await update.message.reply_text(
        "የሚገኙ አገልግሎቶች፦\n"
        "Business • Writing • Translation • CV • AI • Credits • Payment • Referral",
        reply_markup=kb(),
    )


async def ask_ai(text):
    if not client:
        return "⚠️ GEMINI_API_KEY አልተገኘም። Render Environment Variables ውስጥ ያስገቡ።"

    if not text:
        return "💬 እባክዎ ጥያቄዎን ይጻፉ።"

    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=text,
            config=types.GenerateContentConfig(
                system_instruction=(
                    "You are Tirtira Business AI Assistant. "
                    "Support Amharic and English. "
                    "Give practical, concise business help, marketing ideas, "
                    "writing, CV help, and translation assistance."
                ),
            ),
        )
        return response.text or "⚠️ AI ምላሽ አልሰጠም።"
    except Exception:
        logger.exception("Gemini request failed")
        return "⚠️ AI ጊዜያዊ ችግር አጋጥሞታል። እባክዎ በኋላ ይሞክሩ።"


async def show_packages(update: Update):
    buttons = [
        [InlineKeyboardButton("🟢 100 Credits — 50 ETB", callback_data="pkg_50")],
        [InlineKeyboardButton("🔵 500 Credits — 200 ETB", callback_data="pkg_200")],
        [InlineKeyboardButton("🟣 1,000 Credits — 350 ETB", callback_data="pkg_350")],
        [InlineKeyboardButton("🔥 3,000 Credits — 900 ETB", callback_data="pkg_900")],
    ]
    await update.message.reply_text(
        "💳 Buy Credits\n\nPackage ይምረጡ፦",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def buy_package(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key = query.data.replace("pkg_", "")
    if key not in PACKAGES:
        return

    credits, amount = PACKAGES[key]
    context.user_data["pending_package"] = (credits, amount)
    context.user_data["awaiting_payment_ref"] = True

    text = (
        f"💳 Package: {credits:,} Credits = {amount} ETB\n\n"
        f"📱 Telebirr: {TELEBIRR}\n"
        f"🏦 CBE: {CBE_ACCOUNT}\n"
        f"👤 Name: {CBE_NAME}\n\n"
        "1️⃣ ክፍያውን ይፈጽሙ።\n"
        "2️⃣ Transaction/Reference Number ይላኩ።\n"
        "3️⃣ የክፍያ Screenshot ይላኩ።\n\n"
        "ከAdmin ማረጋገጫ በኋላ Credits ይጨመራሉ።"
    )
    await query.edit_message_text(text)


async def payment_ref(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_payment_ref"):
        return False

    if update.message.photo:
        return False

    ref = update.message.text.strip()
    package = context.user_data.get("pending_package")
    if not package:
        return False

    context.user_data["payment_ref"] = ref
    context.user_data["awaiting_payment_ref"] = False
    context.user_data["awaiting_payment_screenshot"] = True

    await update.message.reply_text(
        "✅ Transaction/Reference Number ተቀብያለሁ።\n"
        "📸 አሁን የክፍያ Screenshot ላክ።"
    )
    return True


async def payment_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_payment_screenshot"):
        return False

    package = context.user_data.get("pending_package")
    if not package or not update.message.photo:
        return False

    ref = context.user_data.get("payment_ref", "")
    credits, amount = package
    photo_id = update.message.photo[-1].file_id
    payment_id = create_payment(
        update.effective_user.id, credits, amount, ref, photo_id
    )

    context.user_data.pop("pending_package", None)
    context.user_data.pop("payment_ref", None)
    context.user_data.pop("awaiting_payment_screenshot", None)

    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_{payment_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_{payment_id}"),
        ]
    ])

    caption = (
        "💳 NEW PAYMENT\n\n"
        f"Payment ID: #{payment_id}\n"
        f"User ID: {update.effective_user.id}\n"
        f"Username: @{update.effective_user.username or 'none'}\n"
        f"Credits: {credits:,}\n"
        f"Amount: {amount} ETB\n"
        f"Reference: {ref or 'none'}"
    )

    try:
        await context.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=photo_id,
            caption=caption,
            reply_markup=buttons,
        )
    except Exception:
        logger.exception("Could not notify admin")

    await update.message.reply_text(
        f"✅ Payment #{payment_id} ተልኳል።\n"
        "Admin ካረጋገጠ በኋላ Credits ይጨመራሉ።",
        reply_markup=kb(),
    )
    return True


async def admin_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("⛔ Admin only.", show_alert=True)
        return

    await query.answer()
    parts = query.data.split("_", 1)
    action, pid = parts[0], int(parts[1])
    row = review_payment(pid, action == "approve")

    if not row:
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("⚠️ Payment already reviewed or not found.")
        return

    if action == "approve":
        msg = f"✅ Payment #{pid} approved. {row['credits']:,} Credits added."
        user_msg = (
            f"🎉 Payment #{pid} ተረጋግጧል!\n"
            f"💰 {row['credits']:,} Credits ተጨምረዋል።"
        )
    else:
        msg = f"❌ Payment #{pid} rejected."
        user_msg = f"❌ Payment #{pid} ተቀባይነት አላገኘም።"

    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text(msg)

    try:
        await context.bot.send_message(chat_id=row["user_id"], text=user_msg)
    except Exception:
        logger.exception("Could not notify payment user")


async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    user = update.effective_user
    ensure_user(user)

    # Payment flow has priority.
    if await payment_screenshot(update, context):
        return
    if await payment_ref(update, context):
        return

    text = (update.message.text or "").strip()

    if text == "💳 Buy Credits":
        await show_packages(update)
        return

    if text == "💰 My Credits":
        credits = get_credits(user.id)
        await update.message.reply_text(
            f"💰 Your Credits: {credits:,}\n\n"
            "AI request = 1 Credit",
            reply_markup=kb(),
        )
        return

    if text == "🎁 Earn Credits":
        me = await context.bot.get_me()
        link = f"https://t.me/{me.username}?start=ref_{user.id}"
        await update.message.reply_text(
            "🎁 Earn Credits\n\n"
            "ይህን Referral link ለጓደኞችዎ ያጋሩ።\n"
            "አንድ አዲስ user በlinkዎ ሲመጣ፦\n"
            "👤 እርስዎ +20 Credits\n"
            "👤 አዲሱ user +10 Credits\n\n"
            f"{link}",
            reply_markup=kb(),
        )
        return

    if text == "📊 My Jobs":
        conn = db()
        rows = conn.execute(
            "SELECT prompt, created_at FROM jobs WHERE user_id=? ORDER BY id DESC LIMIT 5",
            (user.id,),
        ).fetchall()
        conn.close()
        if not rows:
            msg = "📊 እስካሁን የተቀመጠ Job የለም።"
        else:
            msg = "📊 Last Jobs:\n\n" + "\n".join(
                f"• {r['prompt'][:70]}" for r in rows
            )
        await update.message.reply_text(msg, reply_markup=kb())
        return

    canned = {
        "🤖 Business Assistant": "💼 የንግድ ጥያቄዎን ይጻፉ።",
        "✍️ Writing & Ads": "✍️ ማስታወቂያ፣ Facebook/Telegram post ወይም የንግድ መግለጫ የሚፈልጉትን ይጻፉ።",
        "🌐 Translation": "🌐 የሚተረጎም ጽሑፍዎን ይላኩ።",
        "💡 Business Ideas": "💡 በጀትዎን እና የንግድ ሀሳብ ፍላጎትዎን ይጻፉ።",
        "📄 CV & Documents": "📄 CV ወይም ደብዳቤ የሚፈልጉትን ይጻፉ።",
        "💬 Ask AI": "💬 ጥያቄዎን በቀጥታ ይጻፉ።",
        "⚙️ Settings": "⚙️ Settings በቀጣይ እትም ይሻሻላል።",
        "🆘 Support": f"🆘 Support: @{ADMIN_USERNAME}",
    }

    if text in canned:
        await update.message.reply_text(canned[text], reply_markup=kb())
        return

    chat = update.effective_chat
    if chat and chat.type in ("group", "supergroup"):
        me = await context.bot.get_me()
        mentioned = bool(
            me.username and f"@{me.username}".lower() in text.lower()
        )
        replied = bool(
            update.message.reply_to_message
            and update.message.reply_to_message.from_user
            and update.message.reply_to_message.from_user.id == me.id
        )
        if not (mentioned or replied):
            return
        if me.username:
            text = text.replace(f"@{me.username}", "").strip()

    credits = get_credits(user.id)
    if credits < 1:
        await update.message.reply_text(
            "⚠️ Credits አልበቃዎትም።\n"
            "💳 Buy Credits ይጫኑ እና package ይምረጡ።",
            reply_markup=kb() if chat and chat.type == "private" else None,
        )
        return

    answer = await ask_ai(text)

    # Only charge when an AI response was actually attempted successfully.
    if not answer.startswith("⚠️"):
        if not change_credits(user.id, -1):
            await update.message.reply_text("⚠️ Credits ለመቀነስ ችግር ተፈጥሯል።")
            return

    add_job(user.id, text, answer)
    await update.message.reply_text(
        answer,
        reply_markup=kb() if chat and chat.type == "private" else None,
    )


async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data.startswith("pkg_"):
        await buy_package(update, context)
    elif query.data.startswith(("approve_", "reject_")):
        await admin_review(update, context)


def build():
    init_db()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CallbackQueryHandler(button_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handler))
    app.add_handler(MessageHandler(filters.PHOTO, handler))
    return app


if __name__ == "__main__":
    build().run_polling(allowed_updates=Update.ALL_TYPES)
