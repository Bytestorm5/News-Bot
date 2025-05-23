from motor.motor_asyncio import AsyncIOMotorClient
from .config import settings

# Initialize MongoDB client and default database
client = AsyncIOMotorClient(settings.MONGO_URI)
db = client.get_default_database()
async def init_db():
    """Initialize database indexes and TTL settings."""
    # Events collection indexes
    await db.events.create_index([("sourceId", 1), ("guid", 1)], unique=True)
    await db.events.create_index([("tags", 1), ("publishedAt", -1)])
    await db.events.create_index([("title", "text"), ("summary", "text")])
    # Embeddings index
    await db.embeddings.create_index("eventId")
    # Summaries TTL index
    await db.summaries.create_index("createdAt", expireAfterSeconds=72 * 3600)
    # Moderation logs TTL index
    await db.moderation_logs.create_index("flaggedAt", expireAfterSeconds=30 * 24 * 3600)
    # Recaps index
    await db.recaps.create_index([("period", 1), ("createdAt", -1)])