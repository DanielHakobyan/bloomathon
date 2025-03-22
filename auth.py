import os
import smtplib
import random
from fastapi import APIRouter, Depends, HTTPException, status, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from passlib.context import CryptContext
from jose import jwt, JWTError
from datetime import datetime, timedelta
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from fastapi.templating import Jinja2Templates
from fastapi.security import OAuth2PasswordBearer
from typing import Union
from typing import Dict
from fastapi import Response
from datetime import datetime, timezone
from fastapi import FastAPI, Response, APIRouter

app = FastAPI()
router = APIRouter()


load_dotenv()

router = APIRouter()

# Database setup
MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME")
client = AsyncIOMotorClient(MONGO_URI)
db = client[DB_NAME]
users_collection = db["users"]

# JWT Config
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = 60

# Password Hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

templates = Jinja2Templates(directory="templates")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


def get_token_from_cookie(request: Request) -> str:
    """ Extract the access token from the cookies in the request """
    access_token = request.cookies.get("access_token")
    if not access_token:
        raise HTTPException(status_code=401, detail="Access token missing in cookies")
    return access_token


def hash_password(password: str):
    return pwd_context.hash(password)


def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: Union[timedelta, None] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)  # Default expiration
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def get_user(email: str):
    return await users_collection.find_one({"email": email})


async def get_current_user(request: Request) -> Dict:
    token = get_token_from_cookie(request)
    try:
        # Decode the token
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")  # Get the email from the token's subject
        
        if email is None:
            raise HTTPException(status_code=401, detail="Could not validate credentials")
        
        # Fetch the user from the database
        user = await get_user(email)  # We need to await this, so get_user must be async
        if user is None:
            raise HTTPException(status_code=401, detail="User not found")
        
        return user
    except JWTError:
        raise HTTPException(status_code=401, detail="Could not validate credentials")


def send_verification_email(email: str, verification_code: int):
    smtp_server = os.getenv("SMTP_SERVER")
    smtp_port = int(os.getenv("SMTP_PORT"))
    smtp_user = os.getenv("SMTP_USERNAME")
    smtp_pass = os.getenv("SMTP_PASSWORD")

    message = f"Subject: Verify your email\n\nYour verification code is: {verification_code}"

    print(f"Attempting to send email to {email} via {smtp_server}:{smtp_port}...")

    try:
        with smtplib.SMTP(smtp_server, smtp_port, timeout=10) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, email, message)
            print("Email sent successfully!")
    except Exception as e:
        print("Email sending failed:", e)
        raise HTTPException(status_code=500, detail=f"Failed to send verification email: {str(e)}")


# GET: Render Registration Page
@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})


# POST: Register User
@router.post("/register")
async def register(email: str = Form(...), password: str = Form(...)):
    existing_user = await get_user(email)
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    try:
        # Hash the password
        hashed_password = hash_password(password)

        # Generate a random verification code
        verification_code = random.randint(100000, 999999)

        # Prepare user data to store
        user_data = {
            "email": email,
            "password": hashed_password,
            "is_verified": False,  # Initially, the user is not verified
            "verification_code": verification_code,
            "role": "user",
        }

        # Insert user into the database
        await users_collection.insert_one(user_data)

        # Send verification email with the code
        send_verification_email(email, verification_code)

        # Redirect to the verification page with the email
        return RedirectResponse(url=f"/auth/verify?email={email}", status_code=303)

    except Exception as e:
        print(f"Error occurred while sending email: {e}")
        raise HTTPException(status_code=500, detail="Failed to send verification email")


# GET: Render Verification Page
@router.get("/verify", response_class=HTMLResponse)
async def verify_page(request: Request, email: str):
    # Check if the email exists in the database
    user = await get_user(email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return templates.TemplateResponse("verify.html", {"request": request, "email": email})


# POST: Verify Email Code
@router.post("/verify-email")
async def verify_email(email: str = Form(...), verification_code: int = Form(...)):
    user = await get_user(email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user["verification_code"] != verification_code:
        raise HTTPException(status_code=400, detail="Invalid verification code")

    # Update user verification status
    await users_collection.update_one({"email": email}, {"$set": {"is_verified": True}})
    return {"message": "Email verified successfully"}


# GET: Render Login Page
@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


# POST: Login User
@router.post("/login")
async def login(email: str = Form(...), password: str = Form(...)):
    user = await get_user(email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not verify_password(password, user["password"]):
        raise HTTPException(status_code=400, detail="Incorrect password")

    if not user["is_verified"]:
        raise HTTPException(status_code=400, detail="Email not verified")

    # Create access token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user["email"], "role": user["role"]},
        expires_delta=access_token_expires,
    )

    # Redirect and set the token in cookies
    response = RedirectResponse(url="/auth/login-success", status_code=303)
    response.set_cookie(
        key="access_token", 
        value=access_token, 
        httponly=True, 
        max_age=3600,  # 1 hour
        secure=False,  # Set to True if using HTTPS in production
        samesite="Lax"
    )
    return response

@router.get("/login-success", response_class=HTMLResponse)
async def login_success_page(request: Request):
    return templates.TemplateResponse("login_success.html", {"request": request})


# POST: Logout User
from datetime import datetime, timedelta

@router.post("/logout")
async def logout(response: Response):
    # Delete cookie with the exact same attributes as it was set
    response.delete_cookie(
        "access_token", 
        path="/",  # Ensure this matches the path you set for the cookie
        secure=False,  # Make sure this matches whether you're using HTTP or HTTPS
        samesite="Lax"  # Ensure consistency in SameSite attribute
    )
    return {"message": "Logged out successfully"}
