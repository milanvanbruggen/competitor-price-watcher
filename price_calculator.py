from playwright.async_api import async_playwright, Page, expect
from typing import Dict, Any, Optional, Tuple, List
from domain_config import DomainConfig
import logging
import re
import os
import json
import asyncio
from urllib.parse import urlparse

logging.basicConfig(level=logging.INFO)

class PriceCalculator:
    """Calculate prices based on dimensions for different domains"""
    
    def __init__(self):
        self.configs = {}
        self._load_configs()

    def _load_configs(self):
        config_dir = os.path.join(os.path.dirname(__file__), 'config', 'domains')
        for filename in os.listdir(config_dir):
            if filename.endswith('.json'):
                with open(os.path.join(config_dir, filename)) as f:
                    config = json.load(f)
                    self.configs[config['domain']] = config

    async def calculate_price(self, url: str, dimensions: Dict[str, float], country: str = 'nl', category: str = 'square_meter_price') -> Tuple[float, float]:
        domain = urlparse(url).netloc.replace('www.', '')
        if domain not in self.configs:
            raise ValueError(f"No configuration found for domain {domain}")

        logging.info(f"Calculating price for {url}")
        logging.info(f"Original dimensions: {dimensions}")
        
        config = self.configs[domain]
        if 'categories' not in config or category not in config['categories']:
            raise ValueError(f"No configuration found for category {category} on domain {domain}")
            
        category_config = config['categories'][category]
        logging.info(f"Using config: {category_config}")
        
        # Load package configuration if this is a shipping calculation
        if category == 'shipping':
            with open('config/packages.json') as f:
                packages = json.load(f)
            package_type = str(dimensions.get('package_type', '1'))
            if package_type not in packages['packages']:
                raise ValueError(f"Invalid package type: {package_type}")
            
            # Log the package configuration before merging
            package = packages['packages'][package_type]
            logging.info(f"Package configuration from packages.json: {package}")
            
            # Merge dimensions, letting package dimensions take precedence
            original_dimensions = dimensions.copy()
            dimensions = {
                **original_dimensions,  # Start with original dimensions
                'thickness': package['thickness'],  # Override with package dimensions
                'width': package['width'],
                'length': package['length'],
                'quantity': package['quantity']
            }
            logging.info(f"Final dimensions after merging: {dimensions}")
            
            # Double check the thickness value
            logging.info(f"Thickness value being used: {dimensions['thickness']}")
            if dimensions['thickness'] != package['thickness']:
                logging.warning(f"Thickness mismatch! Package thickness: {package['thickness']}, Final thickness: {dimensions['thickness']}")
        
        # Determine if we should run in headless mode based on environment
        is_production = os.getenv('FLY_APP_NAME') is not None
        headless = is_production
        logging.info(f"Running in {'headless' if headless else 'headed'} mode")
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)
            context = await browser.new_context(viewport={'width': 1280, 'height': 1024})
            page = await context.new_page()
            
            try:
                logging.info(f"Navigating to {url}")
                await page.goto(url)
                
                # Wait for different load states to ensure complete loading
                logging.info("Waiting for page to be completely loaded...")
                await page.wait_for_load_state("domcontentloaded")
                await page.wait_for_load_state("load")
                await page.wait_for_load_state("networkidle")
                
                try:
                    await page.wait_for_function("document.readyState === 'complete'")
                    logging.info("Page fully loaded and JavaScript executed")
                except Exception as e:
                    logging.warning(f"Could not verify JavaScript completion: {str(e)}")
                
                await asyncio.sleep(1)

                for step in category_config['steps']:
                    logging.info(f"Executing step: {step['type']}")
                    
                    if step['type'] == 'select':
                        await self._handle_select(page, step, dimensions)
                    elif step['type'] == 'input':
                        await self._handle_input(page, step, dimensions)
                    elif step['type'] == 'click':
                        await self._handle_click(page, step)
                    elif step['type'] == 'wait':
                        await self._handle_wait(step)
                    elif step['type'] == 'read_price':
                        price = await self._handle_read_price(page, step)
                        
                        # Load VAT rates from configuration
                        with open('config/countries.json') as f:
                            countries = json.load(f)
                        vat_rate = countries.get(country, countries['nl'])['vat_rate'] / 100
                        
                        if step.get('includes_vat', False):
                            price_incl_vat = price
                            price_excl_vat = price / (1 + vat_rate)
                        else:
                            price_excl_vat = price
                            price_incl_vat = price * (1 + vat_rate)
                            
                        return price_excl_vat, price_incl_vat

            except Exception as e:
                logging.error(f"Error calculating price: {str(e)}")
                raise
            finally:
                await asyncio.sleep(2)
                await browser.close()

    def _convert_value(self, value: float, unit: str) -> float:
        """Convert a value from millimeters to the target unit"""
        # Convert value to float if it's an integer
        value = float(value)
        
        if unit == 'cm':
            return value / 10
        return value  # Default is mm

    async def _handle_select(self, page, step, dimensions):
        value = step['value']
        
        # Handle index-based selection
        if step.get('select_by') == 'index':
            try:
                index = int(value)
                element = await page.wait_for_selector(step['selector'])
                options = await element.evaluate('''(select) => {
                    return Array.from(select.options).map(option => ({
                        value: option.value
                    }));
                }''')
                
                if 0 <= index < len(options):
                    await element.select_option(index=index)
                    await element.evaluate('(el) => el.dispatchEvent(new Event("change", { bubbles: true }))')
                    await asyncio.sleep(1)
                    return
                else:
                    raise ValueError(f"Index {index} out of range for select options")
            except Exception as e:
                raise ValueError(f"Error in index-based selection: {str(e)}")
        
        # Handle regular value-based selection
        for key in ['thickness', 'width', 'length']:
            if f"{{{key}}}" in value:
                if key in dimensions:
                    converted_value = self._convert_value(dimensions[key], step.get('unit', 'mm'))
                    # Convert to integer if it's a whole number
                    if isinstance(converted_value, float) and converted_value.is_integer():
                        converted_value = int(converted_value)
                    value = value.replace(f"{{{key}}}", str(converted_value))
                    logging.info(f"Converted {key} value to: {converted_value}")
                else:
                    logging.warning(f"Dimension {key} not found in dimensions dict")
        
        logging.info(f"Handling select: {step['selector']} with target value {value}")
        
        element = await page.wait_for_selector(step['selector'])
        
        # Check if this is a custom dropdown with option_container
        if 'option_container' in step:
            logging.info("Handling custom dropdown")
            await element.click()
            await asyncio.sleep(1)
            
            option_container = await page.wait_for_selector(step['option_container'])
            option_selector = step['option_selector'].replace('{value}', str(value))
            logging.info(f"Looking for option with selector: {option_selector}")
            
            try:
                option = await option_container.wait_for_selector(option_selector)
                await option.click()
                await asyncio.sleep(1)
                return
            except Exception as e:
                logging.error(f"Could not find option for value {value}: {str(e)}")
                # If exact match fails, try to find closest match
                options = await option_container.query_selector_all('li')
                best_match = None
                smallest_diff = float('inf')
                target_value = float(value)
                
                for opt in options:
                    try:
                        opt_value = await opt.get_attribute('data-value')
                        if opt_value:
                            opt_value = float(opt_value)
                            diff = abs(opt_value - target_value)
                            logging.info(f"Comparing option value {opt_value} with target {target_value} (diff: {diff})")
                            if diff < smallest_diff:
                                smallest_diff = diff
                                best_match = opt
                    except Exception:
                        continue
                
                if best_match and smallest_diff < 0.01:  # Stricter matching - was 0.1
                    await best_match.click()
                    await asyncio.sleep(1)
                    return
                else:
                    raise ValueError(f"Could not find matching option for value {value}mm (closest diff was {smallest_diff})")
        
        # Standard select element handling
        logging.info("Handling standard select element")
        
        # Get all available options without clicking first
        options = await element.evaluate('''(select) => {
            return Array.from(select.options).map(option => ({
                value: option.value,
                text: option.text.trim()
            }));
        }''')
        
        logging.info(f"Available options: {options}")
        
        # Find best matching option
        target_value = float(value)
        best_match = None
        smallest_diff = float('inf')
        
        for option in options:
            try:
                # Try to find numeric value in option text
                numeric_match = re.search(r'(\d+(?:\.\d+)?)(?:\s*mm)?', option['text'].lower())
                if numeric_match:
                    option_value = float(numeric_match.group(1))
                    
                    diff = abs(option_value - target_value)
                    logging.info(f"Comparing option {option['text']} ({option_value}mm) vs target {target_value}mm (diff: {diff})")
                    
                    if diff < smallest_diff:
                        smallest_diff = diff
                        best_match = option
                        logging.info(f"New best match: {option['text']} (value: {option['value']}, diff: {diff})")
            except Exception as e:
                logging.error(f"Error processing option {option['text']}: {str(e)}")
                continue
        
        if best_match is not None and smallest_diff < 0.01:  # Stricter matching - was 0.1
            logging.info(f"Selected best match: {best_match['text']} with diff {smallest_diff}")
            # Select the option without clicking first
            await element.select_option(value=best_match['value'])
            # Trigger only the change event
            await element.evaluate('(el) => el.dispatchEvent(new Event("change", { bubbles: true }))')
            await asyncio.sleep(1)
        else:
            available_options = ", ".join(f"{opt['text']} ({opt['value']})" for opt in options)
            raise ValueError(f"Could not find exact match for thickness {value}mm. Closest diff was {smallest_diff}. Available options: {available_options}")

    async def _handle_input(self, page, step, dimensions):
        value = step['value']
        for key in ['thickness', 'width', 'length', 'quantity']:
            if f"{{{key}}}" in value:
                if key in dimensions:
                    converted_value = self._convert_value(dimensions[key], step.get('unit', 'mm'))
                    # Convert to integer if it's a whole number
                    if converted_value.is_integer():
                        converted_value = int(converted_value)
                    value = value.replace(f"{{{key}}}", str(converted_value))
                else:
                    logging.warning(f"Dimension {key} not found in dimensions dict")

        logging.info(f"Handling input: {step['selector']} with value {value}")
        
        element = await page.wait_for_selector(step['selector'])
        
        # First clear the input field
        await element.evaluate('(el) => { el.value = ""; }')
        await asyncio.sleep(0.5)
        await element.press('Backspace')
        
        # Then fill the new value
        await element.type(str(value))
        
        # Dispatch all events at once
        await element.evaluate('''(el) => {
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            el.dispatchEvent(new Event('blur', { bubbles: true }));
        }''')
        
        await asyncio.sleep(0.5)  # Single wait after all events

    async def _handle_click(self, page, step):
        logging.info(f"Handling click: {step['selector']}")
        element = await page.wait_for_selector(step['selector'])
        await element.click()
        await asyncio.sleep(0.5)

    async def _handle_wait(self, step):
        duration = step['duration'] / 1000
        logging.info(f"Waiting for {duration} seconds")
        await asyncio.sleep(duration)

    async def _handle_read_price(self, page, step):
        logging.info(f"Reading price with selector: {step['selector']}")
        
        try:
            if step['selector'].startswith('xpath='):
                element = await page.wait_for_selector(f"{step['selector']}")
            else:
                element = await page.wait_for_selector(step['selector'])
                
            if not element and 'default_value' in step:
                logging.info(f"Element not found, returning default value: {step['default_value']}")
                return step['default_value']
                
            text = await element.text_content()
            logging.info(f"Found price text: {text}")
            
            # Clean the price text:
            # 1. Replace comma with dot for decimal
            # 2. Remove any trailing dots
            # 3. Keep only digits and one decimal point
            cleaned_text = text.replace(',', '.').rstrip('.')
            price_str = ''.join(char for char in cleaned_text if char.isdigit() or char == '.')
            
            # If we have multiple dots, keep only the first one
            if price_str.count('.') > 1:
                parts = price_str.split('.')
                price_str = parts[0] + '.' + ''.join(parts[1:])
            
            logging.info(f"Cleaned price text: {price_str}")
            price = float(price_str)
            logging.info(f"Extracted price: {price}")
            
            if 'calculation' in step:
                if 'divide_by' in step['calculation']:
                    price = price / step['calculation']['divide_by']
                    logging.info(f"Price after division: {price}")
                if 'add' in step['calculation']:
                    price = price + step['calculation']['add']
                    logging.info(f"Price after addition: {price}")
                    
            return price
            
        except Exception as e:
            logging.error(f"Error reading price: {str(e)}")
            if 'default_value' in step:
                logging.info(f"Returning default value: {step['default_value']}")
                return step['default_value']
            raise ValueError(f"Could not read price: {str(e)}")

    def _convert_dimensions(self, dimensions: Dict[str, float], units: Dict[str, str]) -> Dict[str, float]:
        """Convert dimensions to the units required by the domain"""
        converted = {}
        
        # Handle thickness separately
        if 'thickness' in dimensions:
            if units.get('thickness') == 'cm':
                converted['thickness'] = dimensions['thickness'] / 10  # mm to cm
            else:
                converted['thickness'] = dimensions['thickness']  # keep as mm
        
        # Handle length and width
        dimension_unit = units.get('dimensions', 'mm')
        for field in ['length', 'width']:
            if field in dimensions:
                if dimension_unit == 'cm':
                    converted[field] = dimensions[field] / 10  # mm to cm
                else:
                    converted[field] = dimensions[field]  # keep as mm
                
        return converted

    def _extract_price(self, price_text: str) -> float:
        """Extract numeric price from text"""
        try:
            # Remove currency symbols and whitespace
            cleaned = price_text.replace('€', '').replace(',', '.').strip()
            # Extract first number found
            match = re.search(r'\d+\.?\d*', cleaned)
            if match:
                return float(match.group())
        except Exception as e:
            logging.error(f"Error extracting price from {price_text}: {str(e)}")
        return 0.0

    async def _fill_select_field(self, page: Page, selector: str, value: float) -> None:
        logging.info(f"\nZoeken naar thickness veld met selector: {selector}")
        
        # Check if this is a custom dropdown for voskunststoffen.nl
        if selector.startswith('#partControlDropDownThickness'):
            try:
                # First click the trigger element to open the dropdown
                trigger = await page.wait_for_selector(selector)
                if not trigger:
                    raise ValueError(f"Kon geen dropdown trigger vinden met selector: {selector}")
                
                await trigger.click()
                await page.wait_for_timeout(500)  # Wait for dropdown to open
                
                # Now find the option in the popper container
                option_selector = f"li[data-value='{value}']"
                option = await page.wait_for_selector(option_selector, state="visible", timeout=1000)
                if not option:
                    raise ValueError(f"Kon geen optie vinden voor waarde {value}mm")
                
                await option.click()
                await page.wait_for_timeout(500)  # Wait for selection to process
                
                logging.info(f"Custom dropdown: waarde {value}mm geselecteerd")
                return
                
            except Exception as e:
                raise ValueError(f"Error bij custom dropdown selectie: {str(e)}")
        
        # Regular select field handling
        element = await page.wait_for_selector(selector)
        if not element:
            raise ValueError(f"Kon geen element vinden met selector: {selector}")
            
        logging.info(f"Select veld gevonden, waarde invullen: {value}")
        
        # Get all available options
        options = await element.evaluate('''(select) => {
            return Array.from(select.options).map(option => ({
                value: option.value,
                text: option.text.trim()
            }));
        }''')
        
        logging.info(f"Beschikbare opties: {options}")
        
        # Try to find a matching option
        match_found = False
        for option in options:
            option_text = option['text']
            logging.info(f"Controleren optie: '{option_text}'")
            
            # Extract number from option text (e.g. "3mm" -> 3.0)
            number_match = re.search(r'(\d+(?:\.\d+)?)', option_text)
            if number_match:
                option_value = float(number_match.group(1))
                if abs(option_value - value) < 0.1:  # Allow small difference for float comparison
                    match_found = True
                    logging.info(f"Match gevonden! Selecteren van optie: {option_text}")
                    await element.select_option(value=option['value'])
                    await page.evaluate('(el) => { el.dispatchEvent(new Event("change")); }', element)
                    await page.wait_for_timeout(1000)
                    break
                    
        if not match_found:
            available_thicknesses = ", ".join(opt['text'] for opt in options)
            raise ValueError(f"Kon geen passende optie vinden voor waarde {value}mm in select veld. Beschikbare diktes: {available_thicknesses}")

    async def _collect_price_elements(self, page) -> List[Dict]:
        """Verzamelt alle elementen met prijzen"""
        prices = []
        
        # Zoek alleen in relevante tekst elementen
        selectors = [
            'p', 'span', 'div', 'td', 'th', 'label',
            '[class*="price"]', '[class*="prijs"]',
            '[id*="price"]', '[id*="prijs"]',
            '[class*="total"]', '[class*="totaal"]',
            '[class*="amount"]', '[class*="bedrag"]',
            '[class*="cost"]', '[class*="kosten"]',
            '.woocommerce-Price-amount',
            '.product-price',
            '.price-wrapper'
        ]
        
        for selector in selectors:
            try:
                elements = await page.query_selector_all(selector)
                for element in elements:
                    try:
                        text = await element.text_content()
                        if not text:
                            continue
                            
                        text = text.lower().strip()
                        
                        # Zoek naar prijzen met verschillende patronen
                        price_patterns = [
                            r'€\s*(\d+(?:[.,]\d{2})?)',  # €20,00
                            r'(\d+(?:[.,]\d{2})?)\s*€',  # 20,00€
                            r'eur\s*(\d+(?:[.,]\d{2})?)',  # EUR 20,00
                            r'(\d+(?:[.,]\d{2})?)\s*eur'   # 20,00 EUR
                        ]
                        
                        for pattern in price_patterns:
                            price_matches = re.findall(pattern, text)
                            if price_matches:
                                # Neem de laatste match (vaak de meest relevante bij meerdere prijzen)
                                price_str = price_matches[-1]
                                price = float(price_str.replace(',', '.'))
                                
                                # Valideer dat de prijs realistisch is
                                if 0.01 <= price <= 10000.0:  # Verruim de prijsrange
                                    # Check BTW indicatie
                                    is_incl = any(term in text for term in ['incl', 'inclusief', 'inc.', 'incl.'])
                                    
                                    # Genereer een unieke identifier voor het element
                                    element_id = await element.evaluate("""el => {
                                        if (el.id) return el.id;
                                        if (el.className) return el.className;
                                        return el.tagName + '_' + (el.textContent || '').substring(0, 20);
                                    }""")
                                    
                                    prices.append({
                                        'element': element,
                                        'element_id': element_id,
                                        'text': text,
                                        'price': price,
                                        'is_incl': is_incl,
                                        'pattern_used': pattern
                                    })
                                    print(f"Gevonden prijs in element {element_id}: €{price:.2f} ({'incl' if is_incl else 'excl'} BTW)")
                                    break  # Stop na eerste geldige prijs in dit element
                                    
                    except Exception as e:
                        print(f"Error bij element verwerking: {str(e)}")
                        continue
            except Exception as e:
                print(f"Error bij selector {selector}: {str(e)}")
                continue
                
        return prices

    def _find_changed_prices(self, initial_prices: List[Dict], updated_prices: List[Dict]) -> List[Dict]:
        """Vindt prijzen die zijn veranderd na het invullen van dimensies"""
        changed = []
        
        # Maak maps voor snelle vergelijking
        initial_by_id = {p['element_id']: p for p in initial_prices if 'element_id' in p}
        initial_by_text = {p['text']: p for p in initial_prices}
        
        print("\nVergelijken van prijzen:")
        print(f"Initiële prijzen: {len(initial_prices)}")
        print(f"Nieuwe prijzen: {len(updated_prices)}")
        
        # Check welke prijzen zijn veranderd of nieuw zijn
        for price_info in updated_prices:
            element_id = price_info.get('element_id')
            text = price_info['text']
            price = price_info['price']
            
            # Probeer eerst te matchen op element ID
            if element_id and element_id in initial_by_id:
                initial_price = initial_by_id[element_id]['price']
                if abs(initial_price - price) > 0.01:  # Gebruik kleine marge voor float vergelijking
                    print(f"\nPrijsverandering gedetecteerd in element {element_id}:")
                    print(f"- Oude prijs: €{initial_price:.2f}")
                    print(f"- Nieuwe prijs: €{price:.2f}")
                    changed.append(price_info)
            # Als geen ID match, probeer op tekst
            elif text in initial_by_text:
                initial_price = initial_by_text[text]['price']
                if abs(initial_price - price) > 0.01:
                    print(f"\nPrijsverandering gedetecteerd in tekst '{text}':")
                    print(f"- Oude prijs: €{initial_price:.2f}")
                    print(f"- Nieuwe prijs: €{price:.2f}")
                    changed.append(price_info)
            # Volledig nieuwe prijs
            else:
                # Valideer dat het echt een prijs is
                if any(indicator in text.lower() for indicator in ['€', 'eur', 'prijs', 'price', 'total', 'bedrag']):
                    print(f"\nNieuwe prijs gevonden: €{price:.2f}")
                    print(f"In element: {element_id if element_id else text}")
                    changed.append(price_info)
        
        if not changed:
            print("\nGeen prijsveranderingen gedetecteerd")
            # Als er geen veranderingen zijn, kijk naar nieuwe prijzen die mogelijk relevant zijn
            for price_info in updated_prices:
                if 5.0 <= price_info['price'] <= 500.0:  # Typische m² prijsrange
                    if any(term in price_info['text'].lower() for term in ['totaal', 'total', 'prijs', 'price']):
                        print(f"\nMogelijk relevante prijs gevonden: €{price_info['price']:.2f}")
                        print(f"In element: {price_info.get('element_id', price_info['text'])}")
                        changed.append(price_info)
        
        return changed

    async def _find_nearest_element(self, page, search_terms: List[str], element_type: str = 'text') -> Optional[Dict]:
        """
        Zoekt naar specifieke termen en vindt het dichtstbijzijnde relevante element.
        """
        try:
            # Verzamel alle tekst elementen
            elements = await page.query_selector_all('*')
            matches = []
            
            for element in elements:
                try:
                    # Haal tekst op van het element
                    text = await element.text_content()
                    if not text:
                        continue
                        
                    text = text.lower().strip()
                    
                    # Check of een van de zoektermen voorkomt
                    if any(term.lower() in text for term in search_terms):
                        if element_type == 'text':
                            # Voor m² prijzen: zoek naar getallen in dezelfde tekst
                            price_matches = re.findall(r'€?\s*(\d+(?:[,.]\d+)?)', text)
                            if price_matches:
                                price = float(price_matches[0].replace(',', '.'))
                                matches.append({
                                    'text': text,
                                    'value': price,
                                    'distance': 0  # Directe match in dezelfde tekst
                                })
                        else:
                            # Voor form fields: zoek naar input/select elementen in de buurt
                            # 1. Check voor een explicit label-for relatie
                            tag_name = await element.evaluate('node => node.tagName.toLowerCase()')
                            if tag_name == 'label':
                                field_id = await element.get_attribute('for')
                                if field_id:
                                    field = await page.query_selector(f'#{field_id}')
                                    if field:
                                        field_tag = await field.evaluate('node => node.tagName.toLowerCase()')
                                        if (element_type == 'select' and field_tag == 'select') or \
                                           (element_type == 'input' and field_tag == 'input'):
                                            matches.append({
                                                'text': text,
                                                'id': field_id,
                                                'distance': 0  # Directe label relatie
                                            })
                                            continue
                            
                            # 2. Check voor elementen in de parent container
                            parent = await element.query_selector('..')
                            if parent:
                                selector = element_type
                                if element_type == 'select':
                                    selector = 'select, [class*="select"], [class*="dropdown"]'
                                elif element_type == 'input':
                                    selector = 'input[type="text"], input[type="number"], input:not([type])'
                                
                                nearby = await parent.query_selector_all(selector)
                                for field in nearby:
                                    field_id = await field.get_attribute('id')
                                    matches.append({
                                        'text': text,
                                        'id': field_id,
                                        'distance': 1  # In dezelfde parent
                                    })
                            
                            # 3. Check voor elementen in de grootouder container
                            grandparent = await parent.query_selector('..')
                            if grandparent:
                                selector = element_type
                                if element_type == 'select':
                                    selector = 'select, [class*="select"], [class*="dropdown"]'
                                elif element_type == 'input':
                                    selector = 'input[type="text"], input[type="number"], input:not([type])'
                                
                                nearby = await grandparent.query_selector_all(selector)
                                for field in nearby:
                                    field_id = await field.get_attribute('id')
                                    matches.append({
                                        'text': text,
                                        'id': field_id,
                                        'distance': 2  # In de grootouder
                                    })
                
                except Exception as e:
                    continue
            
            # Sorteer matches op afstand (dichtsbij eerst)
            matches.sort(key=lambda x: x['distance'])
            
            if matches:
                return matches[0]
            
            return None
            
        except Exception as e:
            print(f"Error bij zoeken naar element: {str(e)}")
            return None

    async def analyze_form_fields(self, url: str) -> Dict:
        """Analyseert de form fields op de pagina"""
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch()
                page = await browser.new_page()
                await page.goto(url)
                
                dimension_fields = {}
                
                # Zoektermen voor verschillende dimensies
                dimension_terms = {
                    'dikte': {
                        'terms': ['dikte', 'thickness', 'dicke', 'épaisseur', 'mm', 'millimeter'],
                        'type': 'select'
                    },
                    'lengte': {
                        'terms': ['lengte', 'length', 'länge', 'longueur'],
                        'type': 'input'
                    },
                    'breedte': {
                        'terms': ['breedte', 'width', 'breite', 'largeur', 'hoogte', 'height', 'höhe', 'hauteur'],
                        'type': 'input'
                    }
                }
                
                # Zoek naar elk type dimensie
                for dimension, config in dimension_terms.items():
                    result = await self._find_nearest_element(
                        page, 
                        config['terms'],
                        config['type']
                    )
                    
                    if result:
                        print(f"Gevonden {dimension} veld: {result['text']}")
                        dimension_fields[dimension] = [{
                            'id': result['id'],
                            'label': result['text'],
                            'tag': config['type']
                        }]
                
                await browser.close()
                return dimension_fields
                
        except Exception as e:
            print(f"Error tijdens form analyse: {str(e)}")
            return {} 