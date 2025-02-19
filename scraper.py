from playwright.async_api import async_playwright
from typing import Dict, Any, Optional
from urllib.parse import urlparse
import logging
from database import SessionLocal
import crud
from config import HEADLESS

class MaterialScraper:
    def __init__(self):
        self.db = SessionLocal()
        
    def __del__(self):
        if hasattr(self, 'db'):
            self.db.close()
            
    def _normalize_domain(self, url: str) -> str:
        """Extract and normalize the domain from a URL"""
        return urlparse(url).netloc.replace('www.', '')
        
    async def analyze_form_fields(self, url: str) -> Dict[str, Any]:
        """Analyze form fields on the page using domain configuration from database"""
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=HEADLESS)
            page = await browser.new_page()
            await page.goto(url)
            
            domain = self._normalize_domain(url)
            config = crud.get_domain_config(self.db, domain)
            if not config:
                raise ValueError(f"No configuration found for domain: {domain}")
                
            config = config.config  # Get the actual config from the SQLAlchemy model
            dimension_fields = {}
            
            # Check each dimension field based on configuration
            for field_type in ['thickness', 'width', 'length']:
                if 'selectors' not in config:
                    continue
                    
                field_config = config['selectors'].get(field_type)
                if not field_config:
                    continue
                    
                if not field_config.get('exists', True):
                    logging.info(f"{field_type} field is configured as non-existent for this domain")
                    continue
                
                try:
                    element = await page.query_selector(field_config['selector'])
                    if element:
                        field_info = {
                            'type': field_config['type'],
                            'selector': field_config['selector']
                        }
                        
                        if field_config['type'] == 'select':
                            options = await self._get_select_options(element)
                            field_info['options'] = options
                            
                        dimension_fields[field_type] = field_info
                        logging.info(f"Found {field_type} field: {field_info}")
                    else:
                        logging.warning(f"Could not find {field_type} element with selector: {field_config['selector']}")
                except Exception as e:
                    logging.error(f"Error analyzing {field_type} field: {str(e)}")
            
            await browser.close()
            return dimension_fields
            
    async def _get_select_options(self, element) -> list:
        """Get options from a select element"""
        options = []
        try:
            option_elements = await element.query_selector_all('option')
            for option in option_elements:
                value = await option.get_attribute('value')
                text = await option.text_content()
                if value and text:
                    options.append({
                        'value': value,
                        'text': text.strip()
                    })
        except Exception as e:
            logging.error(f"Error getting select options: {str(e)}")
        return options

    async def _fill_dimension_field(self, page, field_config: Dict[str, Any], value: float) -> bool:
        """Fill a dimension field based on configuration"""
        if not field_config.get('exists', True):
            return False
            
        try:
            element = await page.query_selector(field_config['selector'])
            if not element:
                logging.error(f"Could not find element with selector: {field_config['selector']}")
                return False
                
            if field_config['type'] == 'select':
                return await self._fill_select_field(element, value)
            else:
                await element.fill(str(value))
                return True
                
        except Exception as e:
            logging.error(f"Error filling dimension field: {str(e)}")
            return False
            
    async def _fill_select_field(self, element, value: float) -> bool:
        """Fill a select field with the closest matching value"""
        try:
            options = await self._get_select_options(element)
            best_match = None
            min_diff = float('inf')
            
            for option in options:
                try:
                    option_value = float(option['value'])
                    diff = abs(option_value - value)
                    if diff < min_diff:
                        min_diff = diff
                        best_match = option['value']
                except ValueError:
                    continue
                    
            if best_match:
                await element.select_option(best_match)
                return True
                
            return False
            
        except Exception as e:
            logging.error(f"Error filling select field: {str(e)}")
            return False 