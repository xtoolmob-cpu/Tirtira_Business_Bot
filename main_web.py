import logging
import os

from fastapi import FastAPI, Header, HTTPException, Request
from telegram import Update
from main import build

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("tirtira.web")

app = FastAPI(title="Tirtira Business Studio")
bot = build()


@app.on_event("startup")
async def startup():
    await bot.initialize()
    await bot.start()
    base_url = (os.getenv("WEBHOOK_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")
    if not base_url:
        logger.warning("WEBHOOK_URL / RENDER_EXTERNAL_URL not configured; webhook not set.")
        return
    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    webhook_url = f"{base_url}/telegram/webhook"
    await bot.bot.set_webhook(url=webhook_url, secret_token=secret or None)
    logger.info("Telegram webhook configured.")


@app.on_event("shutdown")
async def shutdown():
    await bot.stop()
    await bot.shutdown()


@app.get("/")
async def root():
    return {"status": "ok", "service": "Tirtira Business Studio"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.post("/telegram/webhook")
async def webhook(request: Request, x_telegram_bot_api_secret_token: str | None = Header(default=None)):
    expected = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    if expected and x_telegram_bot_api_secret_token != expected:
        raise HTTPException(status_code=403, detail="Invalid webhook secret")
    payload = await request.json()
    await bot.process_update(Update.de_json(payload, bot.bot))
    return {"ok": True}
