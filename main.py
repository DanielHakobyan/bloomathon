import os
from fastapi import FastAPI, Request, HTTPException, File, UploadFile, Form
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from motor.motor_asyncio import AsyncIOMotorClient
from motor.motor_asyncio import AsyncIOMotorGridFSBucket
from bson import ObjectId
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# FastAPI setup
app = FastAPI()

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

# Home page
@app.get("/", response_class=HTMLResponse)
async def homepage(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# Report Issue (Save to MongoDB)
@app.get("/report-issue", response_class=HTMLResponse)
async def report_issue_page(request: Request):
    return templates.TemplateResponse("report_issue.html", {"request": request})

@app.post("/report/", response_model=dict)
async def report_issue(
    title: str = Form(...), 
    description: str = Form(...), 
    location: str = Form(...), 
    photo: UploadFile = File(None), 
    video: UploadFile = File(None)
):
    issue_data = {
        "title": title,
        "description": description,
        "location": location,
    }

    # Handle file uploads (photo/video)
    if photo:
        photo_id = await upload_to_gridfs(photo)
        issue_data['photo'] = str(photo_id)
    
    if video:
        video_id = await upload_to_gridfs(video)
        issue_data['video'] = str(video_id)

    # Insert issue into MongoDB
    result = await db.issues.insert_one(issue_data)
    
    if result.inserted_id:
        return {"message": "Issue reported successfully!", "id": str(result.inserted_id)}
    raise HTTPException(status_code=500, detail="Failed to report issue.")

async def upload_to_gridfs(file: UploadFile):
    """ Helper function to store file in GridFS """
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
async def news_page(request: Request):
    return templates.TemplateResponse("news.html", {"request": request})

@app.get("/city")
async def city_page(request: Request):
    return templates.TemplateResponse("city.html", {"request": request})

# Handle lifecycle events
@app.on_event("startup")
async def startup():
    print("Application startup: Connecting to MongoDB")

@app.on_event("shutdown")
async def shutdown():
    print("Application shutdown: Closing MongoDB connection")
    client.close()
