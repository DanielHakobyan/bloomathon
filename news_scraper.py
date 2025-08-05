import requests
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient
import asyncio
import os

NEWS_API_KEY = os.getenv("NEWS_API_KEY")
QUERY = "Rockville MD"
API_URL = f"https://newsapi.org/v2/everything?q={QUERY}&language=en&pageSize=10&apiKey={NEWS_API_KEY}"

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "local_news"

async def fetch_news(db):
    try:
        response = requests.get(API_URL)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"❌ Failed to fetch from NewsAPI: {e}")
        return

    articles = data.get("articles", [])
    for article in articles:
        title = article.get("title")
        link = article.get("url")
        published_at = article.get("publishedAt")

        if not title or not link:
            continue

        news_item = {
            "title": title,
            "link": link,
            "published_at": datetime.fromisoformat(published_at[:-1]) if published_at else datetime.utcnow(),
            "source": article.get("source", {}).get("name"),
        }

        await db.news.update_one({"title": title}, {"$set": news_item}, upsert=True)
        print(f"✅ Saved: {title}")

    print("✅ News fetch completed.")

if __name__ == "__main__":
    client = AsyncIOMotorClient(MONGO_URI)
    db = client[DB_NAME]
    asyncio.run(fetch_news(db))
