from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from database import db
from bson.objectid import ObjectId

from .admin import router as admin_router
app = FastAPI()
# Mount admin router
app.include_router(admin_router)
templates = Jinja2Templates(directory="src/templates")

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Render homepage with latest events."""
    cursor = db.events.find().sort("publishedAt", -1).limit(20)
    events = await cursor.to_list(length=20)
    return templates.TemplateResponse("home.html", {"request": request, "events": events})

@app.get("/tags/{tag}", response_class=HTMLResponse)
async def tag_view(request: Request, tag: str):
    """Render page for a specific tag."""
    cursor = db.events.find({"tags": tag}).sort("publishedAt", -1).limit(50)
    events = await cursor.to_list(length=50)
    return templates.TemplateResponse("tag.html", {"request": request, "events": events, "tag": tag})

@app.get("/event/{event_id}", response_class=HTMLResponse)
async def event_view(request: Request, event_id: str):
    """Render individual event page."""
    ev = await db.events.find_one({"_id": ObjectId(event_id)})
    return templates.TemplateResponse("event.html", {"request": request, "event": ev})

@app.get("/recap/{period}/{date}", response_class=HTMLResponse)
async def recap_view(request: Request, period: str, date: str):
    """Render recap page for given period and date."""
    from datetime import datetime
    try:
        dt = datetime.fromisoformat(date)
    except ValueError:
        return HTMLResponse(content="Invalid date format", status_code=400)
    rec = await db.recaps.find_one({"period": period, "createdAt": {"$gte": dt}})
    return templates.TemplateResponse("recap.html", {"request": request, "recap": rec})

@app.get("/post/{post_id}", response_class=HTMLResponse)
async def post_view(request: Request, post_id: str):
    """Stub for long-form posts (not yet implemented)."""
    return HTMLResponse(content="Not implemented", status_code=404)