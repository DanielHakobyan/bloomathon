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
import threading

# Load environment variables from .env file
load_dotenv()

# FastAPI setup
app = FastAPI()

# Include authentication routes
app.include_router(auth.router, prefix="/auth")

# MongoDB setup
MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME")

client = AsyncIOMotorClient(MONGO_URI)
db = client[DB_NAME]

# Initialize GridFS for file storage
fs_bucket = AsyncIOMotorGridFSBucket(db)

# Jinja2 template setup
templates = Jinja2Templates(directory="templates")

# Mount static directory for CSS/JS
app.mount("/static", StaticFiles(directory="static"), name="static")

news_collection = db.news 

# Set up APScheduler for daily news scraping
async def run_fetch_news():
    await fetch_news(db)  # Directly call fetch_news using await

scheduler = BackgroundScheduler()
scheduler.add_job(run_fetch_news, trigger=IntervalTrigger(days=1))  # Runs once per day
scheduler.start() # Pass the db to fetch_news function

# Home page
@app.get("/", response_class=HTMLResponse)
async def homepage(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# Report Issue (Save to MongoDB) - Protected by Authentication
@app.get("/report-issue", response_class=HTMLResponse)
async def report_issue_page(request: Request, current_user: dict = Depends(auth.get_current_user)):
    if not current_user.get("is_verified", False):
        raise HTTPException(status_code=403, detail="You need to verify your email before reporting an issue.")
    return templates.TemplateResponse("report_issue.html", {"request": request})

@app.post("/report/")
async def report_issue_page(
    request: Request,
    title: str = Form(...),
    description: str = Form(...),
    location: str = Form(...),
    location_description: str = Form(...),
    photo: UploadFile = File(None),
    video: UploadFile = File(None),
    current_user: dict = Depends(auth.get_current_user)
):
    print(f"Received data: title={title}, description={description}, location={location}")

    # Parse location (Lat: xxx, Lng: yyy)
    location_parts = location.split(",")
    if len(location_parts) == 2:
        lat = float(location_parts[0].replace("Lat:", "").strip())
        lng = float(location_parts[1].replace("Lng:", "").strip())
    else:
        lat = None
        lng = None

    # Issue handling
    issue_data = {
        "title": title,
        "description": description,
        "location": location,  # You can save this as a string or also store lat/lng separately
        "location_description": location_description,  # Save the location description as well
        "latitude": lat,
        "longitude": lng,
        "reported_by": current_user["email"],  # User email from the token
    }

    # Handle file uploads
    if photo:
        photo_id = await upload_to_gridfs(photo)
        issue_data["photo"] = str(photo_id)
    
    if video:
        video_id = await upload_to_gridfs(video)
        issue_data["video"] = str(video_id)

    # Insert into DB
    result = await db.issues.insert_one(issue_data)
    
    if result.inserted_id:
        return {"message": "Issue reported successfully!", "id": str(result.inserted_id)}
    
    raise HTTPException(status_code=500, detail="Failed to report issue.")

# Helper function to store files in GridFS
async def upload_to_gridfs(file: UploadFile):
    file_data = await file.read()  # Read file data
    file_id = await fs_bucket.upload_from_stream(file.filename, file_data)
    return file_id

# Get all reported issues (with file links)
@app.get("/issues/", response_class=HTMLResponse)
async def get_issues(request: Request):
    issues = await db.issues.find().to_list(100)  # Limit to 100 issues
    for issue in issues:
        issue["_id"] = str(issue["_id"])  # Convert ObjectId to string
        # Add file URL links
        if issue.get('photo'):
            issue['photo'] = f"/files/{issue['photo']}"
        if issue.get('video'):
            issue['video'] = f"/files/{issue['video']}"
    return templates.TemplateResponse("view_issues.html", {"request": request, "issues": issues})

# Retrieve file from GridFS
@app.get("/files/{file_id}")
async def get_file(file_id: str):
    try:
        file_id = ObjectId(file_id)
        file = await fs_bucket.open_download_stream(file_id)
        return StreamingResponse(file, media_type="application/octet-stream")
    except Exception:
        raise HTTPException(status_code=404, detail="File not found")

# Static file routes
@app.get("/transport")
async def transport_page(request: Request):
    return templates.TemplateResponse("transport.html", {"request": request})

@app.get("/news")
async def get_news(request: Request):
    try:
        # Fetch news articles from the database
        news_list = await news_collection.find({}, {"_id": 0}).to_list(length=100)
        print(f"Fetched {len(news_list)} news articles")
        return templates.TemplateResponse("news.html", {"request": request, "news": news_list})
    except Exception as e:
        print(f"Error fetching news: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch news")


# Run `fetch_news` automatically every 24 hours
# def schedule_news_fetch():
#     loop = asyncio.new_event_loop()
#     asyncio.set_event_loop(loop)
#     loop.run_until_complete(fetch_news(db))  # Pass the db to fetch_news function

# schedule_news_fetch()


@app.get("/city")
async def city_page(request: Request):
    return templates.TemplateResponse("city.html", {"request": request})

@app.get("/for_tourists")
async def for_tourists_page(request: Request):
    return templates.TemplateResponse("for_tourists.html", {"request": request})

@app.get("/news/articles")
async def get_news_articles():
    articles = await db.news.find().to_list(20)  # Fetch 20 latest articles
    for article in articles:
        article["_id"] = str(article["_id"])
        if "image_id" in article and article["image_id"]:
            article["image_url"] = f"/news/image/{article['image_id']}"
    return articles

@app.get("/news/image/{image_id}")
async def get_news_image(image_id: str):
    try:
        file_id = ObjectId(image_id)
        file = await fs_bucket.open_download_stream(file_id)
        return StreamingResponse(file, media_type="image/jpeg")
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found")

# Handle lifecycle events
@app.on_event("startup")
async def startup():
    print("Application startup: Connecting to MongoDB")
    
    # Check if the news collection is empty
    news_count = await db.news.count_documents({})
    print(f"News count in DB: {news_count}")

    if news_count == 0:
        print("No news found in DB, fetching immediately...")
        await fetch_news(db)  # Fetch news immediately if DB is empty

    # Schedule daily news fetching
    asyncio.create_task(run_fetch_news())

@app.on_event("shutdown")
def shutdown_scheduler():
    scheduler.shutdown()

async def shutdown():
    print("Application shutdown: Closing MongoDB connection")
    client.close()
