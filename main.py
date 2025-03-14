import os
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel
from bson import ObjectId

# Load environment variables from .env file
load_dotenv()

# FastAPI setup
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins (you can specify specific origins for security)
    allow_credentials=True,
    allow_methods=["*"],  # Allow all HTTP methods (GET, POST, PUT, DELETE, etc.)
    allow_headers=["*"],  # Allow all headers
)

# Get the database connection details from environment variables
MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME")  # Database name
COLLECTION_NAME = os.getenv("COLLECTION_NAME")  # Collection name

# Set up AsyncIOMotorClient for asynchronous MongoDB operations
client = AsyncIOMotorClient(MONGO_URI)
db = client[DB_NAME]
issues_collection = db[COLLECTION_NAME]

# Jinja2 template setup
templates = Jinja2Templates(directory="templates")

# Pydantic model for validation
class Issue(BaseModel):
    title: str
    description: str
    location: str
    status: str = "Submitted"

# Home Page
@app.get("/", response_class=HTMLResponse)
async def homepage(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# Report Issue (Save to MongoDB) - POST route
@app.get("/report-issue", response_class=HTMLResponse)
async def report_issue_page(request: Request):
    return templates.TemplateResponse("report_issue.html", {"request": request})

@app.post("/report/", response_model=dict)
async def report_issue(issue: Issue):
    issue_dict = issue.model_dump()  # Use model_dump() instead of dict()
    result = await issues_collection.insert_one(issue_dict)
    if result.inserted_id:
        return {"message": "Issue reported successfully!", "id": str(result.inserted_id)}
    raise HTTPException(status_code=500, detail="Failed to report issue.")

# Get All Issues (Retrieve from MongoDB) - GET route
@app.get("/issues/", response_class=HTMLResponse)
async def get_issues(request: Request):
    issues = await issues_collection.find().to_list(100)  # Limit to 100 issues
    for issue in issues:
        issue["_id"] = str(issue["_id"])  # Convert ObjectId to string
    return templates.TemplateResponse("view_issues.html", {"request": request, "issues": issues})

@app.get("/transport")
async def transport_page(request: Request):
    return templates.TemplateResponse("transport.html", {"request": request})

@app.get("/news")
async def news_page(request: Request):
    return templates.TemplateResponse("news.html", {"request": request})

@app.get("/city")
async def city_page(request: Request):
    return templates.TemplateResponse("city.html", {"request": request})
