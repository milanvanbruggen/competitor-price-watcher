from playwright.async_api import async_playwright
from typing import Dict, Any, Optional
from domain_config import DomainConfig
import logging

class MaterialScraper:
    def __init__(self):
        self.domain_config = DomainConfig()
        
    async def analyze_form_fields(self, url: str) -> Dict[str, Any]:
        """Analyze form fields on the page using domain configuration"""
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            await page.goto(url)
            
            config = self.domain_config.get_config(url)
            if not config:
                raise ValueError(f"No configuration found for URL: {url}")
            
            dimension_fields = {}
            
            # Check each dimension field based on configuration
            for field_type in ['thickness', 'width', 'length']:
                field_config = config['selectors'].get(field_type)
                if not field_config:
                    continue
                    
                if not field_config['exists']:
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
        if not field_config['exists']:
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