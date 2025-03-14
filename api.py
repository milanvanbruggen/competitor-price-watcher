from fastapi import FastAPI, Request, HTTPException, Depends, Form, Response, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import json
import os
import asyncio
from price_calculator import PriceCalculator
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.orm import Session
from database import get_db, init_db
import crud, schemas
from datetime import datetime
from config_manager import export_configs_to_file, import_configs_from_file
import tempfile
from urllib.parse import unquote

# Initialize database on startup
init_db()

# Increase timeout to 120 seconds and configure host/port
app = FastAPI(
    title="Competitor Price Watcher",
    description="API for watching competitor prices",
    version="1.0.0",
    default_response_class=JSONResponse,
    timeout=120,
    host="0.0.0.0",
    port=8080
)
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

class VersionResponse(BaseModel):
    version: int
    created_at: datetime
    comment: str | None
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
    
    # Group domains by extension
    domains_by_extension = {}
    for domain, config in domain_configs.items():
        # Extract extension (like .nl, .com, .de, etc)
        parts = domain.split('.')
        if len(parts) > 1:
            extension = '.' + parts[-1]
            if extension not in domains_by_extension:
                domains_by_extension[extension] = []
            domains_by_extension[extension].append((domain, config))
        else:
            # For domains without extension
            if 'other' not in domains_by_extension:
                domains_by_extension['other'] = []
            domains_by_extension['other'].append((domain, config))
    
    return templates.TemplateResponse("config.html", {
        "request": request,
        "domain_configs": domain_configs,
        "domains_by_extension": domains_by_extension,
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
    # URL decode the domain
    decoded_domain = unquote(domain)
    
    config = crud.get_domain_config(db, decoded_domain)
    if not config:
        raise HTTPException(status_code=404, detail="Configuration not found")
    return config.config

@app.post("/api/config")
async def save_config(request: ConfigRequest, db: Session = Depends(get_db)):
    try:
        # Save configuration to database
        config = schemas.DomainConfigCreate(domain=request.domain, config=request.config)
        crud.create_domain_config(db, config)
        return JSONResponse({"success": True})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

@app.delete("/api/config/{domain}")
async def delete_config(domain: str, db: Session = Depends(get_db)):
    # URL decode the domain
    decoded_domain = unquote(domain)
    
    if not crud.delete_domain_config(db, decoded_domain):
        raise HTTPException(status_code=404, detail="Configuration not found")
    return {"success": True}

@app.post("/api/config/delete")
async def delete_config_by_body(request: ConfigRequest, db: Session = Depends(get_db)):
    """Delete domain configuration by providing domain in request body instead of URL path"""
    domain = request.domain
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

@app.get("/api/config/{domain}/versions")
async def get_domain_versions(domain: str, db: Session = Depends(get_db)):
    """Haal alle versies op van een domein configuratie"""
    # URL decode the domain
    decoded_domain = unquote(domain)
    
    versions = crud.get_config_versions(db, 'domain', decoded_domain)
    if not versions:
        raise HTTPException(status_code=404, detail="No versions found")
    return [VersionResponse(
        version=v.version,
        created_at=v.created_at,
        comment=v.comment,
        config=v.config
    ) for v in versions]

@app.post("/api/config/{domain}/restore/{version}")
async def restore_domain_version(domain: str, version: int, db: Session = Depends(get_db)):
    """Herstel een specifieke versie van een domein configuratie"""
    # URL decode the domain
    decoded_domain = unquote(domain)
    
    config = crud.restore_config_version(db, 'domain', decoded_domain, version)
    if not config:
        raise HTTPException(status_code=404, detail="Version not found")
    return {"success": True}

@app.get("/api/country/{country}/versions")
async def get_country_versions(country: str, db: Session = Depends(get_db)):
    """Haal alle versies op van een land configuratie"""
    versions = crud.get_config_versions(db, 'country', country)
    if not versions:
        raise HTTPException(status_code=404, detail="No versions found")
    return [VersionResponse(
        version=v.version,
        created_at=v.created_at,
        comment=v.comment,
        config=v.config
    ) for v in versions]

@app.post("/api/country/{country}/restore/{version}")
async def restore_country_version(country: str, version: int, db: Session = Depends(get_db)):
    """Herstel een specifieke versie van een land configuratie"""
    config = crud.restore_config_version(db, 'country', country, version)
    if not config:
        raise HTTPException(status_code=404, detail="Version not found")
    return {"success": True}

@app.get("/api/packages/{package_id}/versions")
async def get_package_versions(package_id: str, db: Session = Depends(get_db)):
    """Haal alle versies op van een pakket configuratie"""
    versions = crud.get_config_versions(db, 'package', package_id)
    if not versions:
        raise HTTPException(status_code=404, detail="No versions found")
    return [VersionResponse(
        version=v.version,
        created_at=v.created_at,
        comment=v.comment,
        config=v.config
    ) for v in versions]

@app.post("/api/packages/{package_id}/restore/{version}")
async def restore_package_version(package_id: str, version: int, db: Session = Depends(get_db)):
    """Herstel een specifieke versie van een pakket configuratie"""
    config = crud.restore_config_version(db, 'package', package_id, version)
    if not config:
        raise HTTPException(status_code=404, detail="Version not found")
    return {"success": True}

@app.post("/api/configs/export")
async def export_configs_endpoint(db: Session = Depends(get_db)):
    """
    Export all configurations to a JSON file and return it.
    """
    try:
        # Create a temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.json') as tmp:
            export_configs_to_file(db, tmp.name)
            return FileResponse(
                tmp.name,
                media_type='application/json',
                filename='configs_backup.json',
                background=None
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/configs/import")
async def import_configs_endpoint(
    file: UploadFile = File(...),
    clear_existing: bool = False,
    db: Session = Depends(get_db)
):
    """
    Import configurations from a JSON file.
    """
    try:
        # Create a temporary file to store the uploaded content
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp.flush()
            
            # Import the configurations
            import_configs_from_file(db, tmp.name, clear_existing)
            
        return {"message": "Configurations imported successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Clean up the temporary file
        if 'tmp' in locals():
            os.unlink(tmp.name) 