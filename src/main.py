import asyncio
import logging
import uvicorn

from config import settings
from scheduler import start_scheduler
from discord_bot import bot
from http_server import app

async def start_services():
    # Initialize database (indexes, TTLs)
    from .database import init_db
    await init_db()
    # Initialize scheduler for ingestion and recaps
    start_scheduler()
    # Launch HTTP server and Discord bot concurrently
    config = uvicorn.Config(app=app, host="0.0.0.0", port=8000, log_level="info")
    server = uvicorn.Server(config)
    await asyncio.gather(
        server.serve(),
        bot.start(settings.BOT_TOKEN)
    )

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(start_services())