import os
import io
import base64
import logging
import sqlite3
import tempfile
import uuid
from datetime import datetime

import fitz  # PyMuPDF
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics

from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from google import genai
from google.genai import types

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger("tirtira")

TOKEN = os.getenv("BOT_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image")
ADMIN_ID = int(os.getenv("ADMIN_ID", "7268036089"))
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "ahmu2021").lstrip("@")
TELEBIRR = os.getenv("TELEBIRR_NUMBER", "0920210606")
CBE_ACCOUNT = os.getenv("CBE_ACCOUNT", "1000384896287")
CBE_NAME = os.getenv("CBE_NAME", "Ahmed")
DB_PATH = os.getenv("DATABASE_PATH", "tirtira.db")

if not TOKEN:
    raise RuntimeError("BOT_TOKEN is missing. Add it in Render Environment Variables.")
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

def kb(): return ReplyKeyboardMarkup(MENU, resize_keyboard=True)

def db():
    c = sqlite3.connect(DB_PATH); c.row_factory = sqlite3.Row; return c

def init_db():
    c = db(); c.executescript("""
    CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, credits INTEGER NOT NULL DEFAULT 20, referred_by INTEGER, referral_rewarded INTEGER DEFAULT 0, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,credits INTEGER,amount INTEGER,transaction_ref TEXT,screenshot_file_id TEXT,status TEXT DEFAULT 'pending',created_at TEXT,reviewed_at TEXT);
    CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,prompt TEXT,response TEXT,created_at TEXT);
    """); c.commit(); c.close()

def ensure_user(u, ref=None):
    c=db(); row=c.execute("SELECT * FROM users WHERE user_id=?",(u.id,)).fetchone()
    if row is None:
        r = ref if ref and ref != u.id else None
        c.execute("INSERT INTO users(user_id,username,first_name,credits,referred_by,created_at) VALUES(?,?,?,20,?,?)",(u.id,u.username or "",u.first_name or "",r,datetime.utcnow().isoformat()))
        if r:
            c.execute("UPDATE users SET credits=credits+20 WHERE user_id=?",(r,))
            c.execute("UPDATE users SET credits=credits+10, referral_rewarded=1 WHERE user_id=?",(u.id,))
        c.commit(); c.close(); return 30 if r else 20, bool(r)
    c.execute("UPDATE users SET username=?,first_name=? WHERE user_id=?",(u.username or "",u.first_name or "",u.id)); c.commit(); credits=row["credits"]; c.close(); return credits,False

def credits(uid):
    c=db(); r=c.execute("SELECT credits FROM users WHERE user_id=?",(uid,)).fetchone(); c.close(); return r["credits"] if r else 0

def charge(uid,n):
    c=db(); cur=c.execute("UPDATE users SET credits=credits-? WHERE user_id=? AND credits>=?",(n,uid,n)); c.commit(); ok=cur.rowcount==1; c.close(); return ok

def job(uid,prompt,response):
    c=db(); c.execute("INSERT INTO jobs(user_id,prompt,response,created_at) VALUES(?,?,?,?)",(uid,prompt,response,datetime.utcnow().isoformat())); c.commit(); c.close()

async def ask_ai(text, image_bytes=None, mime="image/jpeg", system=None):
    if not client: return SYSTEM_ERROR
    try:
        contents=[text]
        if image_bytes:
            contents=[types.Part.from_bytes(data=image_bytes,mime_type=mime), text]
        r=client.models.generate_content(model=MODEL,contents=contents,config=types.GenerateContentConfig(system_instruction=system or "You are Tirtira Business AI. Answer in clear Amharic or English. Be practical and concise."))
        return r.text or "⚠️ AI ምላሽ አልሰጠም።"
    except Exception:
        logger.exception("Gemini failed"); return SYSTEM_ERROR

async def generate_ai_image(prompt, image_bytes=None, mime="image/jpeg", aspect_ratio="4:5"):
    """Generate or edit an image with Gemini 3.1 Flash Image.
    Uses Google Search grounding when available so advertisements can use current/public information.
    """
    if not client:
        logger.error("GEMINI_API_KEY is missing")
        return None
    try:
        contents = []
        if image_bytes:
            contents = [types.Part.from_bytes(data=image_bytes, mime_type=mime), prompt]
        else:
            contents = [prompt]

        config_kwargs = {
            "response_modalities": ["IMAGE"],
            "response_format": {"image": {"aspect_ratio": aspect_ratio, "image_size": "1K"}},
        }
        try:
            config_kwargs["tools"] = [types.Tool(google_search=types.GoogleSearch())]
        except Exception:
            # Older google-genai versions may not expose the typed GoogleSearch helper.
            pass

        try:
            r = client.models.generate_content(
                model=IMAGE_MODEL,
                contents=contents,
                config=types.GenerateContentConfig(**config_kwargs),
            )
        except Exception:
            # Retry without search grounding; image generation should still work.
            config_kwargs.pop("tools", None)
            r = client.models.generate_content(
                model=IMAGE_MODEL,
                contents=contents,
                config=types.GenerateContentConfig(**config_kwargs),
            )

        for p in getattr(r, "parts", []) or []:
            if getattr(p, "inline_data", None):
                return p.inline_data.data
        for cand in getattr(r, "candidates", []) or []:
            for part in getattr(getattr(cand, "content", None), "parts", []) or []:
                if getattr(part, "inline_data", None):
                    return part.inline_data.data
        logger.warning("Gemini returned no image data")
    except Exception:
        logger.exception("Image generation failed")
    return None

def font(size):
    for path in ["nyala.ttf","/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
        if os.path.exists(path):
            try: return ImageFont.truetype(path,size)
            except Exception: pass
    return ImageFont.load_default()

def fallback_poster(title, subtitle, phone, location):
    W,H=1200,1500; im=Image.new("RGB",(W,H),(245,250,248)); d=ImageDraw.Draw(im)
    for y in range(H):
        t=y/H; d.line((0,y,W,y),fill=(235+int(20*t),248-int(10*t),240-int(30*t)))
    d.rounded_rectangle((50,50,W-50,H-50),radius=45,outline=(20,110,85),width=8)
    d.text((90,110),title,font=font(86),fill=(15,75,65))
    d.text((95,225),subtitle,font=font(45),fill=(50,50,50))
    # simple visual repair toolkit illustration
    d.rounded_rectangle((110,400,1090,900),radius=35,fill=(225,235,235),outline=(70,90,90),width=4)
    d.rounded_rectangle((300,500,900,790),radius=35,fill=(35,40,45))
    d.rounded_rectangle((390,545,810,745),radius=18,fill=(75,155,180))
    d.ellipse((850,430,1030,610),fill=(80,80,80),outline=(20,20,20),width=8); d.ellipse((890,470,990,570),fill=(160,210,220))
    d.line((940,610,940,820),fill=(70,70,70),width=25)
    for x in [150,220,980,1040]: d.line((x,960,x+80,1040),fill=(170,100,50),width=22)
    d.text((100,1120),phone,font=font(58),fill=(20,80,65)); d.text((100,1210),location,font=font(48),fill=(50,50,50))
    d.text((100,1340),"Tirtira Business Studio",font=font(38),fill=(80,80,80))
    out=io.BytesIO(); im.save(out,format="PNG"); return out.getvalue()

def text_to_pdf(text):
    out=io.BytesIO(); c=canvas.Canvas(out,pagesize=A4); w,h=A4
    y=h-55; c.setFont("Helvetica-Bold",16); c.drawString(45,y,"Tirtira Business Studio"); y-=35; c.setFont("Helvetica",11)
    for para in text.splitlines() or [""]:
        if not para: y-=15; continue
        words=para.split(); line=""
        for word in words:
            test=(line+" "+word).strip()
            if c.stringWidth(test,"Helvetica",11)>w-90:
                c.drawString(45,y,line); y-=16; line=word
                if y<50: c.showPage(); y=h-55; c.setFont("Helvetica",11)
            else: line=test
        c.drawString(45,y,line); y-=16
        if y<50: c.showPage(); y=h-55; c.setFont("Helvetica",11)
    c.save(); return out.getvalue()

def photos_to_pdf(images):
    out=io.BytesIO(); c=canvas.Canvas(out,pagesize=A4); w,h=A4
    for data in images:
        im=Image.open(io.BytesIO(data)).convert("RGB"); im.thumbnail((w-50,h-70)); path=None
        with tempfile.NamedTemporaryFile(suffix=".jpg",delete=False) as f: im.save(f.name,"JPEG"); path=f.name
        c.drawImage(path,(w-im.width)/2,(h-im.height)/2,im.width,im.height,preserveAspectRatio=True,anchor='c'); c.showPage(); os.unlink(path)
    c.save(); return out.getvalue()

def pdf_to_text(data):
    doc=fitz.open(stream=data,filetype="pdf"); parts=[]
    for p in doc: parts.append(p.get_text("text"))
    return "\n\n".join(parts).strip()

async def start(update,context):
    ref=None
    if context.args and context.args[0].startswith("ref_") and context.args[0][4:].isdigit(): ref=int(context.args[0][4:])
    cr,referred=ensure_user(update.effective_user,ref)
    msg=f"🤖 Tirtira Business Studio\n\nእንኳን ደህና መጡ! 🇪🇹\n🎁 Credits: {cr}\n\n📸 Advertisement • 🎨 AI Image • 📄 PDF • 📝 Text • 🔎 OCR"
    if referred: msg += "\n\n🎉 Referral bonus: +10 Credits"
    await update.message.reply_text(msg,reply_markup=kb())

async def show_packages(update):
    b=[[InlineKeyboardButton("🟢 100 Credits — 50 ETB",callback_data="pkg_50")],[InlineKeyboardButton("🔵 500 Credits — 200 ETB",callback_data="pkg_200")],[InlineKeyboardButton("🟣 1,000 Credits — 350 ETB",callback_data="pkg_350")],[InlineKeyboardButton("🔥 3,000 Credits — 900 ETB",callback_data="pkg_900")]]
    await update.message.reply_text("💳 Buy Credits\n\nPackage ይምረጡ፦",reply_markup=InlineKeyboardMarkup(b))

async def buy_package(update,context):
    q=update.callback_query; await q.answer(); k=q.data.replace("pkg_","")
    cr,amt=PACKAGES[k]; context.user_data["pending_package"]=(cr,amt); context.user_data["awaiting_ref"]=True
    await q.edit_message_text(f"💳 {cr:,} Credits = {amt} ETB\n\n📱 Telebirr: {TELEBIRR}\n🏦 CBE: {CBE_ACCOUNT}\n👤 Name: {CBE_NAME}\n\n1️⃣ ክፍያ ይፈጽሙ\n2️⃣ Transaction/reference ይላኩ\n3️⃣ Screenshot ይላኩ\n\nAdmin ካረጋገጠ በኋላ Credits ይጨመራሉ።")

def create_payment(uid,cr,amt,ref,pid):
    c=db(); cur=c.execute("INSERT INTO payments(user_id,credits,amount,transaction_ref,screenshot_file_id,status,created_at) VALUES(?,?,?,?,?,'pending',?)",(uid,cr,amt,ref,pid,datetime.utcnow().isoformat())); c.commit(); x=cur.lastrowid; c.close(); return x

async def payment_flow(update,context):
    if context.user_data.get("awaiting_ref") and update.message.text and not update.message.photo:
        context.user_data["payment_ref"]=update.message.text.strip(); context.user_data["awaiting_ref"]=False; context.user_data["awaiting_pay_photo"]=True
        await update.message.reply_text("✅ Reference ተቀብያለሁ። አሁን payment screenshot ላክ።"); return True
    if context.user_data.get("awaiting_pay_photo") and update.message.photo:
        cr,amt=context.user_data.get("pending_package",(0,0)); ref=context.user_data.get("payment_ref",""); pid=update.message.photo[-1].file_id; payment_id=create_payment(update.effective_user.id,cr,amt,ref,pid)
        context.user_data.clear(); buttons=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Approve",callback_data=f"approve_{payment_id}"),InlineKeyboardButton("❌ Reject",callback_data=f"reject_{payment_id}")]])
        try: await context.bot.send_photo(ADMIN_ID,pid,caption=f"💳 NEW PAYMENT #{payment_id}\nUser: {update.effective_user.id}\nCredits: {cr:,}\nAmount: {amt} ETB\nRef: {ref}",reply_markup=buttons)
        except Exception: logger.exception("Admin payment notification failed")
        await update.message.reply_text(f"✅ Payment #{payment_id} ተልኳል። Admin ካረጋገጠ በኋላ Credits ይጨመራሉ።",reply_markup=kb()); return True
    return False

async def admin_review(update,context):
    q=update.callback_query
    if q.from_user.id!=ADMIN_ID: await q.answer("⛔ Admin only",show_alert=True); return
    await q.answer(); action,pid=q.data.split("_"); c=db(); row=c.execute("SELECT * FROM payments WHERE id=?",(int(pid),)).fetchone()
    if not row or row["status"]!="pending": c.close(); await q.edit_message_reply_markup(reply_markup=None); return
    status="approved" if action=="approve" else "rejected"; c.execute("UPDATE payments SET status=?,reviewed_at=? WHERE id=?",(status,datetime.utcnow().isoformat(),int(pid)))
    if action=="approve": c.execute("UPDATE users SET credits=credits+? WHERE user_id=?",(row["credits"],row["user_id"]))
    c.commit(); c.close(); await q.edit_message_reply_markup(reply_markup=None)
    await q.message.reply_text(f"{'✅ Approved' if action=='approve' else '❌ Rejected'} Payment #{pid}")
    try: await context.bot.send_message(row["user_id"],f"{'🎉 Payment approved! Credits added: '+format(row['credits'],',') if action=='approve' else '❌ Payment rejected.'}")
    except Exception: pass

async def make_ad(update,context, photo_bytes=None):
    """Start a professional advertisement workflow. One poster operation costs 10 credits."""
    context.user_data["mode"] = "ad_photo" if photo_bytes else "ad_text"
    if photo_bytes:
        if context.user_data.get("ad_charged") is not True:
            if not charge(update.effective_user.id, COSTS["poster"]):
                await update.message.reply_text("⚠️ 10 Credits ያስፈልጋል።")
                context.user_data.pop("mode", None)
                return
            context.user_data["ad_charged"] = True
        context.user_data["ad_photo_bytes"] = photo_bytes
        await update.message.reply_text("📸 ፎቶው ተቀብያለሁ። የንግዱን ስም፣ አገልግሎት፣ ስልክ እና አካባቢ ጻፍ።")
    else:
        if not charge(update.effective_user.id, COSTS["poster"]):
            await update.message.reply_text("⚠️ 10 Credits ያስፈልጋል።")
            context.user_data.pop("mode", None)
            return
        context.user_data["ad_charged"] = True
        await update.message.reply_text("📸 የማስታወቂያውን ሀሳብ ጻፍ። ለምሳሌ፦ Mobile repair shop — screen replacement, battery service, Addis Ababa, 09xxxxxxxx")

async def handle_photo(update,context):
    data=await (await context.bot.get_file(update.message.photo[-1].file_id)).download_as_bytearray(); data=bytes(data)
    mode=context.user_data.get("mode")
    if mode=="ad_photo":
        context.user_data["ad_photo_bytes"] = data
        await update.message.reply_text("📸 ፎቶው ተቀብያለሁ። አሁን የንግዱን ስም፣ አገልግሎት፣ ስልክ እና አካባቢ ጻፍ።")
        return
    if mode=="photo_pdf":
        if not charge(update.effective_user.id,COSTS["photo_pdf"]): await update.message.reply_text("⚠️ 2 Credits ያስፈልጋል።"); return
        context.user_data.setdefault("pdf_images",[]).append(data); await update.message.reply_text("🖼️ ፎቶ ተጨመረ። ተጨማሪ ፎቶ ላክ ወይም /done ጻፍ።"); return
    if not charge(update.effective_user.id,COSTS["ai"]): await update.message.reply_text("⚠️ Credits አልበቃም።"); return
    ans=await ask_ai("ይህን ምስል ተመልከትና ዋና ዋና ነገሮቹን በአማርኛ ግለጽ።",data,"image/jpeg"); job(update.effective_user.id,"image analysis",ans); await update.message.reply_text(ans,reply_markup=kb())

async def text_handler(update,context):
    u=update.effective_user; ensure_user(u); msg=update.message
    if await payment_flow(update,context): return
    text=(msg.text or "").strip(); mode=context.user_data.get("mode")
    if text=="💰 My Credits": await msg.reply_text(f"💰 Credits: {credits(u.id)}",reply_markup=kb()); return
    if text=="💳 Buy Credits": await show_packages(update); return
    if text=="🎁 Earn Credits":
        me=await context.bot.get_me(); link=f"https://t.me/{me.username}?start=ref_{u.id}"; await msg.reply_text(f"🎁 Referral\n\nይህን link አጋራ፦\n{link}\n\nአዲስ user: +10 Credits\nአንተ: +20 Credits",reply_markup=kb()); return
    if text=="📊 My Jobs":
        c=db(); rows=c.execute("SELECT prompt FROM jobs WHERE user_id=? ORDER BY id DESC LIMIT 5",(u.id,)).fetchall(); c.close(); await msg.reply_text("📊 Last Jobs:\n"+"\n".join("• "+r[0][:80] for r in rows) if rows else "📊 Job የለም።",reply_markup=kb()); return
    if text=="✍️ Writing & Ads":
        context.user_data["mode"]="writing_ads"
        await msg.reply_text("✍️ ምን እንድጽፍልህ? ለምሳሌ፦ Facebook ad, product description, business caption, sales message...")
        return
    if text=="🤖 Business Assistant":
        context.user_data["mode"]="business_ai"
        await msg.reply_text("🤖 የንግድህን ጥያቄ ጻፍ። ምክር፣ pricing idea, marketing, customer reply ወይም business plan ልረዳህ እችላለሁ።")
        return
    if text=="🌐 Translation":
        context.user_data["mode"]="translation"
        await msg.reply_text("🌐 የሚተረጎመውን ጽሁፍ እና የሚፈልገውን ቋንቋ ጻፍ። ለምሳሌ፦ Translate to English: ...")
        return
    if text=="💡 Business Ideas":
        context.user_data["mode"]="business_ideas"
        await msg.reply_text("💡 ምን አይነት business ሀሳብ እንደምትፈልግ ጻፍ። ለምሳሌ፦ Addis Ababa, low budget, online business.")
        return
    if text=="📄 CV & Documents":
        context.user_data["mode"]="cv_docs"
        await msg.reply_text("📄 CV/Document ምን እንድረዳህ ጻፍ። ለምሳሌ፦ professional CV summary ስራልኝ።")
        return
    if text=="🏆 Certificate / PDF":
        context.user_data["mode"]="certificate"
        await msg.reply_text("🏆 የሚፈልገውን legitimate certificate/document text ላክ። እኔ የንድፍ/formatting እገዛ አደርጋለሁ።")
        return
    if text=="📸 Photo Advertisement": await make_ad(update,context); return
    if text=="🎨 AI Image": context.user_data["mode"]="ai_image"; await msg.reply_text("🎨 ምስሉ ምን እንዲሆን እንደምትፈልግ ጻፍ። ለምሳሌ፦ mobile repair shop with microscope and tools, professional Ethiopian advertisement."); return
    if text=="📄 Text → PDF": context.user_data["mode"]="text_pdf"; await msg.reply_text("📄 PDF የሚሆነውን ጽሁፍ ላክ።"); return
    if text=="📝 PDF → Text": context.user_data["mode"]="pdf_text"; await msg.reply_text("📝 PDF ፋይል ላክ።"); return
    if text=="🖼️ Photo → PDF": context.user_data["mode"]="photo_pdf"; context.user_data["pdf_images"]=[]; await msg.reply_text("🖼️ ፎቶዎችን ላክ። ሲጨርስ /done ጻፍ።"); return
    if text=="🔎 PDF OCR": context.user_data["mode"]="ocr"; await msg.reply_text("🔎 Scanned PDF ላክ፤ OCR በAI እንሞክራለን።"); return
    if mode in ("writing_ads", "business_ai", "translation", "business_ideas", "cv_docs", "certificate"):
        system = {
            "writing_ads": "You are a professional marketing copywriter. Create useful, persuasive but truthful business copy.",
            "business_ai": "You are a practical small-business assistant. Give actionable advice without inventing facts.",
            "translation": "You are a precise translator. Preserve meaning and tone. If the requested target language is unclear, ask briefly.",
            "business_ideas": "You are a practical business idea consultant. Give realistic ideas, costs/steps as estimates only when clearly labeled.",
            "cv_docs": "You are a professional CV and document writer. Create clean, professional, truthful content.",
            "certificate": "You help format legitimate certificates and documents. Never fabricate official credentials or claims of authenticity.",
        }.get(mode)
        ans = await ask_ai(text, system=system)
        if ans != SYSTEM_ERROR:
            job(u.id, text, ans)
        await msg.reply_text(ans, reply_markup=kb())
        context.user_data.pop("mode", None)
        return

    if mode=="ai_image":
        if not charge(u.id,COSTS["image"]): await msg.reply_text("⚠️ 15 Credits ያስፈልጋል።"); return
        data=await generate_ai_image("Create a high-quality professional commercial image. "+text+" Avoid fake logos and misleading claims. Clean composition, realistic objects, suitable for social media advertising.")
        if data: await msg.reply_photo(data,caption="🎨 AI Image — Tirtira Business Studio")
        else: await msg.reply_text(SYSTEM_ERROR)
        context.user_data.pop("mode",None); return
    if mode in ("text_pdf",):
        if not charge(u.id,COSTS["pdf"]): await msg.reply_text("⚠️ 2 Credits ያስፈልጋል።"); return
        data=text_to_pdf(text); await msg.reply_document(data,filename="tirtira_document.pdf",caption="📄 Text → PDF"); context.user_data.pop("mode",None); return
    if mode in ("ad_text", "ad_photo"):
        base = context.user_data.get("ad_photo_bytes")
        prompt = (
            "Create a polished, realistic commercial advertisement poster for the business described below. "
            "Use a modern social-media advertising composition, strong visual hierarchy, realistic relevant objects, "
            "clean background, professional lighting, and minimal readable English text. Do not invent logos, phone numbers, "
            "prices, addresses, certifications, or guarantees. If real/public current information is needed, use web search grounding. "
            "Business request: " + text
        )
        img = await generate_ai_image(prompt, base, "image/jpeg", "4:5") if base else await generate_ai_image(prompt, None, "image/jpeg", "4:5")
        if img:
            await msg.reply_photo(img, caption="📸 Professional Advertisement — Tirtira Business Studio")
        else:
            await msg.reply_photo(
                fallback_poster("BUSINESS AD", text[:35] or "Professional Service", "", ""),
                caption="📸 Advertisement — fallback design"
            )
        context.user_data.clear()
        return

    if not charge(u.id,COSTS["ai"]): await msg.reply_text("⚠️ Credits አልበቃም።  💳 Buy Credits ይጫኑ።"); return
    ans=await ask_ai(text); job(u.id,text,ans); await msg.reply_text(ans,reply_markup=kb())

async def document_handler(update,context):
    u=update.effective_user; ensure_user(u); mode=context.user_data.get("mode"); doc=update.message.document
    if not doc: return
    f=await context.bot.get_file(doc.file_id); data=bytes(await f.download_as_bytearray())
    if mode in ("pdf_text","ocr") or (doc.mime_type=="application/pdf" and mode is None):
        cost=COSTS["ocr"] if mode=="ocr" else COSTS["pdf_text"]
        if not charge(u.id,cost): await update.message.reply_text(f"⚠️ {cost} Credits ያስፈልጋል።"); return
        txt=pdf_to_text(data)
        if txt: await update.message.reply_text("📝 PDF Text:\n\n"+txt[:3900])
        else: await update.message.reply_text("🔎 PDF ውስጥ selectable text የለም። ይህ scanned PDF ከሆነ OCR ለማድረግ ይህን አማራጭ ተጠቀም።")
        context.user_data.pop("mode",None); return
    await update.message.reply_text("📄 PDF ፋይል ነው። ከmenu ውስጥ PDF → Text ወይም PDF OCR ምረጥ።")

async def done_cmd(update,context):
    imgs=context.user_data.get("pdf_images",[])
    if not imgs: await update.message.reply_text("🖼️ ምንም ፎቶ አልተላከም።"); return
    data=photos_to_pdf(imgs); await update.message.reply_document(data,filename="tirtira_photos.pdf",caption="🖼️ Photo → PDF"); context.user_data.clear()

async def button_router(update,context):
    q=update.callback_query
    if q.data.startswith("pkg_"): await buy_package(update,context)
    elif q.data.startswith(("approve_","reject_")): await admin_review(update,context)

async def error_handler(update,context): logger.exception("Unhandled error",exc_info=context.error)

def build():
    init_db(); app=Application.builder().token(TOKEN).build(); app.add_handler(CommandHandler("start",start)); app.add_handler(CommandHandler("done",done_cmd)); app.add_handler(CallbackQueryHandler(button_router)); app.add_handler(MessageHandler(filters.Document.ALL,document_handler)); app.add_handler(MessageHandler(filters.PHOTO,handle_photo)); app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,text_handler)); app.add_error_handler(error_handler); return app

if __name__=="__main__": build().run_polling(allowed_updates=Update.ALL_TYPES)
