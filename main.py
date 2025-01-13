from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Optional, Dict
from scraper import MaterialScraper
from price_calculator import PriceCalculator

app = FastAPI(
    title="Materiaal Prijs API",
    description="API voor het analyseren van materiaal prijzen en dimensies",
    version="1.0.0"
)

# Templates voor HTML interface
templates = Jinja2Templates(directory="templates")

# Static files voor CSS/JS
app.mount("/static", StaticFiles(directory="static"), name="static")

class URLInput(BaseModel):
    url: str

class DimensionsInput(BaseModel):
    url: str
    dimensions: Dict[str, float] = {
        'dikte': 2,
        'lengte': 1000,
        'breedte': 1000
    }

class AnalyzeResponse(BaseModel):
    url: str
    dimension_fields: dict

class PriceResponse(BaseModel):
    price_excl_btw: float
    price_incl_btw: float

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """HTML interface voor de API"""
    return templates.TemplateResponse(
        "index.html",
        {"request": request}
    )

@app.post("/api/analyze", response_model=AnalyzeResponse)
async def analyze_url(input: URLInput):
    """
    Analyseert een URL om dimensie velden te vinden
    
    - **url**: De URL van de productpagina om te analyseren
    
    Returns:
        - De gevonden dimensie velden (dikte, lengte, breedte, prijs)
    """
    try:
        scraper = MaterialScraper()
        results = await scraper.analyze_form_fields(input.url)
        
        return AnalyzeResponse(
            url=input.url,
            dimension_fields=results['dimension_fields']
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080) 