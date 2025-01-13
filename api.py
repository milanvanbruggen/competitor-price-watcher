from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from price_calculator import PriceCalculator
from scraper import MaterialScraper

app = FastAPI()

# Templates configuratie
templates = Jinja2Templates(directory="templates")

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

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/calculate-price", response_model=PriceResponse)
async def calculate_price(input: URLInput):
    try:
        # Initialiseer scraper en calculator
        scraper = MaterialScraper()
        calculator = PriceCalculator()
        
        # Eerst de dimensie velden detecteren
        print(f"\nAnalyseren van dimensie velden voor {input.url}")
        results = await scraper.analyze_form_fields(input.url)
        dimension_fields = results['dimension_fields']
        
        # Bereken prijzen met de gevonden velden
        excl_btw, incl_btw = await calculator.calculate_price(
            url=input.url,
            dimensions=input.dimensions,
            dimension_fields=dimension_fields
        )
        
        return PriceResponse(
            price_excl_btw=excl_btw,
            price_incl_btw=incl_btw
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) 