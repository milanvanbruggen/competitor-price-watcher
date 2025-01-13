from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Optional, Dict
import json
import os
from forex_python.converter import CurrencyRates
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

# Laad landen configuratie
with open('config/countries.json', 'r') as f:
    COUNTRIES = json.load(f)

class URLInput(BaseModel):
    url: str

class DimensionsInput(BaseModel):
    url: str
    dimensions: Dict[str, float] = {
        'dikte': 2,
        'lengte': 1000,
        'breedte': 1000
    }
    country: str = "nl"  # Default naar Nederland

class AnalyzeResponse(BaseModel):
    url: str
    dimension_fields: dict

class PriceResponse(BaseModel):
    price_excl_vat: float
    price_incl_vat: float
    currency: str
    currency_symbol: str
    vat_rate: float
    error: Optional[str] = None

def format_price(price: float, country_config: dict) -> str:
    """Format een prijs volgens de landspecifieke instellingen"""
    formatted = f"{price:,.2f}".replace(",", "X").replace(".", country_config["decimal_separator"]).replace("X", country_config["thousands_separator"])
    return formatted

def convert_currency(amount: float, from_currency: str, to_currency: str) -> float:
    """Converteer een bedrag van de ene valuta naar de andere"""
    if from_currency == to_currency:
        return amount
    
    c = CurrencyRates()
    return c.convert(from_currency, to_currency, amount)

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """HTML interface voor de API"""
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "countries": COUNTRIES}
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
    - **country**: Landcode (default: nl)
    
    Returns:
        - De prijs exclusief en inclusief BTW in de juiste valuta
    """
    try:
        # Valideer en haal land configuratie op
        country_code = input.country.lower()
        if country_code not in COUNTRIES:
            raise HTTPException(status_code=400, detail=f"Ongeldig land: {input.country}")
        
        country_config = COUNTRIES[country_code]
        
        scraper = MaterialScraper()
        calculator = PriceCalculator()
        
        # Eerst de velden analyseren
        results = await scraper.analyze_form_fields(input.url)
        
        # Dan de prijs berekenen (altijd eerst in EUR)
        price_excl_vat, price_incl_vat = await calculator.calculate_price(
            url=input.url,
            dimensions=input.dimensions,
            dimension_fields=results['dimension_fields']
        )
        
        # Als beide prijzen 0 zijn, is er waarschijnlijk een fout opgetreden
        if price_excl_vat == 0 and price_incl_vat == 0:
            return PriceResponse(
                price_excl_vat=0,
                price_incl_vat=0,
                currency=country_config["currency"],
                currency_symbol=country_config["currency_symbol"],
                vat_rate=country_config["vat_rate"],
                error=f"Kon geen prijs berekenen voor dikte {input.dimensions['dikte']}mm. Deze variant is niet beschikbaar."
            )
        
        # Converteer prijzen naar de juiste valuta als nodig
        if country_config["currency"] != "EUR":
            price_excl_vat = convert_currency(price_excl_vat, "EUR", country_config["currency"])
            price_incl_vat = convert_currency(price_incl_vat, "EUR", country_config["currency"])
        
        # Pas het BTW percentage aan naar het land-specifieke tarief
        price_excl_vat = price_excl_vat  # Prijs ex BTW blijft gelijk
        price_incl_vat = price_excl_vat * (1 + (country_config["vat_rate"] / 100))  # Nieuwe BTW berekening
        
        return PriceResponse(
            price_excl_vat=price_excl_vat,
            price_incl_vat=price_incl_vat,
            currency=country_config["currency"],
            currency_symbol=country_config["currency_symbol"],
            vat_rate=country_config["vat_rate"]
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