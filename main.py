import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import asyncio
from datetime import datetime, timezone, timedelta

load_dotenv()

import db
import ingestion

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# MongoDB setup
#MONGO_URI = os.getenv("MONGO_URI")
collection = db.db["news_items"]  # Use the collection from db.py

# Scheduler setup
scheduler = AsyncIOScheduler()

async def fetch_and_store_news():
    # Replace with your actual data fetching logic
    news_item = {
        "title": "Sample News",
        "content": "This is a sample news item.",
        "timestamp": datetime.datetime.utcnow()
    }
    collection.insert_one(news_item)
    print("Fetched and stored news.")

since = datetime.now(timezone.utc)

async def post_news():
    global since
    channel_id = int(os.environ.get("NEWS_CHANNEL_ID"))  # Set this in your .env
    channel = bot.get_channel(channel_id)
    if channel:
        # Find news from the last cycle (e.g., last 2 minutes)
        
        new_items: list[ingestion.NewsItem] = [ingestion.NewsItem(**item) for item in list(collection.find({"ingest_timestamp": {"$gte": since}}))]
        since = datetime.now(timezone.utc)  # Update the since variable for the next cycle
        for item in new_items:
            await channel.send(f"# [{item.title}](<{item.url}>)\n{item.description}\n```Categories: {','.join(item.categories)}\nPublished at: {item.publish_timestamp.strftime('%Y-%m-%d %H:%M:%S')}\nSource: {item.source}```")
        print("Posted news to channel.")

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name} ({bot.user.id})')
    # Schedule jobs only once when bot is ready
    for k, v in ingestion.SCHEDULER_INTERVALS.items():
        if k == "BOT_POLL":
            scheduler.add_job(post_news, 'interval', seconds=v['interval'], next_run_time=datetime.now() + timedelta(minutes=2))
        else:
            scheduler.add_job(v['fn'], 'interval', seconds=v['interval'], next_run_time=datetime.now() + timedelta(minutes=1))
        
    scheduler.start()

if __name__ == "__main__":
    TOKEN = os.getenv("BOT_TOKEN")
    if not TOKEN:
        print("Please set the BOT_TOKEN environment variable.")
    else:
        bot.run(TOKEN)
