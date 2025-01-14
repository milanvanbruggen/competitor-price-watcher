from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from fastapi.requests import Request
from pydantic import BaseModel
from typing import Optional
from price_calculator import PriceCalculator
from domain_config import DomainConfig
import logging

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

app = FastAPI()

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Templates configuration
templates = Jinja2Templates(directory="templates")

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

class PriceRequest(BaseModel):
    url: str
    dikte: float
    lengte: float
    breedte: float
    country: str

class PriceResponse(BaseModel):
    price_excl_vat: float
    price_incl_vat: float
    currency: str = "EUR"
    currency_symbol: str = "€"
    vat_rate: float = 21.0
    error: Optional[str] = None

# Initialize domain config and price calculator
domain_config = DomainConfig()
calculator = PriceCalculator(domain_config)

# Countries configuration
countries = {
    'nl': {'name': 'Nederland', 'currency': 'EUR', 'currency_symbol': '€', 'vat_rate': 21.0},
    'uk': {'name': 'United Kingdom', 'currency': 'GBP', 'currency_symbol': '£', 'vat_rate': 20.0},
    'de': {'name': 'Deutschland', 'currency': 'EUR', 'currency_symbol': '€', 'vat_rate': 19.0},
    'fr': {'name': 'France', 'currency': 'EUR', 'currency_symbol': '€', 'vat_rate': 20.0},
    'be': {'name': 'België', 'currency': 'EUR', 'currency_symbol': '€', 'vat_rate': 21.0},
    'es': {'name': 'España', 'currency': 'EUR', 'currency_symbol': '€', 'vat_rate': 21.0},
    'it': {'name': 'Italia', 'currency': 'EUR', 'currency_symbol': '€', 'vat_rate': 22.0},
    'pl': {'name': 'Polska', 'currency': 'PLN', 'currency_symbol': 'zł', 'vat_rate': 23.0},
    'se': {'name': 'Sverige', 'currency': 'SEK', 'currency_symbol': 'kr', 'vat_rate': 25.0},
    'dk': {'name': 'Danmark', 'currency': 'DKK', 'currency_symbol': 'kr', 'vat_rate': 25.0}
}

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "countries": countries})

@app.post("/calculate-price")
async def calculate_price(request: PriceRequest) -> PriceResponse:
    try:
        dimensions = {
            'dikte': request.dikte,
            'lengte': request.lengte,
            'breedte': request.breedte
        }
        
        price_excl_vat, price_incl_vat = await calculator.calculate_price(request.url, dimensions)
        
        return PriceResponse(
            price_excl_vat=price_excl_vat,
            price_incl_vat=price_incl_vat
        )
        
    except Exception as e:
        return PriceResponse(
            price_excl_vat=0,
            price_incl_vat=0,
            error=str(e)
        ) 