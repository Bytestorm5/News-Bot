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

since = datetime.now(timezone.utc) - timedelta(days=1)

async def post_news():
    global since
    channel_id = int(os.environ.get("NEWS_CHANNEL_ID"))  # Set this in your .env
    channel = bot.get_channel(channel_id)
    if channel:
        # Find news from the last cycle (e.g., last 2 minutes)
        
        new_items: list[ingestion.MongoNewsItem] = [ingestion.MongoNewsItem(_id=item['_id'], news_item=ingestion.NewsItem(**item['news_item']), summary=item['summary'], tid=item['tid']) for item in list(collection.find({}))]
        since = datetime.now(timezone.utc)  # Update the since variable for the next cycle
        for item in new_items:
            message = f"# [{item.news_item.title}](<{item.news_item.url}>)\n{item.news_item.description}\n\n{item.summary}```Categories: {','.join(item.news_item.categories)}\nPublished at: {item.news_item.publish_timestamp.strftime('%Y-%m-%d %H:%M:%S')}\nSource: {item.news_item.source}\nEvent ID: {item._id}```"
            if len(message) < 2000:
                await channel.send(message)
            else:
                chunk = ""
                for line in message.split('\n'):
                    if len(chunk) + len(line + '\n') < 2000:
                        chunk += line + '\n'
                    else:
                        await channel.send(chunk)
                        chunk = line + '\n'
                    await channel.send(chunk)  # Send the last chunk if any
        print("Posted news to channel.")

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name} ({bot.user.id})')
    await post_news()
    # Schedule jobs only once when bot is ready
    for k, v in ingestion.SCHEDULER_INTERVALS.items():
        if k == "BOT_POLL":
            scheduler.add_job(post_news, 'interval', seconds=v['interval'], next_run_time=datetime.now())
        else:
            #scheduler.add_job(v['fn'], 'interval', seconds=v['interval'], next_run_time=datetime.now())
            pass
    scheduler.start()

if __name__ == "__main__":
    TOKEN = os.getenv("BOT_TOKEN")
    if not TOKEN:
        print("Please set the BOT_TOKEN environment variable.")
    else:
        bot.run(TOKEN)
