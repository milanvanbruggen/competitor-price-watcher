from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import json
import os
from price_calculator import PriceCalculator

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Initialize calculator
calculator = PriceCalculator()

# Load countries configuration
with open('config/countries.json') as f:
    countries = json.load(f)

class PriceRequest(BaseModel):
    url: str
    dikte: float
    lengte: float
    breedte: float
    country: str = 'nl'

class ConfigRequest(BaseModel):
    domain: str
    config: dict

class CountryRequest(BaseModel):
    country: str
    config: dict

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "countries": countries})

@app.get("/config")
async def config_page(request: Request):
    # Load domain configurations
    domain_configs = {}
    domain_config_dir = os.path.join(os.path.dirname(__file__), 'config', 'domains')
    for filename in os.listdir(domain_config_dir):
        if filename.endswith('.json'):
            with open(os.path.join(domain_config_dir, filename)) as f:
                config = json.load(f)
                domain_configs[config['domain']] = config
    
    # Load country configurations
    with open(os.path.join(os.path.dirname(__file__), 'config', 'countries.json')) as f:
        country_configs = json.load(f)
    
    return templates.TemplateResponse("config.html", {
        "request": request,
        "domain_configs": domain_configs,
        "country_configs": country_configs
    })

@app.post("/api/calculate")
async def calculate_price(request: PriceRequest):
    try:
        dimensions = {
            'thickness': request.dikte,
            'length': request.lengte,
            'width': request.breedte
        }
        
        price_excl_vat, price_incl_vat = await calculator.calculate_price(request.url, dimensions, country=request.country)
        
        country_info = countries.get(request.country, countries['nl'])
        
        return {
            "status": "success",
            "status_code": 200,
            "message": "Price calculated successfully",
            "data": {
                "price_excl_vat": price_excl_vat,
                "price_incl_vat": price_incl_vat,
                "currency": country_info['currency'],
                "currency_symbol": country_info['currency_symbol'],
                "vat_rate": country_info['vat_rate']
            }
        }
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail={
                "status": "error",
                "status_code": 400,
                "message": str(e),
                "error_type": "ValueError"
            }
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "status_code": 500,
                "message": str(e),
                "error_type": type(e).__name__
            }
        )

@app.get("/api/config/{domain}")
async def get_config(domain: str):
    config_path = os.path.join('config', 'domains', f'{domain}.json')
    if not os.path.exists(config_path):
        raise HTTPException(status_code=404, detail="Configuration not found")
    
    with open(config_path) as f:
        return json.load(f)

@app.post("/api/config")
async def save_config(request: ConfigRequest):
    try:
        config_path = os.path.join('config', 'domains', f'{request.domain}.json')
        with open(config_path, 'w') as f:
            json.dump(request.config, f, indent=4)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.delete("/api/config/{domain}")
async def delete_config(domain: str):
    config_path = os.path.join('config', 'domains', f'{domain}.json')
    if not os.path.exists(config_path):
        raise HTTPException(status_code=404, detail="Configuration not found")
    
    os.remove(config_path)
    return {"success": True}

@app.get("/api/country/{country}")
async def get_country_config(country: str):
    config_path = os.path.join('config', 'countries.json')
    if not os.path.exists(config_path):
        raise HTTPException(status_code=404, detail="Country configurations not found")
    
    with open(config_path) as f:
        countries = json.load(f)
        if country not in countries:
            raise HTTPException(status_code=404, detail="Country not found")
        return countries[country]

@app.post("/api/country")
async def save_country_config(request: CountryRequest):
    try:
        config_path = os.path.join('config', 'countries.json')
        with open(config_path) as f:
            countries = json.load(f)
        
        countries[request.country] = request.config
        
        with open(config_path, 'w') as f:
            json.dump(countries, f, indent=4)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.delete("/api/country/{country}")
async def delete_country_config(country: str):
    config_path = os.path.join('config', 'countries.json')
    if not os.path.exists(config_path):
        raise HTTPException(status_code=404, detail="Country configurations not found")
    
    with open(config_path) as f:
        countries = json.load(f)
        if country not in countries:
            raise HTTPException(status_code=404, detail="Country not found")
        del countries[country]
    
    with open(config_path, 'w') as f:
        json.dump(countries, f, indent=4)
    return {"success": True}

@app.get("/docs", response_class=HTMLResponse)
async def docs_page(request: Request):
    return templates.TemplateResponse("docs.html", {"request": request}) 