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

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME")
client = AsyncIOMotorClient(MONGO_URI)
db = client[DB_NAME]
users_collection = db["users"]

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = 60

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
        expire = datetime.utcnow() + timedelta(minutes=15)
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
        email: str = payload.get("sub") 
        
        if email is None:
            raise HTTPException(status_code=401, detail="Could not validate credentials")
        
        user = await get_user(email)
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


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})


@router.post("/register")
async def register(email: str = Form(...), password: str = Form(...)):
    existing_user = await get_user(email)
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    try:
        hashed_password = hash_password(password)

        verification_code = random.randint(100000, 999999)

        user_data = {
            "email": email,
            "password": hashed_password,
            "is_verified": False,
            "verification_code": verification_code,
            "role": "user",
        }

        await users_collection.insert_one(user_data)

        send_verification_email(email, verification_code)

        return RedirectResponse(url=f"/auth/verify?email={email}", status_code=303)

    except Exception as e:
        print(f"Error occurred while sending email: {e}")
        raise HTTPException(status_code=500, detail="Failed to send verification email")


@router.get("/verify", response_class=HTMLResponse)
async def verify_page(request: Request, email: str):
    # Check if the email exists in the database
    user = await get_user(email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return templates.TemplateResponse("verify.html", {"request": request, "email": email})


@router.post("/verify-email")
async def verify_email(email: str = Form(...), verification_code: int = Form(...)):
    user = await get_user(email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user["verification_code"] != verification_code:
        raise HTTPException(status_code=400, detail="Invalid verification code")

    await users_collection.update_one({"email": email}, {"$set": {"is_verified": True}})
    return {"message": "Email verified successfully"}


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login")
async def login(email: str = Form(...), password: str = Form(...)):
    user = await get_user(email)
    if not user:
        raise HTTPException(status_code=404, detail="Invalid credentials")

    if not verify_password(password, user["password"]):
        raise HTTPException(status_code=400, detail="Invalid credentials")

    if not user["is_verified"]:
        raise HTTPException(status_code=400, detail="Email not verified")

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user["email"], "role": user["role"]},
        expires_delta=access_token_expires,
    )

    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(
        key="access_token", 
        value=access_token, 
        httponly=False, 
        max_age=3600,  
        secure=False, 
        samesite="Lax"
    )
    return response

@router.get("/login-success", response_class=HTMLResponse)
async def login_success_page(request: Request):
    return templates.TemplateResponse("login_success.html", {"request": request})


from datetime import datetime, timedelta

from fastapi.responses import RedirectResponse

@router.post("/logout")
async def logout():
    response = RedirectResponse(url="/", status_code=303)  # Redirect to home
    response.delete_cookie(
        key="access_token",
        path="/",
        secure=False,
        samesite="Lax"
    )
    return response
