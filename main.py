import os
import asyncio
from fastapi import FastAPI, Request, HTTPException, File, UploadFile, Form, Depends
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorGridFSBucket
from bson import ObjectId
from dotenv import load_dotenv
import auth
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from news_scraper import fetch_news
from fastapi.responses import RedirectResponse
from datetime import datetime


load_dotenv()

app = FastAPI()
app.include_router(auth.router, prefix="/auth")

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME")

client = AsyncIOMotorClient(MONGO_URI)
db = client[DB_NAME]
fs_bucket = AsyncIOMotorGridFSBucket(db)

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

news_collection = db.news 

async def run_fetch_news():
    await fetch_news(db)  

scheduler = BackgroundScheduler()
scheduler.add_job(run_fetch_news, trigger=IntervalTrigger(days=1))  
scheduler.start()

@app.get("/", response_class=HTMLResponse)
async def homepage(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/about", response_class=HTMLResponse)
async def about_page(request: Request):
    return templates.TemplateResponse("about.html", {"request": request})

@app.get("/contact", response_class=HTMLResponse)
async def contact_page(request: Request):
    return templates.TemplateResponse("contact.html", {"request": request})

@app.get("/report-issue", response_class=HTMLResponse)
async def report_issue_page(request: Request, current_user: dict = Depends(auth.get_current_user)):
    if not current_user.get("is_verified", False):
        raise HTTPException(status_code=403, detail="Verify email first.")
    return templates.TemplateResponse("report_issue.html", {"request": request})

@app.post("/report/")
async def report_issue(
    request: Request,
    title: str = Form(...),
    description: str = Form(...),
    location: str = Form(...),
    location_description: str = Form(...),
    photo: UploadFile = File(None),
    video: UploadFile = File(None),
    current_user: dict = Depends(auth.get_current_user)
):
    location_parts = location.split(",")
    lat, lng = (float(location_parts[0].replace("Lat:", "").strip()), 
                float(location_parts[1].replace("Lng:", "").strip())) if len(location_parts) == 2 else (None, None)

    issue_data = {
        "title": title,
        "description": description,
        "location": location,
        "location_description": location_description,
        "latitude": lat,
        "longitude": lng,
        "reported_by": current_user["email"],
        "photo": None,
        "video": None,
        "status": "pending",
    }

    if photo and photo.filename:
        issue_data["photo"] = str(await upload_to_gridfs(photo))
    if video and video.filename:
        issue_data["video"] = str(await upload_to_gridfs(video))

    result = await db.issues.insert_one(issue_data)
    return {"message": "Issue reported!", "id": str(result.inserted_id)} if result.inserted_id else HTTPException(500, "Failed")

async def upload_to_gridfs(file: UploadFile):
    file_id = await fs_bucket.upload_from_stream(file.filename, await file.read())
    return file_id

@app.get("/issues/", response_class=HTMLResponse)
async def get_issues(request: Request):
    issues = await db.issues.find().to_list(100)
    for issue in issues:
        issue["_id"] = str(issue["_id"])
        issue["photo"] = f"/files/{issue['photo']}" if issue.get('photo') else None
        issue["video"] = f"/files/{issue['video']}" if issue.get('video') else None
    return templates.TemplateResponse("view_issues.html", {"request": request, "issues": issues})

@app.get("/admin/issues", response_class=HTMLResponse)
async def admin_issues_page(request: Request, current_user: dict = Depends(auth.get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Access denied")
    
    issues = await db.issues.find().to_list()
    for issue in issues:
        issue["_id"] = str(issue["_id"])
    return templates.TemplateResponse("admin_issues.html", {"request": request, "issues": issues})

@app.post("/admin/issues/{issue_id}/update")
async def update_issue_status(issue_id: str, status: str = Form(...), current_user: dict = Depends(auth.get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Access denied")

    if not ObjectId.is_valid(issue_id):
        raise HTTPException(status_code=400, detail="Invalid issue ID format")

    if status not in ["resolved", "canceled"]:
        raise HTTPException(status_code=400, detail="Invalid status")

    result = await db.issues.update_one(
        {"_id": ObjectId(issue_id)}, {"$set": {"status": status}}
    )

    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Issue not found or already updated")

    return RedirectResponse(url="/admin/issues", status_code=303)


@app.get("/admin/events", response_class=HTMLResponse)
async def admin_events_page(request: Request, current_user: dict = Depends(auth.get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Access denied")
    
    events = await db.events.find().to_list()
    for event in events:
        event["_id"] = str(event["_id"])
    return templates.TemplateResponse("admin_events.html", {"request": request, "events": events})

@app.post("/admin/events/{event_id}/update")
async def update_events_status(event_id: str, status: str = Form(...), current_user: dict = Depends(auth.get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Access denied")

    if not ObjectId.is_valid(event_id):
        raise HTTPException(status_code=400, detail="Invalid event ID format")

    if status not in ["resolved", "canceled"]:
        raise HTTPException(status_code=400, detail="Invalid status")

    result = await db.events.update_one(
        {"_id": ObjectId(event_id)}, {"$set": {"status": status}}
    )

    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Event not found or already updated")

    return RedirectResponse(url="/admin/events", status_code=303)

@app.get("/city-statistics", response_class=HTMLResponse)
async def city_statistics(request: Request):
    total_issues = await db.issues.count_documents({})
    resolved_issues_count = await db.issues.count_documents({"status": "resolved"})
    resolved_issues = await db.issues.find({"status": "resolved"}).to_list()

    for issue in resolved_issues:
        issue["_id"] = str(issue["_id"])
        issue["photo"] = f"/files/{issue['photo']}" if issue.get("photo") else None
        issue["video"] = f"/files/{issue['video']}" if issue.get("video") else None

        # Convert created_at to a human-readable format
        if "created_at" in issue and isinstance(issue["created_at"], datetime):
            issue["created_at"] = issue["created_at"].strftime("%Y-%m-%d %H:%M:%S")

    return templates.TemplateResponse(
        "city_statistics.html",
        {
            "request": request,
            "total_issues": total_issues,
            "resolved_issues_count": resolved_issues_count,
            "resolved_issues": resolved_issues,
        }
    )


@app.get("/files/{file_id}")
async def get_file(file_id: str):
    try:
        return StreamingResponse(await fs_bucket.open_download_stream(ObjectId(file_id)), media_type="application/octet-stream")
    except:
        raise HTTPException(404, "File not found")

@app.get("/transport", response_class=HTMLResponse)
async def transport_page(request: Request):
    return templates.TemplateResponse("transport.html", {"request": request})

@app.get("/news", response_class=HTMLResponse)
async def get_news(request: Request):
    try:
        news_list = await news_collection.find({}, {"_id": 0}).to_list(100)
        return templates.TemplateResponse("news.html", {"request": request, "news": news_list})
    except Exception as e:
        raise HTTPException(500, "Failed to fetch news")

@app.get("/city", response_class=HTMLResponse)
async def city_page(request: Request):
    return templates.TemplateResponse("city.html", {"request": request})

@app.get("/for_tourists", response_class=HTMLResponse)
async def for_tourists_page(request: Request):
    return templates.TemplateResponse("for_tourists.html", {"request": request})

# Fetch news articles
@app.get("/news/articles")
async def get_news_articles():
    articles = await db.news.find().to_list(20)
    for article in articles:
        article["_id"] = str(article["_id"])
        article["image_url"] = f"/news/image/{article['image_id']}" if "image_id" in article else None
    return articles

@app.get("/news/image/{image_id}")
async def get_news_image(image_id: str):
    try:
        return StreamingResponse(await fs_bucket.open_download_stream(ObjectId(image_id)), media_type="image/jpeg")
    except:
        raise HTTPException(404, "Image not found")
    

@app.get("/view_events/", response_class=HTMLResponse)
async def get_events(request: Request):
    events = await db.events.find().to_list(100)
    for event in events:
        event["_id"] = str(event["_id"])
        event["photo"] = f"/files/{event['photo']}" if event.get('photo') else None
        event["video"] = f"/files/{event['video']}" if event.get('video') else None
    return templates.TemplateResponse("view_events.html", {"request": request, "events": events})

@app.get("/create_event", response_class=HTMLResponse)
async def create_event_page(request: Request, current_user: dict = Depends(auth.get_current_user)):
    if not current_user.get("is_verified", False):
        raise HTTPException(status_code=403, detail="Verify email first.")
    return templates.TemplateResponse("create_event.html", {"request": request})
@app.post("/event")
async def report_issue(
    request: Request,
    title: str = Form(...),
    description: str = Form(...),
    datetime: str = Form(...),
    duration: str = Form(...),
    location: str = Form(...),
    location_description: str = Form(...),
    photo: UploadFile = File(None),
    video: UploadFile = File(None),
    current_user: dict = Depends(auth.get_current_user)
):
    location_parts = location.split(",")
    lat, lng = (float(location_parts[0].replace("Lat:", "").strip()), 
                float(location_parts[1].replace("Lng:", "").strip())) if len(location_parts) == 2 else (None, None)

    event_data = {
        "title": title,
        "description": description,
        "datetime": datetime,
        "duration": duration,
        "location": location,
        "location_description": location_description,
        "latitude": lat,
        "longitude": lng,
        "reported_by": current_user["email"],
        "photo": None,
        "video": None,
        "status": "pending",
    }

    if photo and photo.filename:
        event_data["photo"] = str(await upload_to_gridfs(photo))
    if video and video.filename:
        event_data["video"] = str(await upload_to_gridfs(video))

    result = await db.events.insert_one(event_data)
    return {"message": "Event submitted successfully!", "id": str(result.inserted_id)} if result.inserted_id else HTTPException(500, "Failed")


@app.on_event("startup")
async def startup():
    if await db.news.count_documents({}) == 0:
        await fetch_news(db)
    asyncio.create_task(run_fetch_news())

@app.on_event("shutdown")
def shutdown_scheduler():
    scheduler.shutdown()

async def shutdown():
    client.close()
