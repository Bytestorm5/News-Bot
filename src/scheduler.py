from apscheduler.schedulers.asyncio import AsyncIOScheduler

from ingestion.rss_worker import ingest_rss
from ingestion.twitter_worker import ingest_twitter
from processor.pipeline import generate_recaps

def start_scheduler():
    """
    Start the ingestion and recap scheduler.
    """
    scheduler = AsyncIOScheduler()
    # Poll RSS every 15 minutes
    scheduler.add_job(ingest_rss, 'interval', minutes=15)
    # Poll Twitter every 5 minutes
    scheduler.add_job(ingest_twitter, 'interval', minutes=5)
    # Weekly recap: Sunday 23:55 UTC
    scheduler.add_job(generate_recaps, 'cron', kwargs={"period": "weekly"}, day_of_week='sun', hour=23, minute=55)
    # Monthly recap: last day of month 23:55 UTC
    scheduler.add_job(generate_recaps, 'cron', kwargs={"period": "monthly"}, day='last', hour=23, minute=55)
    scheduler.start()