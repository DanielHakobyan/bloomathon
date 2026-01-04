
import os
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
import pymongo

load_dotenv()

async def test_connection():
    uri = os.getenv("MONGO_URI")
    print(f"Testing connection to URI length: {len(uri) if uri else 0}")
    if not uri:
        print("MONGO_URI is not set")
        return

    try:
        client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=5000)
        await client.server_info()
        print("Connection successful!")
    except Exception as e:
        with open("error.log", "w") as f:
            f.write(f"Connection failed: {type(e).__name__}: {e}")
        print("Logged error to error.log")

if __name__ == "__main__":
    asyncio.run(test_connection())
