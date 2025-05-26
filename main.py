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
import llm_utils
import util

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

since = datetime.now(timezone.utc) - timedelta(minutes=1)

async def post_news():
    global since
    channel_id = int(os.environ.get("NEWS_CHANNEL_ID"))  # Set this in your .env
    channel = bot.get_channel(channel_id)
    if channel:
        # Find scheduled tasks
        scheds: list[llm_utils.Followup] = [llm_utils.Followup(prompt=item["prompt"], timestamp=item["timestamp"]) for item in db.db['follow_ups'].find({ "timestamp": { "$gt": since } })]
        for sched in scheds:
            msg, tid = llm_utils.chat(
                user_input=f"This is a follow-up to a message scheduled for {sched.timestamp.strftime('%Y-%m-%d %H:%M:%S')} UTC. Please respond accordingly. What follows is the task description set at that time:\n {sched.prompt}",
                save=True,
                use_tools=True,
            )
            util.batch_send(channel, msg)
            db.db['follow_ups'].delete_one({"prompt": sched.prompt, "timestamp": sched.timestamp})
        # Find news from the last cycle        
        cursor = collection.find(
            { "news_item.publish_timestamp": { "$gt": since } }
        ).sort("news_item.publish_timestamp", 1)

        new_items = [
            ingestion.MongoNewsItem(
                _id=doc['_id'],
                news_item=ingestion.NewsItem(**doc['news_item']),
                summary=doc['summary'],
                tid=doc['tid']
            )
            for doc in cursor
        ]
        since = datetime.now(timezone.utc)  # Update the since variable for the next cycle
        for item in new_items:
            message = f"# [{item.news_item.title}](<{item.news_item.url}>)\n{item.news_item.description}\n\n{item.summary}```Categories: {','.join(item.news_item.categories)}\nPublished at: {item.news_item.publish_timestamp.strftime('%Y-%m-%d %H:%M:%S')}\nSource: {item.news_item.source}\nEvent ID: {item._id}```"
            await util.batch_send(channel, message)
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
            scheduler.add_job(v['fn'], 'interval', seconds=v['interval'], next_run_time=datetime.now())
            pass
    scheduler.start()

if __name__ == "__main__":
    TOKEN = os.getenv("BOT_TOKEN")
    if not TOKEN:
        print("Please set the BOT_TOKEN environment variable.")
    else:
        bot.run(TOKEN)
