from fastapi import APIRouter, HTTPException
from bson.objectid import ObjectId
from datetime import datetime
import openai

from .database import db
from .config import settings
# Initialize OpenAI API key for admin long-form generation
openai.api_key = settings.OPENAI_KEY

router = APIRouter(prefix="/admin", tags=["admin"])

@router.get("/events")
async def list_events():
    """List all events for admin review."""
    events = await db.events.find().sort("createdAt", -1).to_list(length=100)
    return events

@router.post("/events/{event_id}/longform")
async def generate_longform(event_id: str):
    """Generate a long-form article for an event."""
    ev = await db.events.find_one({"_id": ObjectId(event_id)})
    if not ev:
        raise HTTPException(status_code=404, detail="Event not found")
    prompt = (
        f"Expand the following news summary into a long-form article in Markdown:\n\n{ev.get('summary', '')}\n"
        "Include rich details and structure."
    )
    response = await openai.ChatCompletion.acreate(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You write long-form news articles."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7
    )
    content = response.choices[0].message.content
    await db.events.update_one({"_id": ObjectId(event_id)}, {"$set": {"longForm": content}})
    return {"longForm": content}

@router.get("/recaps")
async def list_recaps():
    """List all recaps for admin review."""
    recaps = await db.recaps.find().sort("createdAt", -1).to_list(length=50)
    return recaps

@router.put("/recaps/{recap_id}")
async def update_recap(recap_id: str, data: dict):
    """Update a recap document."""
    res = await db.recaps.update_one({"_id": ObjectId(recap_id)}, {"$set": data})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Recap not found")
    return {"status": "ok"}