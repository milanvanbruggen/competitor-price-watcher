from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from price_calculator import PriceCalculator
from scraper import MaterialScraper

app = FastAPI()

class URLInput(BaseModel):
    url: str
    dimensions: dict = {
        'dikte': 2,
        'lengte': 1000,
        'breedte': 1000
    }

class PriceResponse(BaseModel):
    price_excl_btw: float
    price_incl_btw: float

class AnalyzeResponse(BaseModel):
    url: str
    dimension_fields: dict

@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze_url(input: URLInput):
    try:
        # Initialiseer scraper
        scraper = MaterialScraper()
        
        # Analyseer de URL
        results = scraper.analyze_form_fields(input.url)
        
        return AnalyzeResponse(
            url=input.url,
            dimension_fields=results['dimension_fields']
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/price", response_model=PriceResponse)
async def get_price(input: URLInput):
    try:
        # Initialiseer calculator
        calculator = PriceCalculator()
        
        # Bereken prijzen
        excl_btw, incl_btw = calculator.calculate_price(
            url=input.url,
            dimensions=input.dimensions
        )
        
        return PriceResponse(
            price_excl_btw=excl_btw,
            price_incl_btw=incl_btw
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
async def root():
    return {"message": "Welkom bij de Materiaal Prijs API"} 