import asyncio
import logging
import sys
from os import getenv

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import Message, BotCommand, Update
from dotenv import load_dotenv

from bot.handlers import router as main_router
from database.db import init_db, add_user
from services.alerts import setup_scheduler, check_alerts
from aiohttp import web

# Configure logging FIRST so all modules can use it
logging.basicConfig(level=logging.INFO, stream=sys.stdout)

load_dotenv()

TOKEN = getenv("BOT_TOKEN")
PORT = int(getenv("PORT", 8080))

# Initialize Bot
bot = None
if TOKEN:
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

dp = Dispatcher()
dp.include_router(main_router)

# --- FastAPI Setup for Vercel Serverless ---
from fastapi import FastAPI, Request, HTTPException

app = FastAPI(title="Crypto Alert Bot Serverless")

@app.post("/webhook")
async def webhook_handler(request: Request):
    if not bot:
        raise HTTPException(status_code=500, detail="Bot not initialized")
    try:
        payload = await request.json()
        await init_db()
        update = Update.model_validate(payload, context={"bot": bot})
        await dp.feed_update(bot, update)
        return {"status": "ok"}
    except Exception as e:
        logging.error(f"Error handling webhook: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/check-alerts")
async def cron_alerts_handler():
    if not bot:
        raise HTTPException(status_code=500, detail="Bot not initialized")
    
    try:
        await init_db()
        logging.info("Checking alerts via serverless cron endpoint...")
        await check_alerts(bot)
        return {"status": "ok", "message": "Alerts checked successfully"}
    except Exception as e:
        logging.error(f"Error during alert checks: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/set-webhook")
async def set_webhook_handler(request: Request):
    if not bot:
        raise HTTPException(status_code=500, detail="Bot not initialized")
    
    host = request.headers.get("host")
    scheme = "https" if "vercel.app" in host or "localhost" not in host else "http"
    webhook_url = f"{scheme}://{host}/webhook"
    
    try:
        await bot.set_webhook(webhook_url)
        return {"status": "ok", "message": f"Webhook successfully set to {webhook_url}"}
    except Exception as e:
        logging.error(f"Error setting webhook: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/")
async def root_handler():
    return {"status": "alive", "service": "Crypto Alert Bot Webhook"}


# --- Local Web Server for non-Serverless runs ---
async def handle_ping(request):
    return web.Response(text="Bot is alive!")

async def handle_health(request):
    return web.Response(text="OK", status=200)

async def start_web_server():
    app_http = web.Application()
    app_http.router.add_get("/", handle_ping)
    app_http.router.add_get("/health", handle_health)
    runner = web.AppRunner(app_http)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logging.info(f"✅ Web server started on port {PORT}")


@dp.message(CommandStart())
async def command_start_handler(message: Message) -> None:
    await add_user(message.from_user.id, message.from_user.username)
    await message.answer(
        f"Hello, <b>{message.from_user.full_name}</b>!\n\n"
        "Welcome to the <b>Crypto Analytics & Alert Bot</b>. 🚀\n\n"
        "I can help you track real-time prices for any coin on decentralized exchanges.\n\n"
        "<b>Commands:</b>\n"
        "🔍 /search - Find a coin\n"
        "🔔 /alerts - Set price alerts\n"
        "❓ /help - See all commands"
    )

async def set_commands(bot: Bot):
    commands = [
        BotCommand(command="start", description="Start the bot"),
        BotCommand(command="search", description="Search for a coin"),
        BotCommand(command="alerts", description="Manage alerts"),
        BotCommand(command="help", description="Show help")
    ]
    await bot.set_my_commands(commands)

async def main() -> None:
    if not TOKEN:
        logging.error("❌ BOT_TOKEN environment variable is not set!")
        sys.exit(1)

    # Initialize DB
    try:
        await init_db()
        logging.info("✅ Database initialized successfully.")
    except Exception as e:
        logging.error(f"❌ Failed to initialize database: {e}")
        sys.exit(1)
    
    bot_local = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    
    # Setup background alerts
    setup_scheduler(bot_local)
    
    # Start the local web server FIRST
    await start_web_server()
    
    await set_commands(bot_local)
    logging.info("🤖 Bot is starting polling...")
    await dp.start_polling(bot_local)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot stopped!")

