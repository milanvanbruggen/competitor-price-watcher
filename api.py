from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import json
import os
import asyncio
from price_calculator import PriceCalculator
from sse_starlette.sse import EventSourceResponse

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Initialize calculator
calculator = PriceCalculator()

# Load configurations
with open('config/countries.json') as f:
    countries = json.load(f)

with open('config/packages.json') as f:
    package_config = json.load(f)

class SquareMeterPriceRequest(BaseModel):
    url: str
    dikte: float
    lengte: float
    breedte: float
    country: str = 'nl'

class ShippingRequest(BaseModel):
    url: str
    country: str = 'nl'
    package_type: int = 1  # 1-6 for different package sizes
    thickness: float = None  # Optional override for package thickness

class ConfigRequest(BaseModel):
    domain: str
    config: dict

class CountryRequest(BaseModel):
    country: str
    config: dict

class PackageRequest(BaseModel):
    package_id: str
    config: dict

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request, 
        "countries": countries,
        "packages": package_config["packages"]
    })

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
    
    return templates.TemplateResponse("config.html", {
        "request": request,
        "domain_configs": domain_configs,
        "country_configs": countries,
        "package_configs": package_config["packages"]
    })

@app.post("/api/calculate-smp")
async def calculate_square_meter_price(request: SquareMeterPriceRequest):
    try:
        dimensions = {
            'thickness': request.dikte,
            'length': request.lengte,
            'width': request.breedte
        }
        
        price_excl_vat, price_incl_vat = await calculator.calculate_price(
            request.url, 
            dimensions, 
            country=request.country,
            category='square_meter_price'
        )
        
        country_info = countries.get(request.country, countries['nl'])
        
        return {
            "status": "success",
            "status_code": 200,
            "message": "Square meter price calculated successfully",
            "data": {
                "price_excl_vat": round(price_excl_vat, 2),
                "price_incl_vat": round(price_incl_vat, 2),
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

@app.post("/api/calculate-shipping")
async def calculate_shipping(request: ShippingRequest):
    """Calculate shipping costs"""
    try:
        package_id = str(request.package_type)
        if package_id not in package_config["packages"]:
            raise ValueError(f"Invalid package type: {request.package_type}. Must be between 1 and {len(package_config['packages'])}.")

        package = package_config["packages"][package_id]
        dimensions = {
            'package_type': package_id,  # Add package_type to dimensions
            'thickness': request.thickness if request.thickness is not None else package['thickness'],  # Allow thickness override
            'length': package['length'],
            'width': package['width'],
            'quantity': package['quantity']
        }
        
        price_excl_vat, price_incl_vat = await calculator.calculate_price(
            request.url, 
            dimensions, 
            country=request.country,
            category='shipping'
        )
        
        country_info = countries.get(request.country, countries['nl'])
        
        return {
            "status": "success",
            "status_code": 200,
            "message": "Shipping costs calculated successfully",
            "data": {
                "price_excl_vat": round(price_excl_vat, 2),
                "price_incl_vat": round(price_incl_vat, 2),
                "currency": country_info['currency'],
                "currency_symbol": country_info['currency_symbol'],
                "vat_rate": country_info['vat_rate'],
                "package_info": {
                    "type": request.package_type,
                    "name": package['name'],
                    "description": package['description'],
                    "quantity": package['quantity'],
                    "dimensions": f"{package['length']}x{package['width']} mm",
                    "thickness": dimensions['thickness'],  # Use the actual thickness being used
                    "display": package['display']
                }
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

@app.get("/api/packages")
async def get_packages():
    """Get all package configurations"""
    return package_config

@app.get("/api/packages/{package_id}")
async def get_package(package_id: str):
    """Get a specific package configuration"""
    if package_id not in package_config["packages"]:
        raise HTTPException(status_code=404, detail="Package configuration not found")
    return package_config["packages"][package_id]

@app.post("/api/packages")
async def save_package(request: PackageRequest):
    """Save or update a package configuration"""
    try:
        package_config["packages"][request.package_id] = request.config
        with open('config/packages.json', 'w') as f:
            json.dump(package_config, f, indent=4)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.delete("/api/packages/{package_id}")
async def delete_package(package_id: str):
    """Delete a package configuration"""
    if package_id not in package_config["packages"]:
        raise HTTPException(status_code=404, detail="Package configuration not found")
    
    del package_config["packages"][package_id]
    with open('config/packages.json', 'w') as f:
        json.dump(package_config, f, indent=4)
    return {"success": True}

@app.get("/docs", response_class=HTMLResponse)
async def docs_page(request: Request):
    return templates.TemplateResponse("docs.html", {"request": request})

async def price_status_stream(request: Request):
    """SSE endpoint voor real-time status updates"""
    async def event_generator():
        while True:
            if await request.is_disconnected():
                break
            
            if PriceCalculator.latest_status:
                yield {
                    "event": "status",
                    "data": json.dumps(PriceCalculator.latest_status)
                }
                PriceCalculator.latest_status = None
            
            await asyncio.sleep(0.1)

    return EventSourceResponse(event_generator())

app.add_route("/api/status-stream", price_status_stream) 