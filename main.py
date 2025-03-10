from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

app = FastAPI()
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
async def homepage(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/city", response_class=HTMLResponse)
async def city_page(request: Request):
    return templates.TemplateResponse("city.html", {"request": request})

@app.get("/map", response_class=HTMLResponse)
async def map_page(request: Request):
    return templates.TemplateResponse("map.html", {"request": request})

@app.get("/transport", response_class=HTMLResponse)
async def transport_page(request: Request):
    return templates.TemplateResponse("transport.html", {"request": request})

@app.get("/report", response_class=HTMLResponse)
async def report_page(request: Request):
    return templates.TemplateResponse("report_issue.html", {"request": request})

@app.get("/news", response_class=HTMLResponse)
async def news_page(request: Request):
    return templates.TemplateResponse("news.html", {"request": request})

@app.get("/statistics", response_class=HTMLResponse)
async def statistics_page(request: Request):
    return templates.TemplateResponse("statistics.html", {"request": request})
