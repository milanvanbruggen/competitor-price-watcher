# Materiaal Prijs Calculator

Een tool voor het automatisch berekenen van prijzen op basis van materiaal dimensies op webpagina's.

## Features

- Detecteert automatisch dikte, lengte/hoogte en breedte velden
- Vult dimensies automatisch in op de webpagina
- Berekent prijzen inclusief en exclusief BTW
- Ondersteunt verschillende talen (Nederlands, Engels)
- Beschikbaar als API endpoint

## API Gebruik

```bash
curl -X POST "https://competitor-price-watcher.fly.dev/calculate-price" \
-H "Content-Type: application/json" \
-d '{
    "url": "https://voorbeeld.nl/product",
    "thickness": 2.0,
    "length": 100,
    "width": 50,
    "country": "nl"
}'
```

Response:
```json
{
    "price_excl_vat": 42.54,
    "price_incl_vat": 51.47,
    "currency": "EUR",
    "vat_rate": 21.0,
    "error": null
}
```

## Lokaal Draaien

```bash
# Installeer dependencies
pip install -r requirements.txt

# Start de API
uvicorn api:app --reload --port 8080
```

## Deployment

De app draait op Fly.io met de volgende configuratie:

- 8 CPUs
- 4GB geheugen
- Auto-scaling enabled
- Health checks op /docs endpoint

Deploy commando:
```bash
fly deploy
```

## Technologie

- Python 3.11
- FastAPI
- Selenium
- Chrome WebDriver
- Fly.io voor hosting 