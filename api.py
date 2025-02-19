from fastapi import FastAPI, Request, HTTPException, Depends, Form, Response
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import json
import os
import asyncio
from price_calculator import PriceCalculator
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.orm import Session
from database import get_db
import crud, schemas

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Initialize calculator
calculator = PriceCalculator()

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
async def read_root(request: Request, db: Session = Depends(get_db)):
    # Get configurations from database
    countries = {config.country_code: config.config for config in crud.get_country_configs(db)}
    packages = {config.package_id: config.config for config in crud.get_package_configs(db)}
    
    return templates.TemplateResponse("index.html", {
        "request": request, 
        "countries": countries,
        "packages": packages
    })

@app.get("/step-editor")
async def step_editor(request: Request, db: Session = Depends(get_db)):
    # Get configurations from database
    domain_configs = {config.domain: config.config for config in crud.get_domain_configs(db)}
    return templates.TemplateResponse("step_editor.html", {
        "request": request,
        "domain_configs": domain_configs
    })

@app.get("/config")
async def config_page(request: Request, db: Session = Depends(get_db)):
    # Get configurations from database
    domain_configs = {config.domain: config.config for config in crud.get_domain_configs(db)}
    country_configs = {config.country_code: config.config for config in crud.get_country_configs(db)}
    package_configs = {config.package_id: config.config for config in crud.get_package_configs(db)}
    
    return templates.TemplateResponse("config.html", {
        "request": request,
        "domain_configs": domain_configs,
        "country_configs": country_configs,
        "package_configs": package_configs
    })

@app.post("/api/calculate-smp")
async def calculate_square_meter_price(request: SquareMeterPriceRequest, db: Session = Depends(get_db)):
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
        
        country_config = crud.get_country_config(db, request.country)
        if not country_config:
            country_config = crud.get_country_config(db, 'nl')  # Fallback to NL
        country_info = country_config.config
        
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
async def calculate_shipping(request: ShippingRequest, db: Session = Depends(get_db)):
    """Calculate shipping costs"""
    try:
        package_id = str(request.package_type)
        package_config = crud.get_package_config(db, package_id)
        if not package_config:
            raise ValueError(f"Invalid package type: {request.package_type}. Must be between 1 and 6.")

        package = package_config.config
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
        
        country_config = crud.get_country_config(db, request.country)
        if not country_config:
            country_config = crud.get_country_config(db, 'nl')  # Fallback to NL
        country_info = country_config.config
        
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
async def get_config(domain: str, db: Session = Depends(get_db)):
    config = crud.get_domain_config(db, domain)
    if not config:
        raise HTTPException(status_code=404, detail="Configuration not found")
    return config.config

@app.post("/api/config")
async def save_config(request: ConfigRequest, db: Session = Depends(get_db)):
    try:
        # Save configuration to database
        config = schemas.DomainConfigCreate(domain=request.domain, config=request.config)
        crud.create_domain_config(db, config)
        
        # Also save configuration to file for backward compatibility
        config_dir = os.path.join(os.path.dirname(__file__), 'configs')
        os.makedirs(config_dir, exist_ok=True)
        
        config_path = os.path.join(config_dir, f"{request.domain}.json")
        with open(config_path, 'w') as f:
            json.dump(request.config, f, indent=2)
            
        return JSONResponse({"success": True})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

@app.delete("/api/config/{domain}")
async def delete_config(domain: str, db: Session = Depends(get_db)):
    if not crud.delete_domain_config(db, domain):
        raise HTTPException(status_code=404, detail="Configuration not found")
    return {"success": True}

@app.get("/api/country/{country}")
async def get_country_config(country: str, db: Session = Depends(get_db)):
    config = crud.get_country_config(db, country)
    if not config:
        raise HTTPException(status_code=404, detail="Country configuration not found")
    return config.config

@app.post("/api/country")
async def save_country_config(request: CountryRequest, db: Session = Depends(get_db)):
    try:
        config = schemas.CountryConfigCreate(country_code=request.country, config=request.config)
        crud.create_country_config(db, config)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.delete("/api/country/{country}")
async def delete_country_config(country: str, db: Session = Depends(get_db)):
    if not crud.delete_country_config(db, country):
        raise HTTPException(status_code=404, detail="Country configuration not found")
    return {"success": True}

@app.get("/api/packages")
async def get_packages(db: Session = Depends(get_db)):
    """Get all package configurations"""
    packages = {config.package_id: config.config for config in crud.get_package_configs(db)}
    return {"packages": packages}

@app.get("/api/packages/{package_id}")
async def get_package(package_id: str, db: Session = Depends(get_db)):
    """Get a specific package configuration"""
    config = crud.get_package_config(db, package_id)
    if not config:
        raise HTTPException(status_code=404, detail="Package configuration not found")
    return config.config

@app.post("/api/packages")
async def save_package(request: PackageRequest, db: Session = Depends(get_db)):
    """Save or update a package configuration"""
    try:
        config = schemas.PackageConfigCreate(package_id=request.package_id, config=request.config)
        crud.create_package_config(db, config)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.delete("/api/packages/{package_id}")
async def delete_package(package_id: str, db: Session = Depends(get_db)):
    """Delete a package configuration"""
    if not crud.delete_package_config(db, package_id):
        raise HTTPException(status_code=404, detail="Package configuration not found")
    return {"success": True}

@app.get("/docs", response_class=HTMLResponse)
async def docs_page(request: Request):
    return templates.TemplateResponse("docs.html", {"request": request})

@app.get("/config-docs", response_class=HTMLResponse)
async def config_docs(request: Request):
    return templates.TemplateResponse("config_docs.html", {"request": request})

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