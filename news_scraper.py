import requests
from bs4 import BeautifulSoup
import io
from motor.motor_asyncio import AsyncIOMotorGridFSBucket
from datetime import datetime
from urllib.parse import urljoin


news_data = {}

WEBSITES = [
    {
        "url": "https://vanadzor.am/news/",
        "title_selector": "h4.entry-title a",
        "link_selector": "h4.entry-title a",
        "image_selector": "img",
        "max_articles": 6,
    },
    {
        "url": "https://am.sputniknews.ru/geo_Vanadzor/",
        "title_selector": "a.list__title",
        "link_selector": "a",
        "image_selector": "img",
        "max_articles": 3,
    },
    {
        "url": "https://ru.aravot.am/tag/%D0%B2%D0%B0%D0%BD%D0%B0%D0%B4%D0%B7%D0%BE%D1%80/",
        "title_selector": "h6.fs-13.mb-0 a",
        "link_selector": "h6.fs-13.mb-0 a",
        "image_selector": "img.rounded",
        "max_articles": 1,
    },
]

async def upload_image_to_gridfs(db, img_url):
    img_response = requests.get(img_url)
    img_content = img_response.content
    fs_bucket = AsyncIOMotorGridFSBucket(db)
    file_id = await fs_bucket.upload_from_stream(img_url.split("/")[-1], io.BytesIO(img_content))
    return file_id

WEBSITES = [
    {
        "url": "https://vanadzor.am/news/",
        "title_selector": "h4.entry-title a",
        "link_selector": "h4.entry-title a",
        "image_selector": "img",
        "max_articles": 6,
    },
    {
        "url": "https://am.sputniknews.ru/geo_Vanadzor/",
        "title_selector": "a.list__title",
        "link_selector": "a",
        "image_selector": "img",
        "max_articles": 3,
    },
    {
        "url": "https://ru.aravot.am/tag/%D0%B2%D0%B0%D0%BD%D0%B0%D0%B4%D0%B7%D0%BE%D1%80/",
        "title_selector": "h6.fs-13.mb-0 a",
        "link_selector": "h6.fs-13.mb-0 a",
        "image_selector": "img.rounded",
        "max_articles": 1,
    },
]

async def upload_image_to_gridfs(db, img_url):
    """Uploads image to GridFS and returns the file ID."""
    try:
        img_response = requests.get(img_url, timeout=10)
        img_response.raise_for_status()
        img_content = img_response.content

        fs_bucket = AsyncIOMotorGridFSBucket(db)
        file_id = await fs_bucket.upload_from_stream(img_url.split("/")[-1], io.BytesIO(img_content))
        return file_id
    except Exception as e:
        print(f"❌ Failed to upload image {img_url}: {e}")
        return None  # Return None if upload fails

import requests
from bs4 import BeautifulSoup
import io
from motor.motor_asyncio import AsyncIOMotorGridFSBucket
from datetime import datetime

WEBSITES = [
    {
        "url": "https://vanadzor.am/news/",
        "title_selector": "h4.entry-title a",
        "link_selector": "h4.entry-title a",
        "image_selector": "img",
        "max_articles": 6,
    },
    {
        "url": "https://am.sputniknews.ru/geo_Vanadzor/",
        "title_selector": "a.list__title",
        "link_selector": "a",
        "image_selector": "img",
        "max_articles": 3,
    },
    {
        "url": "https://ru.aravot.am/tag/%D0%B2%D0%B0%D0%BD%D0%B0%D0%B4%D0%B7%D0%BE%D1%80/",
        "title_selector": "h6.fs-13.mb-0 a",
        "link_selector": "h6.fs-13.mb-0 a",
        "image_selector": "img.rounded",
        "max_articles": 1,
    },
]

async def upload_image_to_gridfs(db, img_url):
    """Uploads image to GridFS and returns the file ID."""
    try:
        img_response = requests.get(img_url, timeout=10)
        img_response.raise_for_status()
        img_content = img_response.content

        fs_bucket = AsyncIOMotorGridFSBucket(db)
        file_id = await fs_bucket.upload_from_stream(img_url.split("/")[-1], io.BytesIO(img_content))
        return file_id
    except Exception as e:
        print(f"❌ Failed to upload image {img_url}: {e}")
        return None  # Return None if upload fails

async def fetch_news(db):
    """Fetches latest news and stores in MongoDB."""
    
    # ✅ Check if the database already has news
    existing_news_count = await db.news.count_documents({})
    if existing_news_count > 0:
        print("📰 News already exists in DB. Skipping immediate fetch.")
        return  # Skip fetching if news already exists

    print("⚡ Fetching news now since DB is empty!")

    unique_articles = set()
    for site in WEBSITES:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
            "Referer": site["url"],
        }
        try:
            response = requests.get(site["url"], headers=headers, timeout=10)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"❌ Failed to retrieve news from {site['url']}: {e}")
            continue

        soup = BeautifulSoup(response.text, "html.parser")
        articles = soup.select(site["title_selector"])

        if not articles:
            print(f"⚠️ No articles found on {site['url']} with selector {site['title_selector']}")
            continue

        articles_processed = 0
        for article in articles:
            if articles_processed >= site["max_articles"]:
                break

            title = article.get_text(strip=True)
            link = article["href"] if article.has_attr("href") else None

            if title in unique_articles or not link:
                continue  # Skip duplicates or invalid links

            unique_articles.add(title)

            # Ensure full link
            if not link.startswith("http"):
                link = site["url"] + link if not link.startswith("/") else "https://" + site["url"].split("/")[2] + link

            try:
                news_response = requests.get(link, headers=headers, timeout=10)
                news_response.raise_for_status()
            except requests.exceptions.RequestException as e:
                print(f"❌ Failed to retrieve article {link}: {e}")
                continue

            news_soup = BeautifulSoup(news_response.text, "html.parser")
            img_tag = news_soup.select_one(site["image_selector"])
            
            img_url = None
            if img_tag:
                # ✅ Handle lazy-loaded images (`data-src` or `src`)
                img_url = img_tag.get("data-src") or img_tag.get("src") or img_tag.get("srcset")

            # ✅ Ensure full image URL
            if img_url:
                img_url = urljoin(site["url"], img_url)
            
            # ✅ Upload image to GridFS
            image_id = None
            if img_url and not img_url.startswith("data:image"):  # Ignore invalid image URLs
                image_id = await upload_image_to_gridfs(db, img_url)

            # ✅ Store in MongoDB
            news_data = {
                "title": title,
                "link": link,
                "image_id": str(image_id) if image_id else None,  # Store image ID if available
                "published_at": datetime.now(),
            }

            await db.news.update_one({"title": title}, {"$set": news_data}, upsert=True)
            articles_processed += 1

    print("✅ News fetching completed.")







# Insert or update the news data in the database
    await db.news.update_one(
    {"title": title},
    {"$set": news_data},
    upsert=True
)   
    articles_processed += 1

