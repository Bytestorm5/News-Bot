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
    response, tid = llm_utils.chat(prompt, save=True, use_tools=True)
    
    processed_item = MongoNewsItem(
        _id=item._id,
        news_item=item,
        summary=response.content,
        tid=tid
    )
    db.db["news_items"].replace_one({"_id": processed_item._id}, processed_item.to_dict(), upsert=True)

DAILY_LIMITS = {
    'thenewsapi': 100,
}

async def ingest_thenewsapi():
    timestamp = datetime.now(timezone.utc)
    history = timestamp - timedelta(seconds=86400/DAILY_LIMITS['thenewsapi'])
    url = "https://api.thenewsapi.com/v1/news/top?"
    url += urllib.parse.urlencode({
        'api_token': os.environ.get("THENEWSAPI_KEY"),
        'categories':'science,business,health,tech,politics',
        'published_after': history.strftime("%Y-%m-%dT%H:%M:%S"),
    })
    
    initial_response = requests.get(url)
    if initial_response.status_code != 200:
        print(f"Failed to fetch news: {initial_response.status_code}")
        return

    # Assume future pages will succeed
    initial_data = initial_response.json()
    total_potential = initial_data['meta']['found']
    per_page = initial_data['meta']['limit']
    # Maximum requests we can make in one cycle
    interval_cap = 4
    
    def ingest_data(data):
        print(f"Processing {len(data['data'])} items")
        for item in data['data']:
            news_item = NewsItem(
                _id=item['uuid'],
                title=item['title'],
                description=item.get('description'),
                url=item['url'],
                publish_timestamp=datetime.fromisoformat(item['published_at']),
                ingest_timestamp=timestamp,
                icon_url=item.get('image_url'),
                categories=item.get('categories', []),
                source=item['source']
            )
            process_news_item(news_item)
        
    recent_data = initial_data
    ingest_data(recent_data)
    
    i = 1
    while i < interval_cap and recent_data['meta']['returned'] == recent_data['meta']['limit']:
        i += 1
        url = "https://api.thenewsapi.com/v1/news/top?"
        url += urllib.parse.urlencode({
            'api_token': os.environ.get("THENEWSAPI_KEY"),
            'categories':'general,science,business,health,tech,politics',
            'published_after': history.strftime("%Y-%m-%dT%H:%M:%S"),
            'page': i,
        })
        
        response = requests.get(url)
        if response.status_code != 200:
            print(f"Failed to fetch news: {response.status_code}")
            break
        
        recent_data = response.json()
        ingest_data(recent_data)

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