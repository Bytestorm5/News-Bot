import requests
import os
from pymongo import MongoClient
import urllib.parse
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass

import db

import llm_utils

@dataclass
class NewsItem:
    _id: str
    title: str
    description: str | None
    url: str
    publish_timestamp: datetime
    ingest_timestamp: datetime
    icon_url: str | None
    categories: list[str]
    source: str
    
    def to_dict(self):
        return {
            "_id": self._id,
            "title": self.title,
            "description": self.description,
            "url": self.url,
            "publish_timestamp": self.publish_timestamp,
            "ingest_timestamp": self.ingest_timestamp,
            "icon_url": self.icon_url,
            "categories": self.categories,
            "source": self.source
        }

@dataclass
class MongoNewsItem:
    _id: str
    news_item: NewsItem
    summary: str
    tid: str
    
    def to_dict(self):
        return {
            "_id": self._id,
            "news_item": self.news_item.to_dict(),
            "summary": self.summary,
            "tid": self.tid
        }

def process_news_item(item: NewsItem):
    prompt = (
        "Summarize the event described in the linked article. Search for other articles talking about this event to add more context.:\n\n"
        f"Title: {item.title}\n"
        f"Description: {item.description}\n"
        f"URL: {item.url}\n"
        f"Published at: {item.publish_timestamp.isoformat()}\n"
    )
    response, tid = llm_utils.chat(prompt)
    
    processed_item = MongoNewsItem(
        _id=item._id,
        news_item=item,
        summary=response,
        tid=tid
    )
    db.db["news_items"].replace_one({"_id": processed_item._id}, processed_item.to_dict(), upsert=True)

DAILY_LIMITS = {
    'thenewsapi': 100,
}

async def ingest_thenewsapi() -> None:
    """Fetch recent stories from TheNewsAPI, falling back from /top to /all
    when /top has fewer items than the per-page limit, while never exceeding
    interval_cap requests per invocation.
    """
    timestamp = datetime.now(timezone.utc)
    history   = timestamp - timedelta(seconds=86400 / DAILY_LIMITS["thenewsapi"])

    def build_url(endpoint: str, page: int = 1) -> str:
        """Compose the request URL for /top or /all."""
        params = {
            "api_token": os.environ.get("THENEWSAPI_KEY"),
            "exclude_categories": "sports,entertainment,food,travel",
            "published_after": history.strftime("%Y-%m-%dT%H:%M:%S"),
            "page": page,
        }
        return f"https://api.thenewsapi.com/v1/news/{endpoint}?{urllib.parse.urlencode(params)}"

    def ingest_data(data: dict) -> None:
        """Convert raw JSON into NewsItem objects and hand off for processing."""
        print(f"Processing {len(data['data'])} items")
        for item in data["data"]:
            news_item = NewsItem(
                _id=item["uuid"],
                title=item["title"],
                description=item.get("description"),
                url=item["url"],
                publish_timestamp=datetime.fromisoformat(item["published_at"]),
                ingest_timestamp=timestamp,
                icon_url=item.get("image_url"),
                categories=item.get("categories", []),
                source=item["source"],
            )
            process_news_item(news_item)

    # ------------------------------------------------------------------ #
    endpoint       = "top"   # start here, may switch to "all"
    page           = 1
    requests_made  = 0
    interval_cap   = 4

    while requests_made < interval_cap:
        url      = build_url(endpoint, page)
        response = requests.get(url)
        requests_made += 1

        if response.status_code != 200:
            print(f"Failed to fetch news: {response.status_code}")
            break

        data = response.json()
        ingest_data(data)

        returned = data["meta"]["returned"]
        limit    = data["meta"]["limit"]

        # Switch from /top to /all if /top gave us fewer than limit results
        if endpoint == "top" and returned < limit:
            endpoint = "all"
            page     = 1        # restart paging on /all
            continue             # do *not* count this as an extra request

        # Stop paging if either we reached the last page or the cap
        if returned < limit:
            break

        page += 1               # go to the next page and loop

SCHEDULER_INTERVALS = {
    'BOT_POLL': {
        'interval':86400 / DAILY_LIMITS['thenewsapi'],
        'fn': None  # Placeholder for the bot's poll function
    },  # Should be the minimum interval of all sources
    'thenewsapi': {
        'interval': 86400 / DAILY_LIMITS['thenewsapi'],  # ~25x/day
        'fn': ingest_thenewsapi
    }
}