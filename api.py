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
    error: Optional[str] = None

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """HTML interface voor de API"""
    return templates.TemplateResponse(
        "index.html",
        {"request": request}
    )

@app.post("/calculate-price", response_model=PriceResponse)
async def calculate_price(input: DimensionsInput):
    """
    Berekent de prijs voor gegeven dimensies
    
    - **url**: De URL van de productpagina
    - **dimensions**: De dimensies in millimeters
        - dikte: Dikte in mm (default: 2)
        - lengte: Lengte in mm (default: 1000)
        - breedte: Breedte in mm (default: 1000)
    
    Returns:
        - De prijs exclusief en inclusief BTW
    """
    try:
        scraper = MaterialScraper()
        calculator = PriceCalculator()
        
        # Eerst de velden analyseren
        results = await scraper.analyze_form_fields(input.url)
        
        # Dan de prijs berekenen
        excl_btw, incl_btw = await calculator.calculate_price(
            url=input.url,
            dimensions=input.dimensions,
            dimension_fields=results['dimension_fields']
        )
        
        # Als beide prijzen 0 zijn, is er waarschijnlijk een fout opgetreden
        if excl_btw == 0 and incl_btw == 0:
            return PriceResponse(
                price_excl_btw=0,
                price_incl_btw=0,
                error=f"Kon geen prijs berekenen voor dikte {input.dimensions['dikte']}mm. Deze variant is niet beschikbaar."
            )
        
        return PriceResponse(
            price_excl_btw=excl_btw,
            price_incl_btw=incl_btw
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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