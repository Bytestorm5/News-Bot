import json
from datetime import datetime, timedelta
from ..database import db
from .llm_service import analyze_item, openai
from .embed_service import embed_text

async def process_event(item: dict) -> dict:
    """
    Process a raw item: analyze via LLM, store in 'events', then embed and store in 'embeddings'.
    """
    analysis = await analyze_item(item.get("title", ""), item.get("content", ""))
    summary = analysis.get("summary", "")
    tags = analysis.get("tags", [])
    sourceBias = analysis.get("sourceBias", {})
    interpretations = analysis.get("interpretations", {})
    event_doc = {
        "sourceId": item.get("sourceId"),
        "guid": item.get("guid"),
        "title": item.get("title", ""),
        "summary": summary,
        "content": item.get("content", ""),
        "tags": tags,
        "sourceBias": sourceBias,
        "interpretations": interpretations,
        "publishedAt": item.get("publishedAt", datetime.utcnow()),
        "createdAt": datetime.utcnow(),
    }
    # Insert event document into database
    result = await db.events.insert_one(event_doc)
    event_id = result.inserted_id
    # Attach the inserted ID for downstream use
    event_doc["_id"] = event_id
    # Compute and store embedding
    vector = await embed_text(summary)
    await db.embeddings.insert_one({"eventId": event_id, "vector": vector})
    return event_doc

async def generate_recaps(period: str = "weekly") -> str:
    """
    Generate and store a recap for the given period ('weekly' or 'monthly').
    """
    now = datetime.utcnow()
    if period == "weekly":
        start = now - timedelta(days=7)
    else:
        # monthly: from first day of last month to end of last month
        last_month_end = now.replace(day=1) - timedelta(days=1)
        start = last_month_end.replace(day=1)
    # Fetch events in window
    cursor = db.events.find({"publishedAt": {"$gte": start, "$lte": now}})
    events = await cursor.to_list(length=1000)
    # Group titles by tag
    tag_map = {}
    for ev in events:
        for tag in ev.get("tags", []):
            tag_map.setdefault(tag, []).append(ev.get("title", ""))
    # Build prompt
    prompt = (
        f"Generate a {period} news recap in Markdown grouped by tag. "
        f"For each tag, list the titles. Data: {json.dumps(tag_map)}"
    )
    # Call LLM
    response = await openai.ChatCompletion.acreate(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You generate news recaps."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3
    )
    recap_text = response.choices[0].message.content
    # Store recap
    await db.recaps.insert_one({
        "period": period,
        "windowStart": start,
        "windowEnd": now,
        "content": recap_text,
        "createdAt": now
    })
    return recap_text