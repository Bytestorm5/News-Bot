import os
import logging
import sys
from discord import Intents, Embed
from discord.ext import commands

from config import settings
from community.summariser import handle_summarise
from community.moderation import moderate_message
import openai
from database import db

# Initialize bot with all intents
intents = Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents)
# Initialize OpenAI API key for Q&A
openai.api_key = settings.OPENAI_KEY

@bot.event
async def on_ready():
    logging.info(f"Discord bot logged in as {bot.user}")

@bot.command(name="summarise", help="Summarise the last X hours of chat")
async def summarise(ctx, hours: int):
    await ctx.trigger_typing()
    await handle_summarise(ctx, hours)

@bot.event
async def on_message(message):
    # Skip bot messages
    if message.author.bot:
        return
    # Run moderation guard
    await moderate_message(message)
    # Q&A thread handling: respond when bot is mentioned in an event thread
    try:
        # Look up event associated with this thread
        ev = await db.events.find_one({"threadIds": str(message.channel.id)})
    except Exception:
        ev = None
    if ev and message.guild and bot.user.mentioned_in(message):
        # Remove bot mention from content
        content = message.content.replace(f"<@!{bot.user.id}>", "").replace(f"<@{bot.user.id}>", "").strip()
        # Prepare Q&A prompt using the event summary
        summary = ev.get("summary", "")
        prompt = (
            "You are a news Q&A assistant. "
            "Use the following event summary to answer questions. "
            f"Summary: {summary}\nQuestion: {content}\n"
            "If the answer cannot be found in the summary, reply with 'I don't know.'"
        )
        # Call OpenAI to generate answer
        try:
            response = await openai.ChatCompletion.acreate(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You answer questions based on a news summary."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3
            )
            answer = response.choices[0].message.content
        except Exception:
            answer = "Sorry, I couldn't generate an answer."
        await message.channel.send(answer)
        return
    # Process other commands
    await bot.process_commands(message)

async def publish_event(event_doc: dict):
    """
    Post a new Event to Discord channels based on its tags.
    """
    tags = event_doc.get("tags", [])
    title = event_doc.get("title", "")
    summary = event_doc.get("summary", "")
    published = event_doc.get("publishedAt")
    source_bias = event_doc.get("sourceBias", {})
    blurb = source_bias.get("blurb", "")
    # Post embed and create Q&A thread for each relevant channel
    for tag in tags:
        channel_id = settings.TAG_CHANNEL_MAP.get(tag)
        if not channel_id:
            continue
        channel = bot.get_channel(int(channel_id))
        if channel is None:
            continue
        embed = Embed(
            title=title,
            description=summary,
            timestamp=published
        )
        embed.add_field(name="Tags", value=", ".join(tags), inline=True)
        # Do not expose source bias in Discord embeds
        # Send the embed
        msg = await channel.send(embed=embed)
        # Create a thread for Q&A
        try:
            thread = await msg.create_thread(name=f"Q&A: {title}")
            # Store thread ID in event document for Q&A routing
            await db.events.update_one(
                {"_id": event_doc.get("_id")},
                {"$addToSet": {"threadIds": str(thread.id)}}
            )
        except Exception:
            # Thread creation failed; continue
            pass

def run_discord_bot():
    logging.basicConfig(level=logging.INFO)
    token = settings.BOT_TOKEN
    bot.run(token)