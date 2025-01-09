# Materiaal Dimensie Analyzer

Een tool voor het automatisch detecteren en analyseren van dimensie velden (dikte, lengte, breedte) op webpagina's.

## Features

- Detecteert automatisch dikte, lengte/hoogte en breedte velden
- Analyseert labels, IDs en andere attributen
- Filtert irrelevante velden
- Toont resultaten in een overzichtelijke interface
- Beschikbaar als web app en API

## Gebruik

1. Open de app
2. Voer een URL in van een productpagina
3. Klik op "Analyseer Dimensie Velden"
4. Bekijk de gevonden velden per categorie

## Lokaal Draaien

```bash
# Installeer dependencies
pip install -r requirements.txt

# Start de web app
streamlit run app.py

# Of start de API
uvicorn api:app --reload
```

## API Gebruik

```python
import requests

response = requests.post(
    "http://localhost:8000/analyze",
    json={"url": "https://voorbeeld.nl/product"}
)
results = response.json()
```

## Deployment

De app kan op verschillende manieren worden gedeployed:

1. **Streamlit Cloud** (aanbevolen)
   - Automatische deployment via GitHub

2. **Docker**
   ```bash
   docker build -t dimensie-analyzer .
   docker run -p 8501:8501 dimensie-analyzer
   ```

## Technologie

- Python 3.11
- Streamlit
- Selenium
- FastAPI
- Chrome WebDriver 