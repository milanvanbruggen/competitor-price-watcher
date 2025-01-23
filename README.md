# Competitor Price Scraper

A web application for scraping and comparing prices from various plastic/plexi suppliers across Europe. The application supports custom configurations for different domains and handles various types of input methods and price calculations.

## Features

- Price calculation based on dimensions (thickness, length, width)
- Support for multiple countries with different VAT rates and currencies
- Configurable scraping steps for each domain
- Interactive configuration management interface
- Comprehensive API documentation

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/competitor-price-watcher.git
cd competitor-price-watcher
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Install Playwright browsers:
```bash
playwright install
```

## Usage

1. Start the application:
```bash
uvicorn api:app --reload --port 8080
```

2. Open your browser and navigate to:
- Home page: http://localhost:8080
- Configuration page: http://localhost:8080/config
- Documentation: http://localhost:8080/docs

## API Usage

The application provides a REST API for price calculations. Example request:

```bash
curl -X POST http://localhost:8080/api/calculate \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com/product",
    "dikte": 3.0,
    "lengte": 1000.0,
    "breedte": 500.0,
    "country": "nl"
  }'
```

For detailed API documentation and configuration options, visit the documentation page in the application.

## Configuration

The application uses two types of configurations:

1. Domain Configurations (`config/domains/*.json`):
   - Define scraping steps for each website
   - Support various input types (select, input, click)
   - Handle custom dropdowns and dynamic content

2. Country Configurations (`config/countries.json`):
   - Define VAT rates per country
   - Set currency and formatting preferences
   - Configure regional settings

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details. 