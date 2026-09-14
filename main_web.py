import os
import logging

from fastapi import FastAPI, Request
from telegram import Update

from main import build

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Tirtira Business Bot")
bot = build()


@app.on_event("startup")
async def startup():
    await bot.initialize()
    await bot.start()

    base_url = (
        os.getenv("WEBHOOK_URL")
        or os.getenv("RENDER_EXTERNAL_URL")
        or ""
    ).rstrip("/")

    if base_url:
        webhook_url = f"{base_url}/telegram/webhook"
        await bot.bot.set_webhook(url=webhook_url)
        logger.info("Telegram webhook set: %s", webhook_url)
    else:
        logger.warning(
            "WEBHOOK_URL/RENDER_EXTERNAL_URL is missing. "
            "Telegram webhook was not configured."
        )


@app.on_event("shutdown")
async def shutdown():
    await bot.stop()
    await bot.shutdown()


@app.get("/")
async def root():
    return {"status": "ok", "service": "Tirtira Business Bot"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.post("/telegram/webhook")
async def webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, bot.bot)
    await bot.process_update(update)
    return {"ok": True}
