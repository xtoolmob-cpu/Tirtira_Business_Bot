import io
import logging
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from telegram import (
    Update, InputFile, ReplyKeyboardMarkup,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters,
)
from google import genai
from google.genai import types

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=os.getenv("LOG_LEVEL", "INFO"),
)
logger = logging.getLogger("tirtira")

TOKEN = os.getenv("BOT_TOKEN", "").strip()
GEMINI_KEY = os.getenv("GEMINI_API_KEY", "").strip()
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or "0")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "").lstrip("@")
TELEBIRR = os.getenv("TELEBIRR_NUMBER", "").strip()
CBE_ACCOUNT = os.getenv("CBE_ACCOUNT", "").strip()
CBE_NAME = os.getenv("CBE_NAME", "").strip()
DB_PATH = os.getenv("DATABASE_PATH", "tirtira.db")
MAX_FILE_MB = int(os.getenv("MAX_FILE_MB", "15"))

if not TOKEN:
    raise RuntimeError("BOT_TOKEN is missing. Add it to your environment variables.")

client = genai.Client(api_key=GEMINI_KEY) if GEMINI_KEY else None

SYSTEM_ERROR = "🙏 ይቅርታ! በSystem ላይ ጊዜያዊ ችግር ተፈጥሯል። እባክዎ ቆይተው እንደገና ይሞክሩ።"
PACKAGES = {"50": (100, 50), "200": (500, 200), "350": (1000, 350), "900": (3000, 900)}
COSTS = {"ai": 1, "pdf": 2, "photo_pdf": 2, "pdf_text": 2, "ocr": 3, "poster": 10, "image": 15}

MENU = [
    ["📸 Photo Advertisement", "🎨 AI Image"],
    ["📄 Text → PDF", "📝 PDF → Text"],
    ["🖼️ Photo → PDF", "🔎 PDF OCR"],
    ["✍️ Writing & Ads", "🤖 Business Assistant"],
    ["🌐 Translation", "💡 Business Ideas"],
    ["📄 CV & Documents", "🏆 Certificate / PDF"],
    ["💰 My Credits", "💳 Buy Credits"],
    ["🎁 Earn Credits", "📊 My Jobs"],
    ["🆘 Support"],
]


def kb():
    return ReplyKeyboardMarkup(MENU, resize_keyboard=True)


def db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    conn.executescript("""
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS users(
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        credits INTEGER NOT NULL DEFAULT 20,
        referred_by INTEGER,
        referral_rewarded INTEGER DEFAULT 0,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS payments(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        credits INTEGER NOT NULL,
        amount INTEGER NOT NULL,
        transaction_ref TEXT NOT NULL,
        screenshot_file_id TEXT,
        status TEXT DEFAULT 'pending',
        created_at TEXT,
        reviewed_at TEXT
    );
    CREATE TABLE IF NOT EXISTS jobs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        prompt TEXT,
        response TEXT,
        created_at TEXT
    );
    """)
    conn.commit()
    conn.close()


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def ensure_user(user, ref=None):
    conn = db()
    row = conn.execute("SELECT * FROM users WHERE user_id=?", (user.id,)).fetchone()
    if row is None:
        referrer = ref if ref and ref != user.id else None
        conn.execute(
            "INSERT INTO users(user_id,username,first_name,credits,referred_by,created_at) VALUES(?,?,?,?,?,?)",
            (user.id, user.username or "", user.first_name or "", 20, referrer, utc_now()),
        )
        if referrer:
            conn.execute("UPDATE users SET credits=credits+20 WHERE user_id=?", (referrer,))
            conn.execute(
                "UPDATE users SET credits=credits+10, referral_rewarded=1 WHERE user_id=?",
                (user.id,),
            )
        conn.commit()
        conn.close()
        return (30 if referrer else 20), bool(referrer)

    conn.execute(
        "UPDATE users SET username=?,first_name=? WHERE user_id=?",
        (user.username or "", user.first_name or "", user.id),
    )
    conn.commit()
    current_credits = row["credits"]
    conn.close()
    return current_credits, False


def credits(uid):
    conn = db()
    row = conn.execute("SELECT credits FROM users WHERE user_id=?", (uid,)).fetchone()
    conn.close()
    return row["credits"] if row else 0


def charge(uid, amount):
    conn = db()
    cur = conn.execute(
        "UPDATE users SET credits=credits-? WHERE user_id=? AND credits>=?",
        (amount, uid, amount),
    )
    conn.commit()
    success = cur.rowcount == 1
    conn.close()
    return success


def refund(uid, amount):
    conn = db()
    conn.execute("UPDATE users SET credits=credits+? WHERE user_id=?", (amount, uid))
    conn.commit()
    conn.close()


def save_job(uid, prompt, response):
    conn = db()
    conn.execute(
        "INSERT INTO jobs(user_id,prompt,response,created_at) VALUES(?,?,?,?)",
        (uid, prompt, response, utc_now()),
    )
    conn.commit()
    conn.close()


def upload(data: bytes, filename: str):
    return InputFile(io.BytesIO(data), filename=filename)


async def ask_ai(prompt, image_bytes=None, mime="image/jpeg", system=None):
    if not client:
        return "⚠️ GEMINI_API_KEY አልተዘጋጀም። Admin እንዲያዘጋጅ ያነጋግሩ።"
    try:
        contents = [prompt]
        if image_bytes:
            contents = [types.Part.from_bytes(data=image_bytes, mime_type=mime), prompt]
        result = client.models.generate_content(
            model=MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system or
                "You are Tirtira Business Studio AI. Answer clearly in Amharic or English. Be accurate and practical."
            ),
        )
        return result.text or "⚠️ AI ምላሽ አልሰጠም።"
    except Exception:
        logger.exception("Gemini text request failed")
        return SYSTEM_ERROR


async def generate_ai_image(prompt, image_bytes=None, mime="image/jpeg", aspect_ratio="4:5"):
    if not client:
        logger.error("GEMINI_API_KEY is missing")
        return None
    try:
        contents = [prompt]
        if image_bytes:
            contents = [types.Part.from_bytes(data=image_bytes, mime_type=mime), prompt]
        config = types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(aspect_ratio=aspect_ratio, image_size="1K"),
        )
        result = client.models.generate_content(
            model=IMAGE_MODEL, contents=contents, config=config
        )
        for part in getattr(result, "parts", []) or []:
            if getattr(part, "inline_data", None):
                return part.inline_data.data
        for candidate in getattr(result, "candidates", []) or []:
            for part in getattr(getattr(candidate, "content", None), "parts", []) or []:
                if getattr(part, "inline_data", None):
                    return part.inline_data.data
        logger.warning("Image model returned no image bytes")
    except Exception:
        logger.exception("Gemini image generation failed")
    return None


def add_ad_text_overlay(image_bytes: bytes, exact_text: str) -> bytes:
    """Add a readable, exact-text panel to an AI-generated ad background."""
    with Image.open(io.BytesIO(image_bytes)) as source:
        image = source.convert("RGBA")

    width, height = image.size
    padding = max(24, int(width * 0.055))
    max_text_width = width - 2 * padding
    font_candidates = [
        os.getenv("AD_FONT_PATH", ""),
        str(Path(__file__).parent / "assets" / "NotoSansEthiopic-Regular.ttf"),
        "/usr/share/fonts/truetype/noto/NotoSansEthiopic-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    font_path = next((f for f in font_candidates if f and Path(f).is_file()), None)

    from PIL import ImageDraw, ImageFont
    draw = ImageDraw.Draw(image)
    font_size = max(18, int(width * 0.043))
    font = None
    while font_size >= 14:
        try:
            font = ImageFont.truetype(font_path, font_size) if font_path else ImageFont.load_default()
        except Exception:
            font = ImageFont.load_default()
        # Wrap on words while measuring actual rendered width.
        lines = []
        for paragraph in (exact_text.strip().splitlines() or [exact_text.strip()]):
            words = paragraph.split()
            if not words:
                lines.append("")
                continue
            current = words[0]
            for word in words[1:]:
                candidate = current + " " + word
                if draw.textbbox((0, 0), candidate, font=font)[2] <= max_text_width:
                    current = candidate
                else:
                    lines.append(current)
                    current = word
            lines.append(current)
        line_gap = max(5, int(font_size * 0.32))
        line_heights = [draw.textbbox((0, 0), line or " ", font=font)[3] - draw.textbbox((0, 0), line or " ", font=font)[1] for line in lines]
        panel_height = sum(line_heights) + line_gap * max(0, len(lines) - 1) + 2 * padding
        if panel_height <= int(height * 0.48):
            break
        font_size -= 2

    if font is None:
        font = ImageFont.load_default()
    # Recompute final line layout at the chosen font size.
    panel_height = sum(line_heights) + line_gap * max(0, len(lines) - 1) + 2 * padding
    panel_top = max(0, height - panel_height)
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    panel = ImageDraw.Draw(overlay)
    panel.rounded_rectangle(
        (max(0, padding // 2), panel_top, width - max(0, padding // 2), height),
        radius=max(12, int(width * 0.025)), fill=(12, 20, 32, 225)
    )
    image = Image.alpha_composite(image, overlay)
    draw = ImageDraw.Draw(image)
    y = panel_top + padding
    for line, line_height in zip(lines, line_heights):
        draw.text((padding, y), line, font=font, fill=(255, 255, 255, 255), stroke_width=0)
        y += line_height + line_gap

    output = io.BytesIO()
    image.convert("RGB").save(output, format="PNG", optimize=True)
    return output.getvalue()


def register_unicode_font():
    candidates = [
        os.getenv("PDF_FONT_PATH", ""),
        "NotoSansEthiopic-Regular.ttf",
        "nyala.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansEthiopic-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            try:
                if "TirtiraUnicode" not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont("TirtiraUnicode", candidate))
                return "TirtiraUnicode"
            except Exception:
                logger.exception("Could not load PDF font: %s", candidate)
    return "Helvetica"


def text_to_pdf(text):
    output = io.BytesIO()
    page_w, page_h = A4
    pdf = canvas.Canvas(output, pagesize=A4)
    font_name = register_unicode_font()
    font_size = 10
    pdf.setTitle("Tirtira Business Studio Document")
    y = page_h - 55
    pdf.setFont(font_name, 15)
    pdf.drawString(42, y, "Tirtira Business Studio")
    y -= 32
    pdf.setFont(font_name, font_size)
    max_width = page_w - 84
    for paragraph in text.splitlines() or [""]:
        if not paragraph.strip():
            y -= 14
            continue
        line = ""
        for word in paragraph.split():
            candidate = (line + " " + word).strip()
            if line and pdf.stringWidth(candidate, font_name, font_size) > max_width:
                if y < 45:
                    pdf.showPage()
                    y = page_h - 50
                    pdf.setFont(font_name, font_size)
                pdf.drawString(42, y, line)
                y -= 15
                line = word
            else:
                line = candidate
        if y < 45:
            pdf.showPage()
            y = page_h - 50
            pdf.setFont(font_name, font_size)
        pdf.drawString(42, y, line)
        y -= 15
    pdf.save()
    return output.getvalue()


def photos_to_pdf(images):
    output = io.BytesIO()
    page_w, page_h = A4
    pdf = canvas.Canvas(output, pagesize=A4)
    for data in images:
        with Image.open(io.BytesIO(data)) as original:
            image = original.convert("RGB")
            image.thumbnail((int(page_w - 50), int(page_h - 70)))
            temp_path = None
            try:
                with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as temp:
                    temp_path = temp.name
                    image.save(temp_path, "JPEG", quality=92)
                pdf.drawImage(
                    temp_path, (page_w-image.width)/2, (page_h-image.height)/2,
                    width=image.width, height=image.height, preserveAspectRatio=True,
                )
                pdf.showPage()
            finally:
                if temp_path and os.path.exists(temp_path):
                    os.unlink(temp_path)
    pdf.save()
    return output.getvalue()


def pdf_to_text(data):
    with fitz.open(stream=data, filetype="pdf") as document:
        return "\n\n".join(page.get_text("text") for page in document).strip()


async def pdf_ocr(data):
    if not client:
        return "⚠️ OCR ለማድረግ GEMINI_API_KEY ያስፈልጋል።"
    try:
        output = []
        with fitz.open(stream=data, filetype="pdf") as document:
            if len(document) > 8:
                return "⚠️ በአንድ ጊዜ እስከ 8 ገጾች ብቻ OCR ማድረግ ይቻላል። PDF ን ከፍለው ይላኩ።"
            for index, page in enumerate(document, start=1):
                pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
                image_bytes = pix.tobytes("png")
                extracted = await ask_ai(
                    "Read the page image and transcribe all visible text faithfully. "
                    "Preserve line breaks and numbers. Do not summarize or guess unclear text.",
                    image_bytes,
                    "image/png",
                    "You are an OCR engine. Transcribe visible text exactly. Mark unreadable parts as [unreadable].",
                )
                output.append(f"--- Page {index} ---\n{extracted}")
        return "\n\n".join(output)
    except Exception:
        logger.exception("PDF OCR failed")
        return SYSTEM_ERROR


def create_payment(uid, package_credits, amount, reference, photo_id):
    conn = db()
    cur = conn.execute(
        """INSERT INTO payments(user_id,credits,amount,transaction_ref,
           screenshot_file_id,status,created_at)
           VALUES(?,?,?,?,?,'pending',?)""",
        (uid, package_credits, amount, reference, photo_id, utc_now()),
    )
    conn.commit()
    payment_id = cur.lastrowid
    conn.close()
    return payment_id


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ref = None
    if context.args and context.args[0].startswith("ref_"):
        raw = context.args[0][4:]
        if raw.isdigit():
            ref = int(raw)
    balance, referred = ensure_user(update.effective_user, ref)
    message = (
        "🤖 Tirtira Business Studio\n\n"
        "እንኳን ደህና መጡ! 🇪🇹\n"
        f"🎁 Credits: {balance}\n\n"
        "📸 Advertisement • 🎨 AI Image • 📄 PDF • 📝 Text • 🔎 OCR"
    )
    if referred:
        message += "\n\n🎉 Referral bonus: +10 Credits"
    await update.message.reply_text(message, reply_markup=kb())


async def show_packages(update):
    buttons = [
        [InlineKeyboardButton("🟢 100 Credits — 50 ETB", callback_data="pkg_50")],
        [InlineKeyboardButton("🔵 500 Credits — 200 ETB", callback_data="pkg_200")],
        [InlineKeyboardButton("🟣 1,000 Credits — 350 ETB", callback_data="pkg_350")],
        [InlineKeyboardButton("🔥 3,000 Credits — 900 ETB", callback_data="pkg_900")],
    ]
    await update.message.reply_text(
        "💳 Credits ለመግዛት Package ይምረጡ፦",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def buy_package(update, context):
    query = update.callback_query
    await query.answer()
    package_key = query.data.removeprefix("pkg_")
    package_credits, amount = PACKAGES[package_key]
    context.user_data["pending_package"] = (package_credits, amount)
    context.user_data["awaiting_ref"] = True

    payment_details = []
    if TELEBIRR:
        payment_details.append(f"📱 Telebirr: {TELEBIRR}")
    if CBE_ACCOUNT:
        payment_details.append(f"🏦 CBE: {CBE_ACCOUNT}")
    if CBE_NAME:
        payment_details.append(f"👤 Name: {CBE_NAME}")
    if not payment_details:
        payment_details.append("⚠️ የክፍያ መረጃ ገና አልተዘጋጀም። Admin ያነጋግሩ።")
    await query.edit_message_text(
        f"💳 {package_credits:,} Credits = {amount} ETB\n\n"
        + "\n".join(payment_details)
        + "\n\n1️⃣ ክፍያ ይፈጽሙ\n"
          "2️⃣ Transaction/reference ይላኩ\n"
          "3️⃣ የክፍያ screenshot ይላኩ\n\n"
          "Admin ካረጋገጠ በኋላ Credits ይጨመራሉ።"
    )


async def payment_flow(update, context):
    message = update.message
    if context.user_data.get("awaiting_ref") and message.text:
        reference = message.text.strip()
        if len(reference) < 3:
            await message.reply_text("⚠️ ትክክለኛ Transaction/reference ያስገቡ።")
            return True
        context.user_data["payment_ref"] = reference
        context.user_data["awaiting_ref"] = False
        context.user_data["awaiting_pay_photo"] = True
        await message.reply_text("✅ Reference ተቀብያለሁ። አሁን የክፍያ screenshot ይላኩ።")
        return True

    if context.user_data.get("awaiting_pay_photo") and message.photo:
        package_credits, amount = context.user_data.get("pending_package", (0, 0))
        reference = context.user_data.get("payment_ref", "")
        photo_id = message.photo[-1].file_id
        payment_id = create_payment(
            update.effective_user.id, package_credits, amount, reference, photo_id
        )
        context.user_data.clear()
        buttons = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_{payment_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_{payment_id}"),
        ]])
        try:
            if ADMIN_ID:
                await context.bot.send_photo(
                    ADMIN_ID, photo_id,
                    caption=(
                        f"💳 NEW PAYMENT #{payment_id}\n"
                        f"User: {update.effective_user.id}\n"
                        f"Credits: {package_credits:,}\nAmount: {amount} ETB\nRef: {reference}"
                    ),
                    reply_markup=buttons,
                )
            else:
                logger.error("ADMIN_ID is not configured; payment needs manual review.")
        except Exception:
            logger.exception("Could not notify admin about payment")
        await message.reply_text(
            f"✅ Payment #{payment_id} ተልኳል። Admin ካረጋገጠ በኋላ Credits ይጨመራሉ።",
            reply_markup=kb(),
        )
        return True
    return False


async def admin_review(update, context):
    query = update.callback_query
    if not ADMIN_ID or query.from_user.id != ADMIN_ID:
        await query.answer("⛔ Admin only", show_alert=True)
        return
    await query.answer()
    action, raw_payment_id = query.data.split("_", 1)
    payment_id = int(raw_payment_id)
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM payments WHERE id=?", (payment_id,)).fetchone()
        if not row or row["status"] != "pending":
            conn.rollback()
            await query.edit_message_reply_markup(reply_markup=None)
            return
        status = "approved" if action == "approve" else "rejected"
        conn.execute(
            "UPDATE payments SET status=?,reviewed_at=? WHERE id=?",
            (status, utc_now(), payment_id),
        )
        if action == "approve":
            conn.execute(
                "UPDATE users SET credits=credits+? WHERE user_id=?",
                (row["credits"], row["user_id"]),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception("Payment review failed")
        await query.message.reply_text("⚠️ Payment review failed. Please retry.")
        return
    finally:
        conn.close()

    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text(
        f"{'✅ Approved' if action == 'approve' else '❌ Rejected'} Payment #{payment_id}"
    )
    try:
        notification = (
            f"🎉 Payment approved! Credits added: {row['credits']:,}"
            if action == "approve" else "❌ Payment rejected. Please contact support."
        )
        await context.bot.send_message(row["user_id"], notification)
    except Exception:
        logger.exception("Could not notify user after payment review")


async def make_ad(update, context):
    if not charge(update.effective_user.id, COSTS["poster"]):
        await update.message.reply_text("⚠️ 10 Credits ያስፈልጋል።")
        return
    context.user_data["mode"] = "ad_text"
    context.user_data["ad_charged"] = True
    context.user_data.pop("ad_photo_bytes", None)
    await update.message.reply_text(
        "📸 የማስታወቂያውን ዝርዝር ይጻፉ፦\n"
        "የንግድ ስም፣ አገልግሎት/ምርት፣ ስልክ፣ አድራሻ።\n\n"
        "ካለዎት የምርት/የንግድ ፎቶ ከዚያ በኋላ መላክ ይችላሉ።"
    )


async def handle_photo(update, context):
    if await payment_flow(update, context):
        return
    photo = update.message.photo[-1]
    telegram_file = await context.bot.get_file(photo.file_id)
    data = bytes(await telegram_file.download_as_bytearray())
    mode = context.user_data.get("mode")

    if mode in ("ad_text", "ad_photo"):
        context.user_data["ad_photo_bytes"] = data
        context.user_data["mode"] = "ad_text"
        await update.message.reply_text(
            "📸 ፎቶው ተቀብያለሁ። አሁን የንግዱን ስም፣ አገልግሎት፣ ስልክና አካባቢ ይጻፉ።"
        )
        return

    if mode == "photo_pdf":
        if not charge(update.effective_user.id, COSTS["photo_pdf"]):
            await update.message.reply_text("⚠️ 2 Credits ያስፈልጋል።")
            return
        context.user_data.setdefault("pdf_images", []).append(data)
        await update.message.reply_text("🖼️ ፎቶ ተጨመረ። ተጨማሪ ፎቶ ይላኩ ወይም /done ይጻፉ።")
        return

    if not charge(update.effective_user.id, COSTS["ai"]):
        await update.message.reply_text("⚠️ Credits አልበቃም።")
        return
    answer = await ask_ai(
        "ይህን ምስል ተመልከትና ዋና ዋና ነገሮቹን በአማርኛ ግለጽ።",
        data, "image/jpeg",
    )
    save_job(update.effective_user.id, "image analysis", answer)
    await update.message.reply_text(answer, reply_markup=kb())


async def text_handler(update, context):
    user = update.effective_user
    ensure_user(user)
    message = update.message
    if await payment_flow(update, context):
        return
    text = (message.text or "").strip()
    mode = context.user_data.get("mode")

    if text == "💰 My Credits":
        await message.reply_text(f"💰 Credits: {credits(user.id)}", reply_markup=kb())
        return
    if text == "💳 Buy Credits":
        await show_packages(update)
        return
    if text == "🎁 Earn Credits":
        me = await context.bot.get_me()
        link = f"https://t.me/{me.username}?start=ref_{user.id}"
        await message.reply_text(
            f"🎁 Referral\n\nይህን link ያጋሩ፦\n{link}\n\n"
            "አዲስ user: +10 Credits\nእርስዎ: +20 Credits",
            reply_markup=kb(),
        )
        return
    if text == "📊 My Jobs":
        conn = db()
        rows = conn.execute(
            "SELECT prompt FROM jobs WHERE user_id=? ORDER BY id DESC LIMIT 5",
            (user.id,),
        ).fetchall()
        conn.close()
        body = "\n".join("• " + (row["prompt"] or "")[:80] for row in rows)
        await message.reply_text("📊 Last Jobs:\n" + (body or "Job የለም።"), reply_markup=kb())
        return
    if text == "🆘 Support":
        support = f"@{ADMIN_USERNAME}" if ADMIN_USERNAME else "Admin"
        await message.reply_text(f"🆘 እገዛ ለማግኘት {support} ያነጋግሩ።", reply_markup=kb())
        return

    menu_modes = {
        "✍️ Writing & Ads": ("writing_ads", "✍️ ምን እንድጽፍልዎ ይፈልጋሉ?"),
        "🤖 Business Assistant": ("business_ai", "🤖 የንግድዎን ጥያቄ ይጻፉ።"),
        "🌐 Translation": ("translation", "🌐 ጽሑፉንና የሚፈልጉትን ቋንቋ ይጻፉ።"),
        "💡 Business Ideas": ("business_ideas", "💡 የሚፈልጉትን የንግድ ሀሳብ ይግለጹ።"),
        "📄 CV & Documents": ("cv_docs", "📄 ለCV/Document ምን እንድረዳዎ ይጻፉ።"),
        "🏆 Certificate / PDF": ("certificate", "🏆 ህጋዊ የሰነድ ጽሑፉን ይላኩ።"),
        "🎨 AI Image": ("ai_image", "🎨 ምስሉ ምን እንዲሆን እንደሚፈልጉ ይጻፉ።"),
        "📄 Text → PDF": ("text_pdf", "📄 PDF የሚሆነውን ጽሑፍ ይላኩ።"),
        "📝 PDF → Text": ("pdf_text", "📝 PDF ፋይል ይላኩ።"),
        "🖼️ Photo → PDF": ("photo_pdf", "🖼️ ፎቶዎችን ይላኩ፤ ሲጨርሱ /done ይጻፉ።"),
        "🔎 PDF OCR": ("ocr", "🔎 OCR ለማድረግ PDF ፋይል ይላኩ።"),
    }
    if text == "📸 Photo Advertisement":
        await make_ad(update, context)
        return
    if text in menu_modes:
        context.user_data["mode"] = menu_modes[text][0]
        if text == "🖼️ Photo → PDF":
            context.user_data["pdf_images"] = []
        await message.reply_text(menu_modes[text][1], reply_markup=kb())
        return

    if mode in ("writing_ads", "business_ai", "translation", "business_ideas", "cv_docs", "certificate"):
        systems = {
            "writing_ads": "You are a professional marketing copywriter. Write persuasive but truthful business copy.",
            "business_ai": "You are a practical small-business assistant. Give actionable advice without inventing facts.",
            "translation": "You are a precise translator. Preserve meaning and tone. Ask if the target language is unclear.",
            "business_ideas": "You are a practical business consultant. Clearly label estimates.",
            "cv_docs": "You are a professional CV and document writer. Be truthful and professional.",
            "certificate": "Help format legitimate documents. Never fabricate official credentials or authenticity.",
        }
        answer = await ask_ai(text, system=systems[mode])
        if answer != SYSTEM_ERROR:
            save_job(user.id, text, answer)
        await message.reply_text(answer, reply_markup=kb())
        context.user_data.pop("mode", None)
        return

    if mode == "ai_image":
        if not charge(user.id, COSTS["image"]):
            await message.reply_text("⚠️ 15 Credits ያስፈልጋል።")
            return
        image_data = await generate_ai_image(
            "Create a professional commercial image. " + text +
            " Avoid fake logos and misleading claims. Clean social-media composition."
        )
        if image_data:
            await message.reply_photo(upload(image_data, "tirtira_ai_image.png"))
            save_job(user.id, text, "AI image generated")
        else:
            refund(user.id, COSTS["image"])
            await message.reply_text(SYSTEM_ERROR)
        context.user_data.pop("mode", None)
        return

    if mode == "text_pdf":
        if not charge(user.id, COSTS["pdf"]):
            await message.reply_text("⚠️ 2 Credits ያስፈልጋል።")
            return
        try:
            pdf_data = text_to_pdf(text)
            await message.reply_document(upload(pdf_data, "tirtira_document.pdf"), caption="📄 Text → PDF")
        except Exception:
            refund(user.id, COSTS["pdf"])
            logger.exception("Text to PDF failed")
            await message.reply_text(SYSTEM_ERROR)
        context.user_data.pop("mode", None)
        return

    if mode in ("ad_text", "ad_photo"):
        photo_bytes = context.user_data.get("ad_photo_bytes")
        prompt = (
            "Create a polished commercial advertisement poster. Use clear visual hierarchy, "
            "relevant realistic objects and a professional social-media layout. Do not invent "
            "logos, phone numbers, prices, addresses, certifications or guarantees. "
            "Use the exact business information supplied by the user:\n" + text
        )
        image_data = await generate_ai_image(prompt, photo_bytes, "image/jpeg", "4:5")
        if image_data:
            try:
                # AI creates the visual background; this panel prints the user's
                # supplied business details verbatim for reliable phone/text accuracy.
                final_ad = add_ad_text_overlay(image_data, text)
            except Exception:
                logger.exception("Advertisement text overlay failed; sending background only")
                final_ad = image_data
            await message.reply_photo(
                upload(final_ad, "business_advertisement.png"),
                caption="✅ ማስታወቂያው ተዘጋጅቷል። የንግድ መረጃው በቀጥታ በምስሉ ላይ ተጨምሯል።"
            )
            save_job(user.id, "Advertisement: " + text, "Poster generated with text overlay")
        else:
            refund(user.id, COSTS["poster"])
            await message.reply_text(SYSTEM_ERROR + "\nCredits ተመላሽ ተደርገዋል።")
        context.user_data.pop("mode", None)
        context.user_data.pop("ad_photo_bytes", None)
        context.user_data.pop("ad_charged", None)
        return

    answer = await ask_ai(text)
    if answer != SYSTEM_ERROR:
        save_job(user.id, text, answer)
    await message.reply_text(answer, reply_markup=kb())


async def document_handler(update, context):
    user = update.effective_user
    ensure_user(user)
    document = update.message.document
    if not document:
        return
    if document.file_size and document.file_size > MAX_FILE_MB * 1024 * 1024:
        await update.message.reply_text(f"⚠️ ፋይሉ ከ{MAX_FILE_MB} MB በላይ ነው። እባክዎ ትንሽ ፋይል ይላኩ።")
        return

    mode = context.user_data.get("mode")
    if document.mime_type != "application/pdf" and not (document.file_name or "").lower().endswith(".pdf"):
        await update.message.reply_text("⚠️ PDF ፋይል ብቻ ይላኩ።")
        return

    file_obj = await context.bot.get_file(document.file_id)
    data = bytes(await file_obj.download_as_bytearray())

    if mode not in ("pdf_text", "ocr") and mode is None:
        await update.message.reply_text("📄 PDF ተቀብያለሁ። ከMenu ውስጥ PDF → Text ወይም PDF OCR ይምረጡ።")
        return

    cost = COSTS["ocr"] if mode == "ocr" else COSTS["pdf_text"]
    if not charge(user.id, cost):
        await update.message.reply_text(f"⚠️ {cost} Credits ያስፈልጋል።")
        return

    try:
        if mode == "ocr":
            result = await pdf_ocr(data)
        else:
            result = pdf_to_text(data)
            if not result:
                result = "🔎 በPDF ውስጥ የሚመረጥ ጽሑፍ አልተገኘም። Scanned PDF ከሆነ PDF OCR ይጠቀሙ።"
        if result == SYSTEM_ERROR:
            refund(user.id, cost)
        else:
            save_job(user.id, "PDF " + mode, result[:3000])
        await update.message.reply_text(("📝 PDF Result:\n\n" + result)[:4000], reply_markup=kb())
    except Exception:
        refund(user.id, cost)
        logger.exception("PDF processing failed")
        await update.message.reply_text(SYSTEM_ERROR)
    context.user_data.pop("mode", None)


async def done_cmd(update, context):
    images = context.user_data.get("pdf_images", [])
    if not images:
        await update.message.reply_text("🖼️ ምንም ፎቶ አልተላከም።")
        return
    try:
        pdf_data = photos_to_pdf(images)
        await update.message.reply_document(upload(pdf_data, "tirtira_photos.pdf"), caption="🖼️ Photo → PDF")
        context.user_data.pop("pdf_images", None)
        context.user_data.pop("mode", None)
    except Exception:
        logger.exception("Photo to PDF failed")
        await update.message.reply_text(SYSTEM_ERROR)


async def cancel_cmd(update, context):
    context.user_data.clear()
    await update.message.reply_text("✅ የአሁኑ ሂደት ተሰርዟል።", reply_markup=kb())


async def button_router(update, context):
    query = update.callback_query
    if query.data.startswith("pkg_"):
        await buy_package(update, context)
    elif query.data.startswith(("approve_", "reject_")):
        await admin_review(update, context)
    else:
        await query.answer()


async def error_handler(update, context):
    logger.error("Unhandled bot error", exc_info=context.error)


def build():
    init_db()
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("done", done_cmd))
    application.add_handler(CommandHandler("cancel", cancel_cmd))
    application.add_handler(CallbackQueryHandler(button_router))
    application.add_handler(MessageHandler(filters.Document.ALL, document_handler))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    application.add_error_handler(error_handler)
    return application


if __name__ == "__main__":
    build().run_polling(allowed_updates=Update.ALL_TYPES)
