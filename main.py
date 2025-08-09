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
from datetime import datetime, timedelta
import httpx
from typing import List, Optional
from pydantic import BaseModel

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
users_collection = db.get_collection("users")
issues_collection = db.get_collection("issues")
events_collection = db.get_collection("events")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# Dependency to get the DB session
def get_db():
    return db

async def run_fetch_news():
    await fetch_news(db)  

scheduler = BackgroundScheduler()
scheduler.add_job(run_fetch_news, trigger=IntervalTrigger(days=1))  
scheduler.start()

def str_to_objectid(id: str) -> ObjectId:
    try:
        return ObjectId(id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid ObjectId format")
    
async def get_current_admin(current_user: dict = Depends(auth.get_current_user)):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user
@app.get("/me")
def get_current_user(request: Request, current_user: dict = Depends(auth.get_current_user)):
    return {"email": current_user.get("email")}

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

    result = await issues_collection.insert_one(issue_data)
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

class SearchRequest(BaseModel):
    user_email: Optional[str] = ""
    status: Optional[str] = ""
    priority: Optional[str] = ""
    date_range: Optional[str] = ""
    page: int = 1
    limit: int = 20

class UserProfileResponse(BaseModel):
    user: dict
    stats: dict
    recent_issues: list
    recent_events: list

# Admin Issues Search Route
@app.post("/admin/issues/search")
async def search_issues(search_request: SearchRequest, current_user=Depends(get_current_admin)):
    try:
        # Build query filter
        filter_query = {}

        if search_request.user_email:
            filter_query["reported_by"] = {"$regex": search_request.user_email, "$options": "i"}
        if search_request.status:
            filter_query["status"] = search_request.status
        if search_request.priority:
            filter_query["priority"] = search_request.priority
        
        skip = (search_request.page - 1) * search_request.limit
        
        issues_cursor = issues_collection.find(filter_query).sort("created_at", -1).skip(skip).limit(search_request.limit)
        issues = await issues_cursor.to_list(length=search_request.limit)
        
        for issue in issues:
            issue["_id"] = str(issue["_id"])
            if issue.get("created_at"):
                issue["created_at"] = issue["created_at"].isoformat()
            if issue.get("updated_at"):
                issue["updated_at"] = issue["updated_at"].isoformat()
        
        total_count = await issues_collection.count_documents(filter_query)
        
        return {
            "issues": issues,
            "total": total_count,
            "page": search_request.page,
            "limit": search_request.limit
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")

# Admin Events Search Route
@app.post("/admin/events/search")
async def search_events(search_request: SearchRequest, current_user=Depends(get_current_admin)):
    try:
        # Build query filter
        filter_query = {}
        
        # Search by organizer email
        if search_request.user_email:
            filter_query["organizer_email"] = {"$regex": search_request.user_email, "$options": "i"}
        
        # Filter by status
        if search_request.status:
            filter_query["status"] = search_request.status
            
        # Filter by date range
        if search_request.date_range:
            now = datetime.utcnow()
            if search_request.date_range == "upcoming":
                filter_query["event_date"] = {"$gte": now}
            elif search_request.date_range == "this_week":
                week_start = now - timedelta(days=now.weekday())
                week_end = week_start + timedelta(days=6)
                filter_query["event_date"] = {"$gte": week_start, "$lte": week_end}
            elif search_request.date_range == "this_month":
                month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                if now.month == 12:
                    month_end = month_start.replace(year=now.year + 1, month=1) - timedelta(days=1)
                else:
                    month_end = month_start.replace(month=now.month + 1) - timedelta(days=1)
                filter_query["event_date"] = {"$gte": month_start, "$lte": month_end}
            elif search_request.date_range == "past":
                filter_query["event_date"] = {"$lt": now}
        
        # Calculate pagination
        skip = (search_request.page - 1) * search_request.limit
        
        # Get events with pagination
        events_cursor = events_collection.find(filter_query).sort("created_at", -1).skip(skip).limit(search_request.limit)
        events = await events_cursor.to_list(length=search_request.limit)
        
        # Convert ObjectId to string and format dates for JSON serialization
        for event in events:
            event["_id"] = str(event["_id"])
            if event.get("created_at"):
                event["created_at"] = event["created_at"].isoformat()
            if event.get("updated_at"):
                event["updated_at"] = event["updated_at"].isoformat()
            if event.get("event_date"):
                event["event_date"] = event["event_date"].isoformat()
        
        # Get total count for pagination
        total_count = await events_collection.count_documents(filter_query)
        
        # Calculate statistics for filtered results
        stats_pipeline = [
            {"$match": filter_query},
            {"$group": {
                "_id": "$status",
                "count": {"$sum": 1}
            }}
        ]
        stats_cursor = events_collection.aggregate(stats_pipeline)
        stats_list = await stats_cursor.to_list(length=None)
        
        stats = {
            "total": total_count,
            "pending": 0,
            "completed": 0,
            "canceled": 0
        }
        
        for stat in stats_list:
            if stat["_id"] in stats:
                stats[stat["_id"]] = stat["count"]
        
        return {
            "events": events,
            "total": total_count,
            "page": search_request.page,
            "limit": search_request.limit,
            "stats": stats
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")

# Get User Profile for Admin
@app.get("/admin/users/{user_email}/profile")
async def get_user_profile(user_email: str, current_user=Depends(get_current_admin)):
    try:
        # Get user details
        user = await users_collection.find_one({"email": user_email})
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Convert ObjectId to string
        user["_id"] = str(user["_id"])
        if user.get("created_at"):
            user["created_at"] = user["created_at"].isoformat()
        
        # Get user statistics
        issues_stats = await issues_collection.aggregate([
            {"$match": {"reported_by": user_email}},
            {"$group": {
                "_id": "$status",
                "count": {"$sum": 1}
            }}
        ]).to_list(length=None)
        
        events_count = await events_collection.count_documents({"organizer_email": user_email})
        
        total_issues = sum(stat["count"] for stat in issues_stats)
        resolved_issues = next((stat["count"] for stat in issues_stats if stat["_id"] == "resolved"), 0)
        
        stats = {
            "total_issues": total_issues,
            "total_events": events_count,
            "resolved_issues": resolved_issues
        }
        
        # Get recent issues (last 5)
        recent_issues_cursor = issues_collection.find({"reported_by": user_email}).sort("created_at", -1).limit(5)
        recent_issues = await recent_issues_cursor.to_list(length=5)
        
        for issue in recent_issues:
            issue["_id"] = str(issue["_id"])
            if issue.get("created_at"):
                issue["created_at"] = issue["created_at"].isoformat()
        
        # Get recent events (last 5)
        recent_events_cursor = events_collection.find({"organizer_email": user_email}).sort("created_at", -1).limit(5)
        recent_events = await recent_events_cursor.to_list(length=5)
        
        for event in recent_events:
            event["_id"] = str(event["_id"])
            if event.get("created_at"):
                event["created_at"] = event["created_at"].isoformat()
            if event.get("event_date"):
                event["event_date"] = event["event_date"].isoformat()
        
        return {
            "user": user,
            "stats": stats,
            "recent_issues": recent_issues,
            "recent_events": recent_events
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get user profile: {str(e)}")

# Get Individual Issue Details
@app.get("/admin/issues/{issue_id}")
async def get_issue_details(issue_id: str, current_user=Depends(get_current_admin)):
    try:
        from bson import ObjectId
        
        issue = await issues_collection.find_one({"_id": ObjectId(issue_id)})
        if not issue:
            raise HTTPException(status_code=404, detail="Issue not found")
        
        # Convert ObjectId to string and format dates
        issue["_id"] = str(issue["_id"])
        if issue.get("created_at"):
            issue["created_at"] = issue["created_at"].isoformat()
        if issue.get("updated_at"):
            issue["updated_at"] = issue["updated_at"].isoformat()
        
        return issue
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get issue details: {str(e)}")

# Get Individual Event Details
@app.get("/admin/events/{event_id}")
async def get_event_details(event_id: str, current_user=Depends(get_current_admin)):
    try:
        from bson import ObjectId
        
        event = await events_collection.find_one({"_id": ObjectId(event_id)})
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
        
        # Convert ObjectId to string and format dates
        event["_id"] = str(event["_id"])
        if event.get("created_at"):
            event["created_at"] = event["created_at"].isoformat()
        if event.get("updated_at"):
            event["updated_at"] = event["updated_at"].isoformat()
        if event.get("event_date"):
            event["event_date"] = event["event_date"].isoformat()
        
        return event
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get event details: {str(e)}")

# Export User Data
@app.get("/admin/users/{user_email}/export")
async def export_user_data(user_email: str, current_user=Depends(get_current_admin)):
    try:
        # Get user data
        user = await users_collection.find_one({"email": user_email})
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Get all user issues
        user_issues_cursor = issues_collection.find({"reported_by": user_email})
        user_issues = await user_issues_cursor.to_list(length=None)
        
        # Get all user events
# Get all user events
        user_events_cursor = events_collection.find({"reported_by": user_email}).sort("created_at", -1)
        user_events = await user_events_cursor.to_list(length=None)
        
        # Prepare data for export
        export_data = {
            "user": {
                "email": user["email"],
                "created_at": user.get("created_at", "").isoformat() if user.get("created_at") else "",
                "is_admin": user.get("is_admin", False)
            },
            "issues": [],
            "events": []
        }
        
        # Format issues
        for issue in user_issues:
            export_data["issues"].append({
                "title": issue.get("title", ""),
                "description": issue.get("description", ""),
                "category": issue.get("category", ""),
                "status": issue.get("status", ""),
                "priority": issue.get("priority", ""),
                "reported_by": issue.get("reported_by", ""),
                "address": issue.get("address", ""),
                "created_at": issue.get("created_at", "").isoformat() if issue.get("created_at") else "",
                "updated_at": issue.get("updated_at", "").isoformat() if issue.get("updated_at") else ""
            })
        
        # Format events
        for event in user_events:
            export_data["events"].append({
                "title": event.get("title", ""),
                "description": event.get("description", ""),
                "location": event.get("location", ""),
                "status": event.get("status", ""),
                "event_date": event.get("event_date", "").isoformat() if event.get("event_date") else "",
                "created_at": event.get("created_at", "").isoformat() if event.get("created_at") else "",
                "updated_at": event.get("updated_at", "").isoformat() if event.get("updated_at") else ""
            })
        
        # Create CSV response
        from fastapi.responses import Response
        import csv
        import io
        
        output = io.StringIO()
        
        # Write user info
        output.write(f"User Data Export for {user_email}\n")
        output.write(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        # Write issues
        output.write("ISSUES\n")
        if export_data["issues"]:
            fieldnames = ["title", "description", "category", "status", "priority", "reported_by", "address", "created_at", "updated_at"]
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            for issue in export_data["issues"]:
                writer.writerow(issue)
        else:
            output.write("No issues found\n")
        
        output.write("\n\nEVENTS\n")
        if export_data["events"]:
            fieldnames = ["title", "description", "location", "status", "event_date", "created_at", "updated_at"]
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            for event in export_data["events"]:
                writer.writerow(event)
        else:
            output.write("No events found\n")
        
        csv_content = output.getvalue()
        output.close()
        
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={user_email}_data_export.csv"}
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to export user data: {str(e)}")

# Export Issues with Filters
@app.get("/admin/issues/export")
async def export_issues(
    user_email: Optional[str] = "",
    status: Optional[str] = "",
    priority: Optional[str] = "",
    current_user=Depends(get_current_admin)
):
    try:
        # Build query filter
        filter_query = {}
        
        if user_email:
            filter_query["reported_by"] = {"$regex": user_email, "$options": "i"}
        if status:
            filter_query["status"] = status
        if priority:
            filter_query["priority"] = priority
        
        # Get filtered issues
        issues_cursor = issues_collection.find(filter_query).sort("created_at", -1)
        issues = await issues_cursor.to_list(length=None)
        
        # Create CSV response
        from fastapi.responses import Response
        import csv
        import io
        
        output = io.StringIO()
        
        if issues:
            fieldnames = ["title", "description", "category", "status", "priority", "reported_by", "location", "created_at", "updated_at"]
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            
            for issue in issues:
                writer.writerow({
                    "title": issue.get("title", ""),
                    "description": issue.get("description", ""),
                    "category": issue.get("category", ""),
                    "status": issue.get("status", ""),
                    "priority": issue.get("priority", ""),
                    "reported_by": issue.get("reported_by", ""),
                    "location": issue.get("location", ""),
                    "created_at": issue.get("created_at", "").isoformat() if issue.get("created_at") else "",
                    "updated_at": issue.get("updated_at", "").isoformat() if issue.get("updated_at") else ""
                })
        else:
            output.write("No issues found matching the criteria")
        
        csv_content = output.getvalue()
        output.close()
        
        # Generate filename based on filters
        filename_parts = ["issues_export"]
        if user_email:
            filename_parts.append(f"user_{user_email.replace('@', '_at_')}")
        if status:
            filename_parts.append(f"status_{status}")
        if priority:
            filename_parts.append(f"priority_{priority}")
        filename_parts.append(datetime.now().strftime("%Y%m%d_%H%M%S"))
        filename = "_".join(filename_parts) + ".csv"
        
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to export issues: {str(e)}")

# Export Events with Filters
@app.get("/admin/events/export")
async def export_events(
    user_email: Optional[str] = "",
    status: Optional[str] = "",
    date_range: Optional[str] = "",
    current_user=Depends(get_current_admin)
):
    try:
        # Build query filter (same logic as search)
        filter_query = {}
        
        if user_email:
            filter_query["organizer_email"] = {"$regex": user_email, "$options": "i"}
        if status:
            filter_query["status"] = status
        if date_range:
            now = datetime.utcnow()
            if date_range == "upcoming":
                filter_query["event_date"] = {"$gte": now}
            elif date_range == "this_week":
                week_start = now - timedelta(days=now.weekday())
                week_end = week_start + timedelta(days=6)
                filter_query["event_date"] = {"$gte": week_start, "$lte": week_end}
            elif date_range == "this_month":
                month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                if now.month == 12:
                    month_end = month_start.replace(year=now.year + 1, month=1) - timedelta(days=1)
                else:
                    month_end = month_start.replace(month=now.month + 1) - timedelta(days=1)
                filter_query["event_date"] = {"$gte": month_start, "$lte": month_end}
            elif date_range == "past":
                filter_query["event_date"] = {"$lt": now}
        
        # Get filtered events
        events_cursor = events_collection.find(filter_query).sort("created_at", -1)
        events = await events_cursor.to_list(length=None)
        
        # Create CSV response
        from fastapi.responses import Response
        import csv
        import io
        
        output = io.StringIO()
        
        if events:
            fieldnames = ["title", "description", "location", "status", "organizer_email", "event_date", "max_participants", "current_participants", "created_at", "updated_at"]
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            
            for event in events:
                writer.writerow({
                    "title": event.get("title", ""),
                    "description": event.get("description", ""),
                    "location": event.get("location", ""),
                    "status": event.get("status", ""),
                    "organizer_email": event.get("organizer_email", ""),
                    "event_date": event.get("event_date", "").isoformat() if event.get("event_date") else "",
                    "max_participants": event.get("max_participants", ""),
                    "current_participants": event.get("current_participants", 0),
                    "created_at": event.get("created_at", "").isoformat() if event.get("created_at") else "",
                    "updated_at": event.get("updated_at", "").isoformat() if event.get("updated_at") else ""
                })
        else:
            output.write("No events found matching the criteria")
        
        csv_content = output.getvalue()
        output.close()
        
        # Generate filename based on filters
        filename_parts = ["events_export"]
        if user_email:
            filename_parts.append(f"organizer_{user_email.replace('@', '_at_')}")
        if status:
            filename_parts.append(f"status_{status}")
        if date_range:
            filename_parts.append(f"date_{date_range}")
        filename_parts.append(datetime.now().strftime("%Y%m%d_%H%M%S"))
        filename = "_".join(filename_parts) + ".csv"
        
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to export events: {str(e)}")

# Suspend User
@app.post("/admin/users/{user_email}/suspend")
async def suspend_user(user_email: str, current_user=Depends(get_current_admin)):
    try:
        # Check if user exists
        user = await users_collection.find_one({"email": user_email})
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Don't allow suspending other admins
        if user.get("role") == "admin":
            raise HTTPException(status_code=403, detail="Cannot suspend admin users")
        
        # Update user status
        result = await users_collection.update_one(
            {"email": user_email},
            {
                "$set": {
                    "is_suspended": True,
                    "suspended_at": datetime.utcnow(),
                    "suspended_by": current_user["email"]
                }
            }
        )
        
        if result.modified_count == 0:
            raise HTTPException(status_code=500, detail="Failed to suspend user")
        
        return {"message": "User suspended successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to suspend user: {str(e)}")

# Helper function to get current admin (you'll need to implement this based on your auth system)
async def get_current_admin(current_user=Depends(auth.get_current_user)):
    """
    This function should verify that the current user is an admin.
    Modify this according to your existing authentication system.
    """
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user

# Update the existing issue update route to handle priority
@app.post("/admin/issues/{issue_id}/update")
async def update_issue_admin(
    issue_id: str, 
    request: Request,
    current_user=Depends(get_current_admin)
):
    try:
        from bson import ObjectId
        
        form = await request.form()
        status = form.get("status")
        priority = form.get("priority")
        
        update_data = {
            "updated_at": datetime.utcnow(),
            "updated_by": current_user["email"]
        }
        
        if status:
            update_data["status"] = status
        if priority:
            update_data["priority"] = priority
        
        result = await issues_collection.update_one(
            {"_id": ObjectId(issue_id)},
            {"$set": update_data}
        )
        
        if result.modified_count == 0:
            raise HTTPException(status_code=404, detail="Issue not found or not updated")
        
        # Redirect back to admin issues page
        return RedirectResponse(url="/admin/issues", status_code=303)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update issue: {str(e)}")

# User Profile Route (accessible to users themselves)
@app.get("/profile/full")
async def get_full_profile(request: Request, current_user=Depends(auth.get_current_user)):
    try:
        user_email = current_user["email"]
        
        # Get user statistics
        issues_stats = await issues_collection.aggregate([
            {"$match": {"reported_by": user_email}},
            {"$group": {
                "_id": "$status",
                "count": {"$sum": 1}
            }}
        ]).to_list(length=None)
        
        events_count = await events_collection.count_documents({"organizer_email": user_email})
        
        total_issues = sum(stat["count"] for stat in issues_stats)
        resolved_issues = next((stat["count"] for stat in issues_stats if stat["_id"] == "resolved"), 0)
        
        # Get all user issues
        user_issues_cursor = issues_collection.find({"reported_by": user_email}).sort("created_at", -1)
        user_issues = await user_issues_cursor.to_list(length=None)
        
        # Get all user events
        user_events_cursor = events_collection.find({"reported_by": user_email}).sort("created_at", -1)
        user_events = await user_events_cursor.to_list(length=None)
        
        # Format dates for template
        for issue in user_issues:
            if issue.get("created_at"):
                issue["created_at"] = issue["created_at"]
            if issue.get("updated_at"):
                issue["updated_at"] = issue["updated_at"]
        
        for event in user_events:
                    event["_id"] = str(event["_id"])
                    if event.get("created_at"):
                        event["created_at"] = event["created_at"]
                    if event.get("updated_at"):
                        event["updated_at"] = event["updated_at"]
                    
                    # Process photos for issues
                    if event.get("photos"):
                        event["photos"] = [f"/files/{photo_id}" for photo_id in event["photos"]]
                    else:
                        event["photos"] = []
                    
                    # Process single photo (for backward compatibility)
                    if event.get("photo"):
                        if not event["photos"]:  # Only add if photos array is empty
                            event["photos"] = [f"/files/{event['photo']}"]
                    
                    # Process video for issues
                    event["video"] = f"/files/{event['video']}" if event.get("video") else None
        
        stats = {
            "total_issues": total_issues,
            "total_events": events_count,
            "resolved_issues": resolved_issues,
            "pending_issues": next((stat["count"] for stat in issues_stats if stat["_id"] == "pending"), 0),
            "in_progress_issues": next((stat["count"] for stat in issues_stats if stat["_id"] == "in_progress"), 0)
        }
        
        return templates.TemplateResponse("profile_full.html", {
            "request": request,
            "user": current_user,
            "stats": stats,
            "user_issues": user_issues,
            "user_events": user_events
        })
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load profile: {str(e)}")

# Additional route to get admin dashboard statistics
@app.get("/admin/stats")
async def get_admin_stats(current_user=Depends(get_current_admin)):
    try:
        # Issues statistics
        issues_stats = await issues_collection.aggregate([
            {"$group": {
                "_id": "$status",
                "count": {"$sum": 1}
            }}
        ]).to_list(length=None)
        
        # Events statistics  
        events_stats = await events_collection.aggregate([
            {"$group": {
                "_id": "$status",
                "count": {"$sum": 1}
            }}
        ]).to_list(length=None)
        
        # Users count
        total_users = await users_collection.count_documents({})
        
        # Format statistics
        issue_stats_formatted = {
            "total": sum(stat["count"] for stat in issues_stats),
            "pending": 0,
            "in_progress": 0,
            "resolved": 0,
            "closed": 0
        }
        
        for stat in issues_stats:
            if stat["_id"] in issue_stats_formatted:
                issue_stats_formatted[stat["_id"]] = stat["count"]
        
        event_stats_formatted = {
            "total": sum(stat["count"] for stat in events_stats),
            "pending": 0,
            "completed": 0,
            "canceled": 0
        }
        
        for stat in events_stats:
            if stat["_id"] in event_stats_formatted:
                event_stats_formatted[stat["_id"]] = stat["count"]
        
        return {
            "issues": issue_stats_formatted,
            "events": event_stats_formatted,
            "users": {"total": total_users}
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get admin stats: {str(e)}")

@app.get("/admin/issues")
async def admin_issues_page(request: Request, current_user=Depends(get_current_admin)):
    try:
        issues_cursor = issues_collection.find({}).sort("created_at", -1).limit(50)
        issues = await issues_cursor.to_list(length=50)
        
        for issue in issues:
            issue["_id"] = str(issue["_id"])
            if issue.get('photo'):
                issue["photo"] = f"/files/{issue['photo']}"

        stats_response = await get_admin_stats(current_user)
        
        return templates.TemplateResponse("admin_issues.html", {
            "request": request,
            "issues": issues,
            "stats": stats_response["issues"]
        })
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load admin issues page: {str(e)}")

# NEW ROUTE for Admin Users Page
@app.get("/admin/users", response_class=HTMLResponse)
async def admin_users_page(request: Request, current_user: dict = Depends(get_current_admin)):
    users = await users_collection.find({}).to_list(length=None)
    for user in users:
        user["_id"] = str(user["_id"])
    return templates.TemplateResponse("admin_users.html", {"request": request, "users": users})

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
async def admin_events_page(request: Request, current_user: dict = Depends(get_current_admin)):
    # The redundant role check is removed, as Depends(get_current_admin) handles it.
    events = await db.events.find().to_list()
    for event in events:
        event["_id"] = str(event["_id"])

    stats_response = await get_admin_stats(current_user)

    return templates.TemplateResponse(
        "admin_events.html", 
        {
            "request": request, 
            "events": events,
            "stats": stats_response["events"]
        }
    )

@app.post("/admin/events/{event_id}/update")
async def update_events_status(event_id: str, status: str = Form(...), current_user: dict = Depends(get_current_admin)):
    # The redundant role check is removed, as Depends(get_current_admin) handles it.
    if not ObjectId.is_valid(event_id):
        raise HTTPException(status_code=400, detail="Invalid event ID format")

    if status not in ["completed", "canceled"]:
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
        if event.get("photos"):
            event["photos"] = [f"/files/{photo_id}" for photo_id in event["photos"]]
        else:
            event["photos"] = []
        event["video"] = f"/files/{event['video']}" if event.get("video") else None
    return templates.TemplateResponse("view_events.html", {"request": request, "events": events})

@app.get("/create_event", response_class=HTMLResponse)
async def create_event_page(request: Request, current_user: dict = Depends(auth.get_current_user)):
    if not current_user.get("is_verified", False):
        raise HTTPException(status_code=403, detail="Verify email first.")
    return templates.TemplateResponse("create_event.html", {"request": request})

@app.post("/event/")
async def create_event(
    request: Request,
    title: str = Form(...),
    description: str = Form(...),
    datetime: str = Form(...),
    duration: str = Form(...),
    location: str = Form(...),
    location_description: str = Form(...),
    photos: List[UploadFile] = File(None),
    video: UploadFile = File(None),
    current_user: dict = Depends(auth.get_current_user)
):
    location_parts = location.split(",")
    lat, lng = (float(location_parts[0].strip()), 
                float(location_parts[1].strip())) if len(location_parts) == 2 else (None, None)

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
        "photos": [],
        "video": None,
        "status": "pending",
    }

    if photos:
        for photo in photos:
            if photo and photo.filename:
                photo_id = await upload_to_gridfs(photo)
                event_data["photos"].append(str(photo_id))

    if video and video.filename:
        event_data["video"] = str(await upload_to_gridfs(video))

    result = await events_collection.insert_one(event_data)
    return {"message": "Event submitted successfully!", "id": str(result.inserted_id)} if result.inserted_id else HTTPException(500, "Failed")

@app.post("/profile/issues/{issue_id}/edit")
async def edit_issue(issue_id: str, 
                     title: str = Form(...), 
                     description: str = Form(...),
                     location_description: str = Form(...),
                     current_user: dict = Depends(auth.get_current_user)):
    issue = await db.issues.find_one({"_id": ObjectId(issue_id)})
    if not issue or issue["reported_by"] != current_user["email"]:
        raise HTTPException(status_code=403, detail="Unauthorized")

    await db.issues.update_one(
        {"_id": ObjectId(issue_id)},
        {"$set": {"title": title, "description": description, "location_description": location_description}}
    )
    return RedirectResponse(url="/profile/full", status_code=303)


@app.post("/profile/issues/{issue_id}/delete")
async def delete_issue(issue_id: str, current_user: dict = Depends(auth.get_current_user)):
    issue = await db.issues.find_one({"_id": ObjectId(issue_id)})
    if not issue or issue["reported_by"] != current_user["email"]:
        raise HTTPException(status_code=403, detail="Unauthorized")

    await db.issues.delete_one({"_id": ObjectId(issue_id)})
    return RedirectResponse(url="/profile/full", status_code=303)


@app.post("/profile/events/{event_id}/edit")
async def edit_event(event_id: str, 
                     title: str = Form(...), 
                     description: str = Form(...),
                     location_description: str = Form(...),
                     current_user: dict = Depends(auth.get_current_user)):
    event = await db.events.find_one({"_id": ObjectId(event_id)})
    if not event or event["reported_by"] != current_user["email"]:
        raise HTTPException(status_code=403, detail="Unauthorized")

    await db.events.update_one(
        {"_id": ObjectId(event_id)},
        {"$set": {"title": title, "description": description, "location_description": location_description}}
    )
    return RedirectResponse(url="/profile/full", status_code=303)


@app.post("/profile/events/{event_id}/delete")
async def delete_event(event_id: str, current_user: dict = Depends(auth.get_current_user)):
    event = await db.events.find_one({"_id": ObjectId(event_id)})
    if not event or event["reported_by"] != current_user["email"]:
        raise HTTPException(status_code=403, detail="Unauthorized")

    await db.events.delete_one({"_id": ObjectId(event_id)})
    return RedirectResponse(url="/profile/full", status_code=303)

@app.post("/ai/suggest")
async def ai_suggest(description: str = Form(...)):
    prompt = f"""Citizen reported the following issue: "{description}"
Suggest one or more actionable steps that city officials can take to resolve it."""

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "mistralai/mistral-7b-instruct:free",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant for municipal problem solving."},
            {"role": "user", "content": prompt}
        ]
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload
            )
            response.raise_for_status()
            suggestion = response.json()["choices"][0]["message"]["content"]
            return {"suggestion": suggestion.strip()}
    except Exception as e:
        return {"error": str(e)}

@app.on_event("startup")
async def startup():
    if await db.news.count_documents({}) == 0:
        await fetch_news(db)

@app.on_event("shutdown")
def shutdown_scheduler():
    scheduler.shutdown()

async def shutdown():
    client.close()