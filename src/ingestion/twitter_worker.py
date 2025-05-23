import tweepy
from datetime import datetime
from ..config import settings
from ..database import db
from ..processor.pipeline import process_event
from ..discord_bot import publish_event

async def ingest_twitter():
    """Ingest tweets from configured Twitter users and process new events."""
    client = tweepy.Client(bearer_token=settings.TWITTER_BEARER_TOKEN)
    for user in settings.TWITTER_USERS:
        user_id = user.get("id")
        if not user_id:
            continue
        try:
            resp = client.get_users_tweets(
                id=user_id,
                tweet_fields=["created_at", "text"],
                max_results=10
            )
        except Exception:
            continue
        tweets = resp.data or []
        for tweet in tweets:
            guid = str(tweet.id)
            source_key = f"twitter:{user_id}"
            # Dedupe
            exists = await db.events.find_one({"sourceId": source_key, "guid": guid})
            if exists:
                continue
            item = {
                "sourceId": source_key,
                "guid": guid,
                "title": "",
                "content": tweet.text,
                "publishedAt": tweet.created_at or datetime.utcnow(),
            }
            # Process via LLM pipeline
            event_doc = await process_event(item)
            # Publish to Discord
            await publish_event(event_doc)