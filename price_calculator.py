from playwright.async_api import async_playwright, Page, expect
from typing import Dict, Any, Optional, Tuple, List
import logging
import re
import os
import json
import asyncio
from urllib.parse import urlparse
from datetime import datetime
from database import SessionLocal
import crud
from config import HEADLESS

logging.basicConfig(level=logging.INFO)

class PriceCalculator:
    """Calculate prices based on dimensions for different domains"""
    
    # Class variable to store latest status
    latest_status = None
    
    def __init__(self):
        """Initialize the calculator"""
        self._update_status("Initializing calculator")

    def _normalize_domain(self, url: str) -> str:
        """Normalize domain name by removing www. and getting base domain"""
        parsed = urlparse(url if url.startswith('http') else f'http://{url}')
        domain = parsed.netloc or parsed.path
        return domain.replace('www.', '')

    def _load_configs(self):
        """Load configurations from database"""
        db = SessionLocal()
        try:
            # Load domain configs
            domain_configs = crud.get_domain_configs(db)
            for config in domain_configs:
                self.configs[config.domain] = config.config
        finally:
            db.close()

    def _update_status(self, message: str, step_type: str = None, step_details: dict = None):
        """Update the status of the current operation"""
        PriceCalculator.latest_status = {
            "message": message,
            "step_type": step_type,
            "step_details": step_details,
            "timestamp": datetime.now().isoformat()
        }
        logging.info(f"Status update: {message}")

    async def calculate_price(self, url: str, dimensions: Dict[str, float], country: str = 'nl', category: str = 'square_meter_price') -> Tuple[float, float]:
        """Calculate price based on dimensions for a specific domain"""
        try:
            # Get domain from URL
            domain = self._normalize_domain(url)
            
            # Get configuration from database
            db = SessionLocal()
            config = crud.get_domain_config(db, domain)
            if not config:
                raise ValueError(f"No configuration found for domain: {domain}")
            
            domain_config = config.config

            # Get country config
            country_config = crud.get_country_config(db, country)
            if not country_config:
                country_config = crud.get_country_config(db, 'nl')  # Fallback to NL
            country_info = country_config.config

        finally:
            db.close()

        if category not in domain_config['categories']:
            raise ValueError(f"Category '{category}' not supported for domain: {domain}")

        self._update_status(f"Starting price calculation for {domain}", "config", {"domain": domain})

        async with async_playwright() as p:
            # Launch browser with headless mode based on environment
            browser = await p.chromium.launch(headless=HEADLESS)
            
            # Create context with viewport settings
            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080}
            )
            
            # Create page from context and set timeout
            page = await context.new_page()
            page.set_default_timeout(120000)  # 120 seconds timeout

            try:
                # Navigate to URL with increased timeout
                self._update_status(f"Navigating to {url}", "navigation", {"url": url})
                await page.goto(url, timeout=120000)  # 120 seconds timeout
                self._update_status("Waiting for page to be fully loaded", "loading")
                await page.wait_for_load_state('networkidle')
                self._update_status("Page loaded successfully", "loaded")
                await page.wait_for_timeout(100)  # Small delay to ensure status is sent

                # Execute steps
                steps = domain_config['categories'][category]['steps']
                for step in steps:
                    step_type = step['type']
                    
                    if step_type == 'select':
                        await self._handle_select(page, step, dimensions)
                    elif step_type == 'input':
                        await self._handle_input(page, step, dimensions)
                    elif step_type == 'click':
                        await self._handle_click(page, step)
                    elif step_type == 'wait':
                        await self._handle_wait(step)
                    elif step_type == 'blur':
                        await self._handle_blur(page, step)
                    elif step_type == 'read_price':
                        price = await self._handle_read_price(page, step)
                        
                        # Convert price based on VAT
                        vat_rate = country_info['vat_rate']
                        if step.get('includes_vat', False):
                            price_excl = price / (1 + vat_rate/100)
                            price_incl = price
                        else:
                            price_excl = price
                            price_incl = price * (1 + vat_rate/100)

                        self._update_status(
                            "Price calculation completed",
                            "complete",
                            {
                                "price_excl_vat": price_excl,
                                "price_incl_vat": price_incl
                            }
                        )
                        
                        return price_excl, price_incl
                    elif step_type == 'modify_element':
                        await self._handle_modify(page, step)

            except Exception as e:
                self._update_status(f"Error: {str(e)}", "error")
                raise
            finally:
                await browser.close()

        raise ValueError("No price found in configuration steps")

    def _convert_value(self, value: float, unit: str) -> float:
        """Convert a value from millimeters to the target unit"""
        # Convert value to float if it's an integer
        value = float(value)
        
        if unit == 'cm':
            return value / 10
        return value  # Default is mm

    async def _handle_select(self, page, step, dimensions):
        """Handle a select/input step"""
        # Controleer eerst of 'value' aanwezig is in de step dictionary
        if 'value' not in step:
            if 'use_index' in step and step['use_index'] and 'option_index' in step:
                # Voeg automatisch een value toe in het juiste format
                step['value'] = f"index:{step['option_index']}"
                self._update_status(f"Added value 'index:{step['option_index']}' based on option_index", "select")
            else:
                self._update_status("No value specified for select step", "error")
                raise ValueError("Missing required field 'value' in select step")
        
        value = step['value']
        selector = step['selector']
        
        # Check for index-based selection
        if value.startswith('index:'):
            try:
                # Extract the index from the value string (format: 'index:X')
                index = int(value.split(':', 1)[1])
                logging.info(f"Handling index-based selection: {selector} with index {index}")
                self._update_status(f"Selecting option with index {index}", "select", {"selector": selector, "index": index})
                
                # Find the select element
                element = await page.wait_for_selector(selector, timeout=5000)
                if not element:
                    raise ValueError(f"No element found matching selector: {selector}")
                
                # Ensure the element is visible
                await element.scroll_into_view_if_needed()
                await asyncio.sleep(0.5)
                
                # Check if it's a standard SELECT element
                tag_name = await element.evaluate('el => el.tagName.toLowerCase()')
                if tag_name == 'select':
                    # For SELECT elements, we can directly select by index
                    options = await element.evaluate('(select) => Array.from(select.options).map(o => o.value)')
                    if index < len(options):
                        # Select the option by index
                        await element.click()  # Click to open dropdown
                        await asyncio.sleep(0.2)
                        # Get the option value at the specified index
                        option_value = options[index]
                        await element.select_option(value=option_value)
                        await asyncio.sleep(0.5)
                        await element.evaluate('(el) => el.dispatchEvent(new Event("change", { bubbles: true }))')
                        return
                    else:
                        raise ValueError(f"Index {index} is out of range for select element with {len(options)} options")
                else:
                    # For non-standard dropdowns, try to find all options and click the one at the specified index
                    await element.click()  # Click to open dropdown
                    await asyncio.sleep(0.5)
                    
                    # Try to find options (this depends on the site's structure)
                    options = await page.query_selector_all('li, .option, .dropdown-item, [role="option"]')
                    if not options:
                        self._update_status(f"No dropdown options found", "warn")
                        # Try again with a different approach - look for children of the dropdown
                        options = await element.evaluate('''
                            (el) => {
                                // Try to find all clickable children
                                const allOptions = [
                                    ...Array.from(document.querySelectorAll('li, .option, .dropdown-item, [role="option"]')),
                                    ...Array.from(el.querySelectorAll('*'))
                                ].filter(el => el.offsetParent !== null); // Only visible elements
                                return allOptions;
                            }
                        ''')
                    
                    # If we still have no options, try a last approach
                    if not options or len(options) <= index:
                        self._update_status(f"Could not find {index} options in dropdown", "warn")
                        # Try JavaScript selection
                        await page.evaluate(f'''
                            (selector, index) => {{
                                const el = document.querySelector(selector);
                                if (el) {{
                                    // Try common dropdown implementations
                                    if (el.options && el.options.length > index) {{
                                        // Standard select
                                        el.selectedIndex = index;
                                        el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                                    }} else if (el.querySelectorAll) {{
                                        // Try to find child elements
                                        const options = el.querySelectorAll('li, .option, div, a, span');
                                        if (options && options.length > index) {{
                                            options[index].click();
                                        }}
                                    }}
                                }}
                            }}
                        ''', selector, index)
                        await asyncio.sleep(1)
                        return
                    
                    # Click the option at the specified index
                    if index < len(options):
                        await options[index].click()
                        await asyncio.sleep(0.5)
                        return
                    else:
                        raise ValueError(f"Index {index} is out of range for dropdown with {len(options)} options")
            
            except Exception as e:
                self._update_status(f"Error with index-based selection: {str(e)}", "error")
                raise ValueError(f"Failed to select option by index: {str(e)}")
        
        # Handle regular value-based selection
        for key in ['thickness', 'width', 'length']:
            if f"{{{key}}}" in value:
                if key in dimensions:
                    converted_value = self._convert_value(dimensions[key], step.get('unit', 'mm'))
                    if isinstance(converted_value, float) and converted_value.is_integer():
                        converted_value = int(converted_value)
                    value = value.replace(f"{{{key}}}", str(converted_value))
                    self._update_status(
                        f"Setting {key} to {converted_value}",
                        "select",
                        {
                            "selector": selector,
                            "value": str(converted_value),
                            "unit": step.get('unit', 'mm')
                        }
                    )
                else:
                    self._update_status(f"Dimension {key} not found", "error")
                    raise ValueError(f"Dimension {key} not found in dimensions dict")
        
        logging.info(f"Handling select/input: {selector} with target value {value}")
        self._update_status(f"Handling select/input with value {value}", "select", {"selector": selector, "value": value})
        
        try:
            target_value = float(value)
        except ValueError:
            # If we can't convert to float, treat it as a string-based selection
            self._update_status(f"Using string-based selection with value: {value}", "select")
            
            element = await page.wait_for_selector(selector, timeout=5000)
            if not element:
                raise ValueError(f"No element found matching selector: {selector}")
                
            tag_name = await element.evaluate('el => el.tagName.toLowerCase()')
            if tag_name == 'select':
                # For select elements, try to find option with matching text
                await element.select_option(label=value)
                await asyncio.sleep(0.5)
                return
            else:
                # For non-standard dropdowns, try to find an option containing the text
                await element.click()  # Click to open dropdown
                await asyncio.sleep(0.5)
                
                # Try to find options with matching text
                options = await page.query_selector_all('li, .option, .dropdown-item, [role="option"]')
                for option in options:
                    option_text = await option.text_content()
                    if value.lower() in option_text.lower():
                        await option.click()
                        await asyncio.sleep(0.5)
                        return
                
                raise ValueError(f"No option found with text containing '{value}'")

        # First check if we need to open a dropdown/container
        if 'container_trigger' in step:
            trigger = await page.wait_for_selector(step['container_trigger'])
            if trigger:
                await trigger.click()
                await asyncio.sleep(0.5)

        # Find all matching elements
        elements = await page.query_selector_all(selector)
        if not elements:
            raise ValueError(f"No elements found matching selector: {selector}")

        best_match = None
        smallest_diff = float('inf')

        # Try each element
        for element in elements:
            try:
                # Get element type
                tag_name = await element.evaluate('el => el.tagName.toLowerCase()')
                element_type = await element.get_attribute('type') if tag_name == 'input' else None

                # Get the value and any associated text
                value_attr = await element.get_attribute('value')
                element_text = ''

                if tag_name == 'select':
                    # For select elements, get all options
                    options = await element.evaluate('''(select) => {
                        return Array.from(select.options).map(option => ({
                            value: option.value,
                            text: option.text.trim()
                        }));
                    }''')
                    
                    for option in options:
                        try:
                            numeric_match = re.search(r'(\d+(?:\.\d+)?)', option['text'])
                            if numeric_match:
                                option_value = float(numeric_match.group(1))
                                diff = abs(option_value - target_value)
                                if diff < smallest_diff:
                                    smallest_diff = diff
                                    best_match = {
                                        'element': element,
                                        'type': 'select',
                                        'value': option['value'],
                                        'option_value': option_value
                                    }
                        except Exception as e:
                            logging.error(f"Error processing select option: {str(e)}")

                elif element_type in ['radio', 'checkbox']:
                    try:
                        # Get numeric value from the value attribute
                        numeric_match = re.search(r'(\d+(?:\.\d+)?)', value_attr)
                        if numeric_match:
                            option_value = float(numeric_match.group(1))
                            diff = abs(option_value - target_value)
                            logging.info(f"Found radio/checkbox with value {option_value} (target: {target_value}, diff: {diff})")
                            if diff < smallest_diff:
                                smallest_diff = diff
                                best_match = {
                                    'element': element,
                                    'type': 'input',
                                    'option_value': option_value
                                }
                    except Exception as e:
                        logging.error(f"Error processing radio/checkbox: {str(e)}")

                else:
                    # For other elements, try to find numeric value in text content
                    element_text = await element.text_content()
                    numeric_match = re.search(r'(\d+(?:\.\d+)?)', element_text)
                    if numeric_match:
                        option_value = float(numeric_match.group(1))
                        diff = abs(option_value - target_value)
                        if diff < smallest_diff:
                            smallest_diff = diff
                            best_match = {
                                'element': element,
                                'type': 'other',
                                'option_value': option_value
                            }

            except Exception as e:
                logging.error(f"Error processing element: {str(e)}")
                continue

        # Select the best matching option
        if best_match and smallest_diff < 0.01:  # Strict matching threshold
            logging.info(f"Found best match with value {best_match.get('option_value')} (diff: {smallest_diff})")
            
            # Ensure element is in view and clickable
            await best_match['element'].scroll_into_view_if_needed()
            await asyncio.sleep(0.5)  # Wait for scroll to complete
            
            if best_match['type'] == 'select':
                # For select elements, first click to open dropdown
                await best_match['element'].click()
                await asyncio.sleep(0.2)
                # Then select the option
                await best_match['element'].select_option(value=best_match['value'])
                # Finally click again to close dropdown
                await best_match['element'].click()
            else:
                # For radio/checkbox/other, simulate a real click
                # First ensure we're clicking the center of the element
                box = await best_match['element'].bounding_box()
                if box:
                    x = box['x'] + box['width'] / 2
                    y = box['y'] + box['height'] / 2
                    await page.mouse.click(x, y)
                else:
                    # Fallback to element click if we can't get bounding box
                    await best_match['element'].click()
            
            # Dispatch change event
            await best_match['element'].evaluate('(el) => el.dispatchEvent(new Event("change", { bubbles: true }))')
            await asyncio.sleep(1)
            return
        else:
            raise ValueError(f"Could not find matching option for value {value}mm (closest diff was {smallest_diff})")

    async def _handle_input(self, page, step, dimensions):
        value = step['value']
        clear_first = step.get('clear_first', True)  # Default to clearing the field first
        max_retries = 3
        selector = step['selector']
        
        # Variabelen in de value string vervangen door waarden uit dimensions
        for key in ['thickness', 'width', 'length', 'quantity']:
            if f"{{{key}}}" in value:
                if key in dimensions:
                    converted_value = self._convert_value(dimensions[key], step.get('unit', 'mm'))
                    # Convert to integer if it's a whole number
                    if converted_value.is_integer():
                        converted_value = int(converted_value)
                    value = value.replace(f"{{{key}}}", str(converted_value))
                    self._update_status(
                        f"Setting {key} to {converted_value}",
                        "input",
                        {
                            "selector": selector,
                            "value": str(converted_value),
                            "unit": step.get('unit', 'mm')
                        }
                    )
                else:
                    self._update_status(f"Dimension {key} not found", "error")
                    raise ValueError(f"Dimension {key} not found in dimensions dict")

        logging.info(f"Handling input: {selector} with value {value}")
        self._update_status(f"Setting input value {value}", "input", {"selector": selector, "value": value})
        
        for attempt in range(max_retries):
            try:
                # Wacht langer op het element in de online omgeving
                element = await page.wait_for_selector(selector, timeout=5000)  # 5 seconden timeout
                if not element:
                    raise ValueError(f"Element not found: {selector}")
                
                # Scroll naar het element om zeker te zijn dat het zichtbaar is
                await element.scroll_into_view_if_needed()
                await asyncio.sleep(0.5)
                
                # Focus op het element voordat we beginnen
                await element.focus()
                await asyncio.sleep(0.3)
                
                if clear_first:
                    # Leeg het veld op verschillende manieren
                    await element.evaluate('(el) => { el.value = ""; }')
                    await asyncio.sleep(0.3)
                    
                    # Selecteer alle tekst en verwijder
                    await element.click(click_count=3)  # Triple click selecteert alle tekst
                    await asyncio.sleep(0.2)
                    await element.press('Backspace')
                    await asyncio.sleep(0.2)
                
                # Type de nieuwe waarde, met korte pauzes tussen tekens
                await element.type(str(value), delay=50)  # 50ms vertraging tussen tekens
                
                # Stuur events om de website te informeren over de wijziging
                await element.evaluate('''(el) => {
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    el.dispatchEvent(new Event('blur', { bubbles: true }));
                }''')
                
                # Bevestig dat de waarde correct is ingevoerd
                actual_value = await element.evaluate('(el) => el.value')
                if actual_value == str(value) or str(value) in actual_value:
                    self._update_status(f"Successfully set input to {value}", "input", {"status": "success"})
                    break
                else:
                    self._update_status(f"Value mismatch: expected {value}, got {actual_value}", "warn")
                    if attempt == max_retries - 1:
                        # Als dit de laatste poging was, probeer nog één andere methode
                        await element.evaluate(f'(el) => {{ el.value = "{value}"; }}')
                
                # Langere wachttijd tussen acties
                await asyncio.sleep(1.0)
                
            except Exception as e:
                self._update_status(f"Error setting input (attempt {attempt+1}/{max_retries}): {str(e)}", "warn")
                if attempt == max_retries - 1:  # als dit de laatste poging was
                    self._update_status(f"Failed to set input after {max_retries} attempts", "error")
                    raise
                await asyncio.sleep(1.0)  # wacht voor de volgende poging

    async def _handle_click(self, page, step):
        """Handle a click step"""
        selector = step['selector']
        description = step.get('description', '')
        max_retries = 3
        
        # Add more descriptive messages for specific actions
        if 'figure' in selector.lower():
            self._update_status(f"Selecting figure shape", "click", {"selector": selector})
        elif 'calculator' in selector.lower():
            self._update_status(f"Opening calculator section", "click", {"selector": selector})
        elif 'winkelwagen' in selector.lower() or '.cart' in selector.lower():
            self._update_status(f"Adding to shopping cart", "click", {"selector": selector})
        else:
            self._update_status(f"Clicking {selector}", "click", {"selector": selector})
        
        for attempt in range(max_retries):
            try:
                # Wacht langer op het element
                element = await page.wait_for_selector(selector, timeout=5000)
                if not element:
                    raise ValueError(f"Element not found: {selector}")
                
                # Zorg ervoor dat het element zichtbaar is
                is_visible = await element.is_visible()
                if not is_visible:
                    self._update_status(f"Element {selector} is not visible, trying to scroll into view", "warn")
                    await element.scroll_into_view_if_needed()
                    await asyncio.sleep(0.5)
                
                # Als het een .cart element is of winkelwagen, probeer het op verschillende manieren te klikken
                if '.cart' in selector.lower() or 'winkelwagen' in selector.lower():
                    # Probeer eerst JavaScript klik
                    try:
                        await page.evaluate(f"""
                            const element = document.querySelector('{selector}');
                            if (element) {{
                                // Zorg ervoor dat het element zichtbaar is
                                element.style.zIndex = '9999';
                                element.style.position = 'relative';
                                element.scrollIntoView({{behavior: 'smooth', block: 'center'}});
                                setTimeout(() => {{
                                    // Klik na een korte vertraging
                                    element.click();
                                }}, 100);
                            }}
                        """)
                        await asyncio.sleep(1.0)
                        self._update_status(f"Clicked {selector} using JavaScript", "click", {"status": "success"})
                    except Exception as js_error:
                        self._update_status(f"JavaScript click failed: {str(js_error)}", "warn")
                        # Als JavaScript klik mislukt, probeer normale klik
                        await element.click()
                else:
                    # Normale klik voor andere elementen
                    await element.click()
                
                self._update_status(f"Successfully clicked {selector}", "click", {"status": "success"})
                await asyncio.sleep(1.0)  # Langere wachttijd na klik
                return True
                
            except Exception as e:
                self._update_status(f"Click failed (attempt {attempt+1}/{max_retries}): {str(e)}", "warn")
                
                # Speciale aanpak voor cart elementen bij laatste poging
                if attempt == max_retries - 1 and ('.cart' in selector.lower() or 'winkelwagen' in selector.lower()):
                    try:
                        # Laatste poging: gebruik execute_script voor direct document.querySelector
                        self._update_status(f"Trying alternative method to click {selector}", "click")
                        await page.evaluate(f"""
                            const cart = document.querySelector('{selector}');
                            if (cart) {{
                                cart.style.pointerEvents = 'auto';
                                cart.style.opacity = '1';
                                cart.style.visibility = 'visible';
                                cart.style.display = 'block';
                                cart.style.zIndex = '10000';
                                cart.scrollIntoView({{behavior: 'smooth', block: 'center'}});
                                setTimeout(() => cart.click(), 200);
                            }}
                        """)
                        await asyncio.sleep(1.5)
                        self._update_status(f"Attempted alternative click on {selector}", "click")
                        return True
                    except Exception as final_error:
                        self._update_status(f"All click attempts failed: {str(final_error)}", "error")
                
                if attempt == max_retries - 1:
                    self._update_status(f"Click failed after {max_retries} attempts", "error")
                    raise
                
                await asyncio.sleep(1.0)  # Wacht voordat we het opnieuw proberen

    async def _handle_wait(self, step):
        """Handle a wait step"""
        # Predefined wait durations in seconds
        WAIT_DURATIONS = {
            'short': 0.5,
            'default': 1.0,
            'long': 1.5,
            'longer': 3.0
        }
        
        duration = step.get('duration', 'default')
        if isinstance(duration, str):
            wait_time = WAIT_DURATIONS.get(duration.lower(), WAIT_DURATIONS['default'])
        else:
            wait_time = float(duration)
            
        self._update_status(f"Waiting for {wait_time} seconds", "wait", {"duration": wait_time})
        await asyncio.sleep(wait_time)
        self._update_status(f"Wait completed", "wait", {"duration": wait_time})

    async def _handle_read_price(self, page, step):
        """Handle reading a price"""
        selector = step['selector']
        self._update_status("Reading price", "read_price", {"selector": selector})
        
        try:
            element = await page.wait_for_selector(selector, timeout=5000)  # 5 seconden timeout
            if not element:
                self._update_status("Price element not found, returning 0.00", "read_price", {"price": 0.0})
                return 0.0

            price_text = await element.text_content()
            self._update_status("Found price text", "read_price", {"text": price_text})
            
            # Clean and parse price
            cleaned_price = re.sub(r'[^\d,.]', '', price_text).replace(',', '.')
            price = float(cleaned_price)
            
            self._update_status(f"Price found: €{price:.2f}", "read_price", {"price": price})
            return price
        except Exception as e:
            self._update_status(f"Error reading price, returning 0.00: {str(e)}", "warn")
            return 0.0

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
                # Launch browser in non-headless mode
                browser = await p.chromium.launch(headless=False)
                # Create page with full HD viewport
                page = await browser.new_page(viewport={'width': 1920, 'height': 1080})
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

    async def _handle_blur(self, page, step):
        """Handle a blur step by either using the selector from the step or the last interacted element"""
        selector = step.get('selector')
        
        try:
            if selector:
                # If a selector is provided, use it
                self._update_status(f"Triggering blur on {selector}", "blur", {"selector": selector})
                element = await page.wait_for_selector(selector)
                if element:
                    await element.evaluate('(el) => { el.blur(); }')
                    self._update_status(f"Blur completed on {selector}", "blur", {"selector": selector, "status": "success"})
            else:
                # If no selector is provided, try to blur the active element
                self._update_status("Triggering blur on active element", "blur")
                await page.evaluate('() => { document.activeElement?.blur(); }')
                self._update_status("Blur completed on active element", "blur", {"status": "success"})
        except Exception as e:
            self._update_status(f"Blur failed: {str(e)}", "error")
            raise 

    async def _handle_modify(self, page, step):
        """Handle a modify_element step that runs JavaScript to modify an element"""
        selector = step['selector']
        script = step.get('script', '')
        add_class = step.get('add_class', '')
        add_attribute = step.get('add_attribute', {})
        
        self._update_status(f"Modifying element {selector}", "modify", {"selector": selector})
        
        try:
            # Wacht tot het element beschikbaar is
            element = await page.wait_for_selector(selector)
            if not element:
                self._update_status(f"Element not found: {selector}", "error")
                return
                
            if add_class:
                # Voeg een class toe aan het element
                await page.evaluate("""
                    const element = document.querySelector(""" + f'"{selector}"' + """);
                    if (element) {{
                        element.classList.add(""" + f'"{add_class}"' + """);
                    }}
                """)
                self._update_status(f"Added class '{add_class}' to {selector}", "modify", {"status": "success"})
                
            if add_attribute and isinstance(add_attribute, dict):
                # Voeg attributen toe aan het element
                for attr_name, attr_value in add_attribute.items():
                    await page.evaluate("""
                        const element = document.querySelector(""" + f'"{selector}"' + """);
                        if (element) {{
                            element.setAttribute(""" + f'"{attr_name}", "{attr_value}"' + """);
                        }}
                    """)
                self._update_status(f"Added attributes to {selector}", "modify", {"status": "success"})
                
            if script:
                # Voer aangepast JavaScript uit
                js_code = """
                    const element = document.querySelector(""" + f'"{selector}"' + """);
                    if (element) {{
                        try {{
                            """ + script + """
                            console.log('Custom script executed successfully');
                        }} catch (e) {{
                            console.error('Error executing script:', e);
                        }}
                    }}
                """
                await page.evaluate(js_code)
                self._update_status(f"Executed custom script on {selector}", "modify", {"status": "success"})
                
        except Exception as e:
            self._update_status(f"Modify element failed: {str(e)}", "error")
            raise

    async def _process_step(self, page, step, dimensions):
        """Process a single step in the configuration"""
        step_type = step['type']
        
        try:
            if step_type == 'select':
                await self._handle_select(page, step, dimensions)
            elif step_type == 'input':
                await self._handle_input(page, step, dimensions)
            elif step_type == 'click':
                await self._handle_click(page, step)
            elif step_type == 'wait':
                await self._handle_wait(step)
            elif step_type == 'read_price':
                return await self._handle_read_price(page, step)
            elif step_type == 'modify_element':
                await self._handle_modify(page, step)
            else:
                self._update_status(f"Unknown step type: {step_type}", "error")
                
        except Exception as e:
            self._update_status(f"Error processing step: {str(e)}", "error")
            raise
        
        return None 