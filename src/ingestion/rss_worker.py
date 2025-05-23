import feedparser
from datetime import datetime
from ..config import settings
from ..database import db
from ..processor.pipeline import process_event
from ..discord_bot import publish_event

async def ingest_rss():
    """Ingest items from configured RSS sources and process new events."""
    for source in settings.RSS_SOURCES:
        url = source.get("url")
        source_id = source.get("id")
        if not url or not source_id:
            continue
        feed = feedparser.parse(url)
        for entry in feed.entries:
            guid = getattr(entry, 'id', entry.get('link'))
            if not guid:
                continue
            # Dedupe
            exists = await db.events.find_one({"sourceId": source_id, "guid": guid})
            if exists:
                continue
            # Build item
            published = None
            if entry.get('published_parsed'):
                published = datetime(*entry.published_parsed[:6])
            item = {
                "sourceId": source_id,
                "guid": guid,
                "title": entry.get('title', ''),
                "content": entry.get('content', entry.get('summary', '')),
                "publishedAt": published or datetime.utcnow(),
            }
            # Process via LLM pipeline
            event_doc = await process_event(item)
            # Publish to Discord
            await publish_event(event_doc)