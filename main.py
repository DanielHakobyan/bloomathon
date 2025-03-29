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

# Load environment variables
load_dotenv()

# FastAPI setup
app = FastAPI()
app.include_router(auth.router, prefix="/auth")

# MongoDB setup
MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME")

client = AsyncIOMotorClient(MONGO_URI)
db = client[DB_NAME]
fs_bucket = AsyncIOMotorGridFSBucket(db)

# Jinja2 template setup
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

news_collection = db.news 

# Set up APScheduler for daily news scraping
async def run_fetch_news():
    await fetch_news(db)  

scheduler = BackgroundScheduler()
scheduler.add_job(run_fetch_news, trigger=IntervalTrigger(days=1))  
scheduler.start()

# Home page
@app.get("/", response_class=HTMLResponse)
async def homepage(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# Report Issue (Protected)
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
    # Parse location
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

    # Handle file uploads
    if photo:
        issue_data["photo"] = str(await upload_to_gridfs(photo))
    if video:
        issue_data["video"] = str(await upload_to_gridfs(video))

    result = await db.issues.insert_one(issue_data)
    return {"message": "Issue reported!", "id": str(result.inserted_id)} if result.inserted_id else HTTPException(500, "Failed")

# Helper function to store files in GridFS
async def upload_to_gridfs(file: UploadFile):
    file_id = await fs_bucket.upload_from_stream(file.filename, await file.read())
    return file_id

# Get all reported issues (Public)
@app.get("/issues/", response_class=HTMLResponse)
async def get_issues(request: Request):
    issues = await db.issues.find().to_list(100)
    for issue in issues:
        issue["_id"] = str(issue["_id"])
        issue["photo"] = f"/files/{issue['photo']}" if issue.get('photo') else None
        issue["video"] = f"/files/{issue['video']}" if issue.get('video') else None
    return templates.TemplateResponse("view_issues.html", {"request": request, "issues": issues})

# Admin Panel - View All Issues (Admin Only)
@app.get("/admin/issues", response_class=HTMLResponse)
async def admin_issues_page(request: Request, current_user: dict = Depends(auth.get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Access denied")
    
    issues = await db.issues.find().to_list()
    for issue in issues:
        issue["_id"] = str(issue["_id"])
    return templates.TemplateResponse("admin_issues.html", {"request": request, "issues": issues})

# Update issue status (Admin Only)
@app.post("/admin/issues/{issue_id}/update")
async def update_issue_status(issue_id: str, status: str = Form(...), current_user: dict = Depends(auth.get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Access denied")

    # Validate the issue ID
    if not ObjectId.is_valid(issue_id):
        raise HTTPException(status_code=400, detail="Invalid issue ID format")

    # Validate the status to ensure only "resolved" or "canceled" are used
    if status not in ["resolved", "canceled"]:
        raise HTTPException(status_code=400, detail="Invalid status")

    # Update the issue status in the database
    result = await db.issues.update_one(
        {"_id": ObjectId(issue_id)}, {"$set": {"status": status}}
    )

    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Issue not found or already updated")

    # Redirect back to the issues page after updating the status
    return RedirectResponse(url="/admin/issues", status_code=303)

@app.get("/city-statistics", response_class=HTMLResponse)
async def city_statistics(request: Request):
    # Calculate total issues
    total_issues = await db.issues.count_documents({})

    # Calculate resolved issues count
    resolved_issues_count = await db.issues.count_documents({"status": "resolved"})

    # Fetch the resolved issues details (e.g., title, description)
    resolved_issues = await db.issues.find({"status": "resolved"}).to_list(100)

    # Pass data to the template
    return templates.TemplateResponse(
        "city_statistics.html",
        {
            "request": request,
            "total_issues": total_issues,
            "resolved_issues_count": resolved_issues_count,
            "resolved_issues": resolved_issues
        }
    )

# Retrieve file from GridFS
@app.get("/files/{file_id}")
async def get_file(file_id: str):
    try:
        return StreamingResponse(await fs_bucket.open_download_stream(ObjectId(file_id)), media_type="application/octet-stream")
    except:
        raise HTTPException(404, "File not found")

# Static pages
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

# Fetch news image
@app.get("/news/image/{image_id}")
async def get_news_image(image_id: str):
    try:
        return StreamingResponse(await fs_bucket.open_download_stream(ObjectId(image_id)), media_type="image/jpeg")
    except:
        raise HTTPException(404, "Image not found")

# On startup: Fetch news if DB is empty
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
