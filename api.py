from fastapi import FastAPI, HTTPException
from scraper import MaterialScraper
from pydantic import BaseModel
import uvicorn

app = FastAPI(
    title="Materiaal Dimensie Analyzer API",
    description="API voor het analyseren van dimensie velden op webpagina's",
    version="1.0.0"
)

class ScrapeRequest(BaseModel):
    url: str

@app.post("/analyze")
async def analyze_url(request: ScrapeRequest):
    try:
        scraper = MaterialScraper()
        results = scraper.analyze_form_fields(request.url)
        
        if not results:
            raise HTTPException(status_code=404, detail="Geen dimensie velden gevonden")
            
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000) 