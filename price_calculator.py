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
import random
import string

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
                    elif step_type == 'captcha':
                        await self._handle_captcha(page, step)
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
            # Als use_index is ingesteld en option_index is beschikbaar, gebruik index gebaseerde selectie
            if 'use_index' in step and step['use_index'] and 'option_index' in step:
                # Voeg automatisch een value toe in het juiste format
                step['value'] = f"index:{step['option_index']}"
                self._update_status(f"Added value 'index:{step['option_index']}' based on option_index", "select")
            # Als er geen selector is, probeer opties te raden op basis van andere velden
            elif 'selector' in step:
                # Log dit als een waarschuwing en gebruik een default waarde
                self._update_status(f"No value specified for select step, using empty value", "warn")
                step['value'] = ""  # Lege string als fallback
            else:
                # Als er geen selector is, kunnen we niet verder
                self._update_status("Missing required fields for select step", "error")
                raise ValueError("Missing required fields in select step: need 'value' or 'use_index' + 'option_index'")
        
        # Controleer of de selector aanwezig is
        if 'selector' not in step:
            if 'select_element' in step:
                # Als select_element aanwezig is, gebruik dat als selector (compatibiliteit met index selectie)
                step['selector'] = step['select_element']
                self._update_status(f"Using select_element as selector", "select")
            else:
                # Als er geen selector is, kunnen we niet verder
                self._update_status("No selector specified for select step", "error")
                raise ValueError("Missing required field 'selector' in select step")
        
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
        
        # Value is een lege string, probeer de eerste optie te selecteren
        if value == "":
            try:
                element = await page.wait_for_selector(selector, timeout=5000)
                if not element:
                    self._update_status(f"Element not found: {selector}", "error")
                    return  # Ga verder zonder error
                
                tag_name = await element.evaluate('el => el.tagName.toLowerCase()')
                if tag_name == 'select':
                    # Voor select elementen, selecteer de eerste optie
                    await element.select_option(index=0)
                    self._update_status(f"Selected first option for empty value", "select")
                    await asyncio.sleep(0.5)
                    return
                else:
                    # Voor non-standard dropdowns, klik erop en selecteer de eerste optie
                    await element.click()
                    await asyncio.sleep(0.5)
                    options = await page.query_selector_all('li, .option, .dropdown-item, [role="option"]')
                    if options and len(options) > 0:
                        await options[0].click()
                        self._update_status(f"Selected first dropdown option for empty value", "select")
                        await asyncio.sleep(0.5)
                        return
            except Exception as e:
                self._update_status(f"Error selecting first option: {str(e)}", "warn")
                # Ga verder met reguliere selectie
        
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
        # Check eerst of 'selector' aanwezig is
        if 'selector' not in step:
            self._update_status(f"Missing selector in input step", "error")
            raise ValueError("No selector specified for input step")
            
        selector = step['selector']
        max_retries = 3
        clear_first = step.get('clear_first', True)  # Default to clearing the field first
        
        # Check voor randomize
        if step.get('randomize') or step.get('input_method') == 'randomize':
            random_type = step.get('random_type', 'Generic Term')
            
            # Genereer willekeurige waarde op basis van het type
            if random_type == 'First Name':
                first_names = ['Jan', 'Piet', 'Klaas', 'Maria', 'Anna', 'Sara', 'Emma', 'Sophie', 'Thomas', 'Daan']
                step['value'] = random.choice(first_names)
                self._update_status(f"Using random first name: {step['value']}", "input", {"selector": selector, "value": step['value']})
            elif random_type == 'Last Name':
                last_names = ['Jansen', 'de Vries', 'van den Berg', 'Bakker', 'Visser', 'Meijer', 'de Boer', 'Mulder', 'de Groot', 'Bos']
                step['value'] = random.choice(last_names)
                self._update_status(f"Using random last name: {step['value']}", "input", {"selector": selector, "value": step['value']})
            elif random_type == 'Email Address':
                domains = ['gmail.com', 'outlook.com', 'hotmail.com', 'yahoo.com', 'protonmail.com']
                first_names = ['jan', 'piet', 'klaas', 'maria', 'anna', 'sara', 'emma', 'thomas', 'daan', 'lisa']
                last_names = ['jansen', 'devries', 'bakker', 'visser', 'meijer', 'deboer', 'mulder', 'degroot', 'bos']
                numbers = [str(random.randint(1, 999)) for _ in range(3)]
                
                # Create email with random parts
                parts = [random.choice(first_names), random.choice(last_names), random.choice(numbers)]
                random.shuffle(parts)
                email_name = '.'.join(parts[:2])
                domain = random.choice(domains)
                step['value'] = f"{email_name}@{domain}"
                self._update_status(f"Using random email: {step['value']}", "input", {"selector": selector, "value": step['value']})
            elif random_type == 'Password':
                # Haal wachtwoordinstellingen op uit stap
                min_length = int(step.get('password_min_length', 8))  # Ensure this is an integer
                max_length = int(step.get('password_max_length', 16))  # Ensure this is an integer
                include_uppercase = step.get('password_include_uppercase', True)
                include_numbers = step.get('password_include_numbers', True)
                include_special = step.get('password_include_special', True)
                
                # Debug logging
                self._update_status(
                    f"Password settings - min_length: {min_length}, max_length: {max_length}, " +
                    f"uppercase: {include_uppercase}, numbers: {include_numbers}, special: {include_special}",
                    "debug"
                )
                
                # Bepaal de tekens die gebruikt kunnen worden
                chars = string.ascii_lowercase
                if include_uppercase:
                    chars += string.ascii_uppercase
                if include_numbers:
                    chars += string.digits
                if include_special:
                    # Use a more limited set of special characters that are more likely to work across websites
                    chars += '!@#$%^&*'
                    
                # Genereer een wachtwoord met willekeurige lengte tussen min en max
                password_length = random.randint(min_length, max_length)
                
                # Ensure at least one character of each required type is included
                must_include = []
                if include_uppercase:
                    must_include.append(random.choice(string.ascii_uppercase))
                if include_numbers:
                    must_include.append(random.choice(string.digits))
                if include_special:
                    must_include.append(random.choice('!@#$%^&*'))
                
                # Generate remaining characters
                remaining_length = password_length - len(must_include)
                remaining_chars = [random.choice(chars) for _ in range(remaining_length)]
                
                # Combine and shuffle
                all_chars = must_include + remaining_chars
                random.shuffle(all_chars)
                
                # Generate the password and ensure it's a string
                password = ''.join(all_chars)
                step['value'] = password  # Store the password
                
                # Log the password generation (without showing the actual password)
                self._update_status(
                    f"Generated random password (length: {password_length})",
                    "input",
                    {
                        "selector": selector,
                        "value": "[HIDDEN]",
                        "length": str(password_length),
                        "includes_uppercase": str(include_uppercase),
                        "includes_numbers": str(include_numbers),
                        "includes_special": str(include_special)
                    }
                )
            elif random_type == 'Street Name':
                # Lijst met Nederlandse straatnamen
                street_names = [
                    'Hoofdstraat', 'Kerkstraat', 'Schoolstraat', 'Molenstraat', 'Stationstraat',
                    'Dorpsstraat', 'Markt', 'Beekstraat', 'Burgemeesterstraat', 'Industrieweg',
                    'Parallelweg', 'Ringweg', 'Sportlaan', 'Wilhelminastraat', 'Julianastraat',
                    'Beatrixstraat', 'Prins Bernhardstraat', 'Koningstraat', 'Koninginnewal',
                    'Oranjelaan', 'Wilhelminapark', 'Julianapark', 'Beatrixpark', 'Prins Bernhardpark',
                    'Koningin Julianapark', 'Oranjepark', 'Wilhelminaplein', 'Julianaplein',
                    'Beatrixplein', 'Prins Bernhardplein', 'Koningin Julianaplein', 'Oranjeplein'
                ]
                # Voeg een willekeurig huisnummer toe
                house_number = random.randint(1, 999)
                step['value'] = f"{random.choice(street_names)} {house_number}"
                self._update_status(f"Using random street name: {step['value']}", "input", {"selector": selector, "value": step['value']})
            elif random_type == 'Postal Code':
                country = step.get('postal_code_country', 'NL')
                # Genereer postcode op basis van land
                if country == 'NL':
                    # Nederlandse postcode: 4 cijfers + 2 letters
                    numbers = ''.join(random.choices(string.digits, k=4))
                    letters = ''.join(random.choices(string.ascii_uppercase, k=2))
                    step['value'] = f"{numbers} {letters}"
                elif country == 'BE':
                    # Belgische postcode: 4 cijfers
                    step['value'] = ''.join(random.choices(string.digits, k=4))
                elif country == 'DE':
                    # Duitse postcode: 5 cijfers
                    step['value'] = ''.join(random.choices(string.digits, k=5))
                elif country == 'FR':
                    # Franse postcode: 5 cijfers
                    step['value'] = ''.join(random.choices(string.digits, k=5))
                elif country == 'GB':
                    # Britse postcode: AA9A 9AA format
                    area = ''.join(random.choices(string.ascii_uppercase, k=2))
                    district = random.choice(string.ascii_uppercase) + random.choice(string.digits)
                    space = ' '
                    sector = random.choice(string.digits)
                    unit = ''.join(random.choices(string.ascii_uppercase, k=2))
                    step['value'] = f"{area}{district}{space}{sector}{unit}"
                else:
                    # Voor andere landen, gebruik een algemene 5-cijferige postcode
                    step['value'] = ''.join(random.choices(string.digits, k=5))
                self._update_status(f"Using random postal code for {country}: {step['value']}", "input", {"selector": selector, "value": step['value']})
            elif random_type == 'Random Number':
                # Haal de instellingen op voor het willekeurige getal
                min_value = float(step.get('random_number_min', 0))
                max_value = float(step.get('random_number_max', 100))
                decimals = int(step.get('random_number_decimals', 0))
                
                # Genereer een willekeurig getal met het opgegeven aantal decimalen
                random_value = random.uniform(min_value, max_value)
                if decimals == 0:
                    step['value'] = str(int(random_value))
                else:
                    step['value'] = f"{random_value:.{decimals}f}"
                
                self._update_status(f"Using random number: {step['value']}", "input", {"selector": selector, "value": step['value']})
            else:  # Generic Term
                terms = ['test', 'sample', 'example', 'demo', 'trial', 'preview', 'beta', 'review', 'check', 'verify']
                step['value'] = random.choice(terms)
                self._update_status(f"Using random term: {step['value']}", "input", {"selector": selector, "value": step['value']})
        else:
            # Check of 'value' aanwezig is als we niet randomizen
            if 'value' not in step:
                self._update_status(f"No value specified for input step, using empty string", "warn")
                step['value'] = ""  # Gebruik lege string als fallback
            else:
                # Originele waarde uit stap
                step['value'] = step['value']
                
                # Variabelen in de value string vervangen door waarden uit dimensions
        for key in ['thickness', 'width', 'length', 'quantity']:
            if f"{{{key}}}" in step['value']:
                if key in dimensions:
                    converted_value = self._convert_value(dimensions[key], step.get('unit', 'mm'))
                    # Convert to integer if it's a whole number
                    if isinstance(converted_value, float) and converted_value.is_integer():
                        converted_value = int(converted_value)
                    step['value'] = step['value'].replace(f"{{{key}}}", str(converted_value))
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

        logging.info(f"Handling input: {selector} with value {step['value']}")
        self._update_status(f"Setting input value {step['value']}", "input", {"selector": selector, "value": step['value']})
        
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
                try:
                    # Handle passwords with special characters 
                    if step.get('random_type') == 'Password':
                        # First try with type()
                        await element.type(str(step['value']), delay=50)
                    else:
                        await element.type(str(step['value']), delay=50)
                    
                    # Stuur events om de website te informeren over de wijziging
                    await element.evaluate('''(el) => {
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                        el.dispatchEvent(new Event('blur', { bubbles: true }));
                    }''')
                    
                    # Bevestig dat de waarde correct is ingevoerd
                    actual_value = await element.evaluate('(el) => el.value')
                    # Always convert to string for comparison
                    actual_value_str = str(actual_value)
                    step_value_str = str(step['value'])
                    
                    if actual_value_str == step_value_str or step_value_str in actual_value_str:
                        self._update_status(f"Successfully set input to {step_value_str if step.get('random_type') != 'Password' else '[HIDDEN]'}", "input", {"status": "success"})
                        return
                    else:
                        self._update_status(f"Value mismatch: expected value not matching actual value", "warn")
                        
                        # For passwords or values with special characters, try an alternative method as a last resort
                        if attempt == max_retries - 1:
                            # Try direct JavaScript fill for the password
                            value = str(step['value'])
                            
                            # Double escape special characters for JavaScript
                            escaped_value = value.replace('\\', '\\\\').replace('"', '\\"').replace("'", "\\'")
                            js_code = f'''(el) => {{
                                try {{
                                    // First try direct value assignment
                                    el.value = "{escaped_value}";
                                    // Then dispatch appropriate events
                                    el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                                    el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                                    return true;
                                }} catch(e) {{
                                    console.error("Error setting value:", e);
                                    return false;
                                }}
                            }}'''
                            
                            success = await element.evaluate(js_code)
                            if success:
                                self._update_status("Successfully set value using JavaScript method", "input", {"status": "success"})
                            else:
                                self._update_status("Failed to set value with all methods", "error")
                
                except Exception as e:
                    self._update_status(f"Error in typing: {str(e)}", "warn")
                    if attempt == max_retries - 1:
                        # As a last resort for passwords, try filling character by character
                        if step.get('random_type') == 'Password':
                            try:
                                await element.fill('')  # Clear first
                                password = str(step['value'])
                                for char in password:
                                    await page.keyboard.press(char)
                                self._update_status("Typed password character by character", "input")
                            except Exception as char_error:
                                self._update_status(f"Character-by-character typing failed: {str(char_error)}", "error")
                
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
        # Check of dit een geldig stap object is
        if not isinstance(step, dict):
            self._update_status(f"Invalid step type: {type(step)}", "error")
            raise ValueError(f"Step must be a dictionary, got {type(step)}")

        # Valideer dat het stap type bestaat
        if 'type' not in step:
            self._update_status("Step missing 'type' field", "error")
            raise ValueError("Step configuration missing required 'type' field")
            
        step_type = step['type']
        
        # Voeg extra validatie toe voor specifieke staptypes
        if step_type == 'select' and 'value' not in step and 'use_index' not in step:
            # Voor select stappen zonder value of use_index, voeg een lege waarde toe
            step['value'] = ""
            self._update_status("Adding empty value for select step", "warn")
        
        if step_type == 'input':
            # Voor input stappen, controleer of we randomiseren
            if step.get('input_method') == 'randomize':
                # Als we randomiseren, zorg ervoor dat random_type aanwezig is
                if 'random_type' not in step:
                    step['random_type'] = 'Generic Term'
                    self._update_status("Adding default random_type for input step", "warn")
            elif 'value' not in step:
                # Als we niet randomiseren en geen waarde hebben, voeg een lege string toe
                step['value'] = ""
                self._update_status("Adding empty value for input step", "warn")
        
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
            elif step_type == 'blur':
                await self._handle_blur(page, step)
            elif step_type == 'captcha':
                await self._handle_captcha(page, step)
            else:
                self._update_status(f"Unknown step type: {step_type}", "error")
                raise ValueError(f"Unknown step type: {step_type}")
                
        except Exception as e:
            self._update_status(f"Error processing step: {str(e)}", "error")
            # Voeg gedetailleerde informatie toe over de stap die mislukte
            logging.error(f"Failed step details: {json.dumps(step, default=str)}")
            raise
        
        return None 

    async def _handle_captcha(self, page, step):
        """Handle different types of captchas including reCAPTCHA and checkbox captchas"""
        captcha_type = step.get('captcha_type', 'checkbox')
        solving_method = step.get('solving_method', 'manual')
        selector = step.get('selector', '')
        frame_selector = step.get('frame_selector', '')
        skip_on_failure = step.get('skip_on_failure', True)
        
        self._update_status(f"Attempting to handle {captcha_type} captcha", "captcha", {
            "type": captcha_type,
            "method": solving_method
        })
        
        # Check if using external service
        if solving_method == 'external_service':
            # Get external service configuration
            service_name = step.get('external_service', '2Captcha')
            api_key = step.get('api_key', '')
            max_wait_time = int(step.get('max_wait_time', 120))
            
            if not api_key:
                self._update_status("No API key provided for external captcha service", "error")
                if skip_on_failure:
                    return
                raise ValueError("No API key provided for external captcha service")
            
            self._update_status(f"Using {service_name} to solve captcha", "captcha")
            
            try:
                # Extract site key from the page
                site_key = await self._extract_recaptcha_key(page)
                if not site_key:
                    self._update_status("Could not extract reCAPTCHA site key", "error")
                    if skip_on_failure:
                        return
                    raise ValueError("Could not extract reCAPTCHA site key")
                
                # Get the page URL
                page_url = page.url
                
                # Solve captcha using external service
                solution = await self._solve_captcha_with_external_service(
                    service_name, 
                    api_key, 
                    site_key, 
                    page_url,
                    captcha_type,
                    max_wait_time
                )
                
                if not solution:
                    self._update_status("Failed to get captcha solution from external service", "error")
                    if skip_on_failure:
                        return
                    raise ValueError("Failed to get captcha solution from external service")
                
                # Apply the solution
                await self._apply_captcha_solution(page, solution, captcha_type)
                self._update_status("Applied captcha solution from external service", "captcha", {"status": "success"})
                return
            except Exception as e:
                self._update_status(f"Error using external captcha service: {str(e)}", "error")
                if skip_on_failure:
                    return
                raise
        
        # Manual method (default)
        max_retries = 3
        
        # Different approaches based on captcha type
        if captcha_type == 'checkbox':
            for attempt in range(max_retries):
                try:
                    if frame_selector:
                        # If the captcha is in an iframe, we need to handle it differently
                        self._update_status("Captcha is in an iframe, navigating to it", "captcha")
                        
                        # Wait for the frame to be available
                        frame = await page.wait_for_selector(frame_selector)
                        if not frame:
                            raise ValueError(f"Captcha frame not found with selector: {frame_selector}")
                        
                        # Get the iframe's content frame
                        content_frame = await frame.content_frame()
                        if not content_frame:
                            raise ValueError("Could not get content frame from iframe")
                        
                        # Now find the checkbox within the frame
                        checkbox_selector = selector or 'span[role="checkbox"]'
                        checkbox = await content_frame.wait_for_selector(checkbox_selector, timeout=5000)
                        if not checkbox:
                            raise ValueError(f"Captcha checkbox not found in frame with selector: {checkbox_selector}")
                        
                        # Ensure it's visible before clicking
                        await checkbox.scroll_into_view_if_needed()
                        await asyncio.sleep(0.5)
                        
                        # Click the checkbox
                        await checkbox.click()
                        await asyncio.sleep(1.0)  # Wait for potential animations
                        
                        # Check if it was successful
                        is_checked = await content_frame.evaluate(f"""
                            (selector) => {{
                                const el = document.querySelector(selector);
                                if (el) {{
                                    return el.getAttribute('aria-checked') === 'true' || 
                                           el.getAttribute('aria-selected') === 'true' || 
                                           el.checked === true;
                                }}
                                return false;
                            }}
                        """, checkbox_selector)
                        
                        if is_checked:
                            self._update_status("Captcha checkbox successfully checked", "captcha", {"status": "success"})
                            return
                    else:
                        # Direct approach for captchas in the main page
                        self._update_status(f"Looking for captcha checkbox with selector: {selector}", "captcha")
                        
                        # Use a more general selector if none provided
                        if not selector:
                            selector = '[role="checkbox"], .recaptcha-checkbox, .g-recaptcha'
                        
                        # Try multiple methods to find and interact with the captcha
                        
                        # Method 1: Direct selector
                        element = await page.wait_for_selector(selector, timeout=5000, state="visible")
                        if element:
                            self._update_status("Found captcha checkbox, scrolling to it", "captcha")
                            await element.scroll_into_view_if_needed()
                            await asyncio.sleep(0.5)
                            
                            # Try to get if it's already checked
                            is_checked = await element.evaluate("""
                                (el) => {
                                    return el.getAttribute('aria-checked') === 'true' || 
                                           el.getAttribute('aria-selected') === 'true' || 
                                           el.checked === true;
                                }
                            """)
                            
                            if not is_checked:
                                # Click the element
                                await element.click(force=True)
                                await asyncio.sleep(1.0)  # Wait for animations
                                
                                # Check if successful
                                is_checked = await element.evaluate("""
                                    (el) => {
                                        return el.getAttribute('aria-checked') === 'true' || 
                                               el.getAttribute('aria-selected') === 'true' || 
                                               el.checked === true;
                                    }
                                """)
                                
                                if is_checked:
                                    self._update_status("Captcha checkbox successfully checked", "captcha", {"status": "success"})
                                    return
                            else:
                                self._update_status("Captcha checkbox was already checked", "captcha", {"status": "success"})
                                return
                        
                        # Method 2: Look for iframes containing reCAPTCHA
                        recaptcha_frames = await page.query_selector_all('iframe[src*="recaptcha"]')
                        if recaptcha_frames:
                            for frame_elem in recaptcha_frames:
                                try:
                                    content_frame = await frame_elem.content_frame()
                                    if content_frame:
                                        # Look for the checkbox in this frame
                                        checkbox = await content_frame.wait_for_selector('span[role="checkbox"]', timeout=2000)
                                        if checkbox:
                                            await checkbox.click()
                                            await asyncio.sleep(1.0)
                                            is_checked = await content_frame.evaluate("""
                                                () => {
                                                    const el = document.querySelector('span[role="checkbox"]');
                                                    return el && el.getAttribute('aria-checked') === 'true';
                                                }
                                            """)
                                            
                                            if is_checked:
                                                self._update_status("Captcha checkbox in iframe successfully checked", "captcha", {"status": "success"})
                                                return
                                except Exception as iframe_error:
                                    self._update_status(f"Error with iframe approach: {str(iframe_error)}", "warn")
                                    continue
                        
                        # Method 3: Use JavaScript to find and click
                        js_result = await page.evaluate("""
                            () => {
                                // Try various selectors for captcha checkboxes
                                const selectors = [
                                    '[role="checkbox"]', 
                                    '.recaptcha-checkbox', 
                                    '.g-recaptcha',
                                    'iframe[src*="recaptcha"]',
                                    '#recaptcha-anchor'
                                ];
                                
                                for (const selector of selectors) {
                                    const elements = document.querySelectorAll(selector);
                                    for (const el of elements) {
                                        try {
                                            // If it's an iframe, we can't click directly
                                            if (el.tagName.toLowerCase() === 'iframe') {
                                                // Just report we found an iframe
                                                return { success: false, message: 'Found reCAPTCHA iframe but cannot interact directly' };
                                            }
                                            
                                            // Otherwise click the element
                                            el.click();
                                            
                                            // Check if it worked
                                            const isChecked = 
                                                el.getAttribute('aria-checked') === 'true' || 
                                                el.getAttribute('aria-selected') === 'true' || 
                                                el.checked === true;
                                                
                                            if (isChecked) {
                                                return { success: true, message: 'Captcha checkbox clicked successfully via JavaScript' };
                                            }
                                        } catch (e) {
                                            console.error('Error clicking captcha:', e);
                                        }
                                    }
                                }
                                
                                return { success: false, message: 'No captcha elements found with JavaScript' };
                            }
                        """)
                        
                        if js_result.get('success'):
                            self._update_status(js_result.get('message'), "captcha", {"status": "success"})
                            return
                
                except Exception as e:
                    self._update_status(f"Captcha handling error (attempt {attempt+1}/{max_retries}): {str(e)}", "warn")
                    if attempt == max_retries - 1:
                        self._update_status("Failed to handle captcha after multiple attempts", "error")
                        if skip_on_failure:
                            return
                    await asyncio.sleep(1.0)
        
        elif captcha_type == 'recaptcha_v2':
            # Handle more complex reCAPTCHA v2 with image selection challenges
            if solving_method == 'manual':
                self._update_status("reCAPTCHA v2 with challenges detected - manual method not suitable", "captcha", {"status": "warn"})
                
                # If the step has a skip_on_failure flag, we can continue
                if skip_on_failure:
                    self._update_status("Skipping complex captcha as configured", "captcha")
                    return
                
                # Otherwise we can only attempt to click the checkbox and hope it passes
                try:
                    # Try to find the initial checkbox frame
                    frames = await page.query_selector_all('iframe[src*="recaptcha"]')
                    if frames:
                        for frame_elem in frames:
                            try:
                                frame = await frame_elem.content_frame()
                                if frame:
                                    checkbox = await frame.query_selector('span[role="checkbox"]')
                                    if checkbox:
                                        await checkbox.click()
                                        self._update_status("Clicked reCAPTCHA checkbox, but cannot solve challenges", "captcha", {"status": "warn"})
                                        # Wait a bit longer to see if it passes without a challenge
                                        await asyncio.sleep(3.0)
                            except Exception:
                                continue
                except Exception as e:
                    self._update_status(f"Error attempting reCAPTCHA v2: {str(e)}", "error")
                    if not skip_on_failure:
                        raise
            
        else:
            self._update_status(f"Unsupported captcha type: {captcha_type}", "error")
            if skip_on_failure:
                return
            raise ValueError(f"Unsupported captcha type: {captcha_type}")
    
    async def _extract_recaptcha_key(self, page):
        """Extract reCAPTCHA site key from the page"""
        try:
            # Try multiple methods to extract the site key
            site_key = await page.evaluate("""
                () => {
                    // Method 1: Look for g-recaptcha elements with data-sitekey
                    const recaptchaElements = document.querySelectorAll('.g-recaptcha[data-sitekey], [class*=recaptcha][data-sitekey]');
                    if (recaptchaElements.length > 0) {
                        return recaptchaElements[0].getAttribute('data-sitekey');
                    }
                    
                    // Method 2: Look for grecaptcha in window object and try to extract key
                    if (window.grecaptcha && window.grecaptcha.render) {
                        // This is more complex as it's in the rendered parameters
                        const recaptchaDiv = document.querySelector('.g-recaptcha');
                        if (recaptchaDiv) {
                            return recaptchaDiv.getAttribute('data-sitekey');
                        }
                    }
                    
                    // Method 3: Look in the page source
                    const scripts = document.querySelectorAll('script');
                    for (const script of scripts) {
                        const text = script.textContent || script.innerText || '';
                        const match = text.match(/('sitekey'|"sitekey"|sitekey)(\s*):(\s*)(['"`])((\\.|[^\\])*?)\4/i);
                        if (match && match[5]) {
                            return match[5];
                        }
                    }
                    
                    // Method 4: Search in script src attributes
                    for (const script of scripts) {
                        const src = script.getAttribute('src') || '';
                        if (src.includes('recaptcha')) {
                            const match = src.match(/[?&]k=([^&]+)/i);
                            if (match && match[1]) {
                                return match[1];
                            }
                        }
                    }
                    
                    // Method 5: Look for recaptcha iframe and extract from src
                    const recaptchaIframes = document.querySelectorAll('iframe[src*="recaptcha"]');
                    for (const iframe of recaptchaIframes) {
                        const src = iframe.getAttribute('src') || '';
                        const match = src.match(/[?&]k=([^&]+)/i);
                        if (match && match[1]) {
                            return match[1];
                        }
                    }
                    
                    return null;
                }
            """)
            
            if site_key:
                self._update_status(f"Found reCAPTCHA site key: {site_key}", "captcha")
                return site_key
                
            self._update_status("Could not find reCAPTCHA site key with JavaScript", "warn")
            return None
            
        except Exception as e:
            self._update_status(f"Error extracting reCAPTCHA site key: {str(e)}", "error")
            return None
    
    async def _solve_captcha_with_external_service(self, service_name, api_key, site_key, page_url, captcha_type, max_wait_time):
        """Solve captcha using an external service"""
        try:
            import aiohttp
            import json
            import time
            
            start_time = time.time()
            self._update_status(f"Starting captcha solution request with {service_name}", "captcha")
            
            # API endpoints for different services
            service_endpoints = {
                '2Captcha': {
                    'submit': 'https://2captcha.com/in.php',
                    'retrieve': 'https://2captcha.com/res.php'
                },
                'Anti-Captcha': {
                    'submit': 'https://api.anti-captcha.com/createTask',
                    'retrieve': 'https://api.anti-captcha.com/getTaskResult'
                },
                'CapMonster': {
                    'submit': 'https://api.capmonster.cloud/createTask',
                    'retrieve': 'https://api.capmonster.cloud/getTaskResult'
                }
            }
            
            if service_name not in service_endpoints:
                self._update_status(f"Unknown captcha service: {service_name}", "error")
                return None
            
            # Prepare the request data
            task_data = None
            task_id = None
            
            # Using aiohttp for non-blocking HTTP requests
            async with aiohttp.ClientSession() as session:
                # Submit the captcha task
                if service_name == '2Captcha':
                    # 2Captcha API
                    params = {
                        'key': api_key,
                        'method': 'userrecaptcha',
                        'googlekey': site_key,
                        'pageurl': page_url,
                        'json': 1
                    }
                    async with session.get(service_endpoints[service_name]['submit'], params=params) as response:
                        result = await response.json()
                        if result.get('status') == 1:
                            task_id = result.get('request')
                        else:
                            self._update_status(f"Error from {service_name}: {result.get('error_text', 'Unknown error')}", "error")
                            return None
                else:
                    # Anti-Captcha/CapMonster API
                    data = {
                        'clientKey': api_key,
                        'task': {
                            'type': 'NoCaptchaTaskProxyless',
                            'websiteURL': page_url,
                            'websiteKey': site_key
                        }
                    }
                    async with session.post(service_endpoints[service_name]['submit'], json=data) as response:
                        result = await response.json()
                        if service_name == 'Anti-Captcha':
                            if result.get('errorId') == 0:
                                task_id = result.get('taskId')
                            else:
                                self._update_status(f"Error from {service_name}: {result.get('errorDescription', 'Unknown error')}", "error")
                                return None
                        else:  # CapMonster
                            if result.get('errorId') == 0:
                                task_id = result.get('taskId')
                            else:
                                self._update_status(f"Error from {service_name}: {result.get('errorCode', 'Unknown error')}", "error")
                                return None
                
                # If we have a task ID, poll for results
                if task_id:
                    self._update_status(f"Captcha task submitted, waiting for solution (task ID: {task_id})", "captcha")
                    # Poll with increasing delays
                    wait_time = 5  # Start with 5 seconds
                    
                    while time.time() - start_time < max_wait_time:
                        # Wait before polling
                        await asyncio.sleep(wait_time)
                        
                        # Adjust wait time for next poll
                        wait_time = min(wait_time * 1.5, 15)  # Increase wait time but cap at 15 seconds
                        
                        self._update_status(f"Checking captcha solution status (elapsed: {int(time.time() - start_time)}s)", "captcha")
                        
                        # Poll for results
                        if service_name == '2Captcha':
                            params = {
                                'key': api_key,
                                'action': 'get',
                                'id': task_id,
                                'json': 1
                            }
                            async with session.get(service_endpoints[service_name]['retrieve'], params=params) as response:
                                result = await response.json()
                                if result.get('status') == 1:
                                    # We have a solution
                                    solution = result.get('request')
                                    self._update_status(f"Captcha solved successfully in {int(time.time() - start_time)}s", "captcha", {"status": "success"})
                                    return solution
                                elif result.get('request') != 'CAPCHA_NOT_READY':
                                    # Some error occurred
                                    self._update_status(f"Error from {service_name}: {result.get('request', 'Unknown error')}", "error")
                                    return None
                        else:
                            # Anti-Captcha/CapMonster API
                            data = {
                                'clientKey': api_key,
                                'taskId': task_id
                            }
                            async with session.post(service_endpoints[service_name]['retrieve'], json=data) as response:
                                result = await response.json()
                                if result.get('errorId') == 0 and result.get('status') == 'ready':
                                    # We have a solution
                                    solution = result.get('solution', {}).get('gRecaptchaResponse')
                                    self._update_status(f"Captcha solved successfully in {int(time.time() - start_time)}s", "captcha", {"status": "success"})
                                    return solution
                                elif result.get('errorId') != 0:
                                    # Some error occurred
                                    error_msg = result.get('errorDescription', 'Unknown error')
                                    if service_name == 'CapMonster':
                                        error_msg = result.get('errorCode', 'Unknown error')
                                    self._update_status(f"Error from {service_name}: {error_msg}", "error")
                                    return None
                    
                    # If we get here, we've timed out
                    self._update_status(f"Timed out waiting for captcha solution after {max_wait_time}s", "error")
                    return None
                else:
                    self._update_status("Failed to submit captcha task", "error")
                    return None
        
        except Exception as e:
            self._update_status(f"Error using external captcha service: {str(e)}", "error")
            return None
    
    async def _apply_captcha_solution(self, page, solution, captcha_type):
        """Apply the captcha solution to the page"""
        if captcha_type == 'recaptcha_v2':
            try:
                # Set the g-recaptcha-response textarea
                await page.evaluate(f"""
                    (solution) => {{
                        // Create a textarea or find existing one if the challenge is active
                        const existing = document.querySelector('textarea#g-recaptcha-response');
                        
                        if (existing) {{
                            // If the textarea already exists, just set its value
                            existing.value = solution;
                        }} else {{
                            // Create a new textarea if needed
                            const textarea = document.createElement('textarea');
                            textarea.id = 'g-recaptcha-response';
                            textarea.name = 'g-recaptcha-response';
                            textarea.className = 'g-recaptcha-response';
                            textarea.style.display = 'none';
                            textarea.value = solution;
                            document.body.appendChild(textarea);
                        }}
                        
                        // Trigger events to make the site recognize the solved captcha
                        document.dispatchEvent(new Event('captcha-solution'));
                        
                        // Try to trigger success callbacks
                        if (window.___grecaptcha_cfg && window.___grecaptcha_cfg.clients) {{
                            const clients = Object.values(window.___grecaptcha_cfg.clients);
                            for (const client of clients) {{
                                try {{
                                    // Different versions of reCAPTCHA have different structures
                                    // Try to find and call the callback
                                    if (client && client.iY) {{
                                        const callback = client.iY.callback;
                                        if (typeof callback === 'function') {{
                                            callback(solution);
                                        }}
                                    }}
                                }} catch (e) {{
                                    console.error('Error triggering reCAPTCHA callback:', e);
                                }}
                            }}
                        }}
                        
                        return true;
                    }}
                """, solution)
                
                # Wait a moment for any callbacks to execute
                await asyncio.sleep(2.0)
                
                # Try to find and click any submit buttons that might have been enabled
                await page.evaluate("""
                    () => {
                        // Look for newly enabled submit buttons
                        const buttons = document.querySelectorAll('button:not([disabled]), input[type="submit"]:not([disabled])');
                        for (const button of buttons) {
                            // Check if it's visible
                            const style = window.getComputedStyle(button);
                            if (style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0') {
                                // Might be a submit button that was enabled after solving captcha
                                // Don't click automatically, as it might submit a form before all fields are filled
                                // Just return that we found an enabled button
                                return true;
                            }
                        }
                        return false;
                    }
                """)
                
                return True
            except Exception as e:
                self._update_status(f"Error applying captcha solution: {str(e)}", "error")
                return False
        else:
            self._update_status(f"Unsupported captcha type: {captcha_type}", "error")
            raise ValueError(f"Unsupported captcha type: {captcha_type}") 

    def _generate_random_value(self, value_type: str, **kwargs) -> str:
        """Generate a random value based on the specified type."""
        if value_type == "First Name":
            return random.choice([
                "Jan", "Piet", "Klaas", "Henk", "Wim", "Hans", "Peter", "Paul", "Mark", "Thomas",
                "Emma", "Sophie", "Julia", "Lisa", "Anna", "Maria", "Sarah", "Laura", "Eva", "Sophia"
            ])
        elif value_type == "Last Name":
            return random.choice([
                "de Vries", "van de Berg", "van Dijk", "Bakker", "Janssen", "Visser", "Smit", "Meijer", "de Boer", "Mulder",
                "de Groot", "Bos", "Vos", "Peters", "Hendriks", "van Leeuwen", "Dekker", "Dijkstra", "Smits", "de Graaf"
            ])
        elif value_type == "Email Address":
            first_name = self._generate_random_value("First Name").lower()
            last_name = self._generate_random_value("Last Name").lower().replace(" ", "")
            domains = ["gmail.com", "hotmail.com", "outlook.com", "yahoo.com", "icloud.com"]
            return f"{first_name}.{last_name}@{random.choice(domains)}"
        elif value_type == "Password":
            min_length = kwargs.get('password_min_length', 12)
            max_length = kwargs.get('password_max_length', 16)
            length = random.randint(min_length, max_length)
            
            # Define character sets
            lowercase = string.ascii_lowercase
            uppercase = string.ascii_uppercase if kwargs.get('password_include_uppercase', True) else ""
            digits = string.digits if kwargs.get('password_include_numbers', True) else ""
            special = "!@#$%^&*" if kwargs.get('password_include_special', True) else ""
            
            # Ensure at least one of each required character type
            password = [
                random.choice(lowercase),
                random.choice(uppercase) if uppercase else random.choice(lowercase),
                random.choice(digits) if digits else random.choice(lowercase),
                random.choice(special) if special else random.choice(lowercase)
            ]
            
            # Fill the rest randomly
            all_chars = lowercase + uppercase + digits + special
            while len(password) < length:
                password.append(random.choice(all_chars))
            
            # Shuffle the password
            random.shuffle(password)
            return "".join(password)
        elif value_type == "Generic Term":
            return random.choice([
                "test", "example", "sample", "demo", "trial", "check", "verify", "validate", "confirm", "review",
                "inspect", "examine", "assess", "evaluate", "analyze", "study", "research", "investigate", "explore", "probe"
            ])
        elif value_type == "Street Name":
            # Define street names per city for consistency
            city_streets = {
                "Amsterdam": [
                    "Damstraat", "Kalverstraat", "Nieuwendijk", "Damrak", "Rokin",
                    "Leidsestraat", "Utrechtsestraat", "Spuistraat", "Nieuwezijds Voorburgwal", "Dam"
                ],
                "Rotterdam": [
                    "Coolsingel", "Lijnbaan", "Hoogstraat", "Beursplein", "Binnenwegplein",
                    "Meent", "Witte de Withstraat", "Coolsingel", "Blaak", "Witte de Withstraat"
                ],
                "Den Haag": [
                    "Spuistraat", "Grote Marktstraat", "Lange Poten", "Plein", "Hofweg",
                    "Noordeinde", "Lange Vijverberg", "Plein", "Spui", "Hofweg"
                ],
                "Utrecht": [
                    "Oudegracht", "Hoog Catharijne", "Vredenburg", "Lange Viestraat", "Oudegracht",
                    "Domstraat", "Neude", "Vredenburg", "Lange Viestraat", "Domstraat"
                ],
                "Eindhoven": [
                    "Demer", "Rechtestraat", "Hooghuisstraat", "18 Septemberplein", "Stratumseind",
                    "Kleine Berg", "Heuvel", "18 Septemberplein", "Stratumseind", "Kleine Berg"
                ]
            }
            
            # Get the city from the context or use a default
            city = kwargs.get('city', random.choice(list(city_streets.keys())))
            streets = city_streets.get(city, [
                "Hoofdstraat", "Kerkstraat", "Schoolstraat", "Stationsstraat", "Marktstraat",
                "Dorpsstraat", "Molenstraat", "Beekstraat", "Burgemeesterstraat", "Industrieweg"
            ])
            
            house_number = random.randint(1, 999)
            return f"{random.choice(streets)} {house_number}"
        elif value_type == "Postal Code":
            country = kwargs.get('postal_code_country', 'NL')
            city = kwargs.get('city')
            
            # Define postal code ranges for major cities
            city_postcodes = {
                "Amsterdam": (1000, 1109),
                "Rotterdam": (3000, 3089),
                "Den Haag": (2500, 2599),
                "Utrecht": (3500, 3585),
                "Eindhoven": (5600, 5658)
            }
            
            if city and city in city_postcodes:
                min_code, max_code = city_postcodes[city]
                postal_code = random.randint(min_code, max_code)
                return f"{postal_code} {random.choice(string.ascii_uppercase)}{random.choice(string.ascii_uppercase)}"
            
            # Fallback to general postal code format if city is not in our list
            postal_code_formats = {
                'NL': lambda: f"{random.randint(1000, 9999)} {random.choice(string.ascii_uppercase)}{random.choice(string.ascii_uppercase)}",
                'BE': lambda: f"{random.randint(1000, 9999)}",
                'DE': lambda: f"{random.randint(10000, 99999)}",
                'FR': lambda: f"{random.randint(10000, 99999)}",
                'GB': lambda: f"{random.choice(string.ascii_uppercase)}{random.choice(string.ascii_uppercase)}{random.randint(1, 99)} {random.randint(1, 9)}{random.choice(string.ascii_uppercase)}{random.choice(string.ascii_uppercase)}"
            }
            return postal_code_formats.get(country, lambda: f"{random.randint(10000, 99999)}")()
        elif value_type == "City Name":
            # Define cities for different countries
            cities = {
                'NL': [
                    "Amsterdam", "Rotterdam", "Den Haag", "Utrecht", "Eindhoven",
                    "Groningen", "Tilburg", "Almere", "Breda", "Nijmegen",
                    "Enschede", "Haarlem", "Amersfoort", "Arnhem", "Zaanstad",
                    "Den Bosch", "Zwolle", "Maastricht", "Leiden", "Alkmaar"
                ],
                'BE': [
                    "Brussel", "Antwerpen", "Gent", "Charleroi", "Luik",
                    "Brugge", "Sint-Niklaas", "Aalst", "Mechelen", "Kortrijk",
                    "Hasselt", "Oostende", "Genk", "Roeselare", "Turnhout",
                    "Dendermonde", "Beveren", "Bilzen", "Lokeren", "Geel"
                ],
                'DE': [
                    "Berlijn", "Hamburg", "München", "Keulen", "Frankfurt",
                    "Stuttgart", "Düsseldorf", "Dortmund", "Essen", "Leipzig",
                    "Dresden", "Hannover", "Nürnberg", "Duisburg", "Bochum",
                    "Wuppertal", "Bielefeld", "Bonn", "Münster", "Karlsruhe"
                ],
                'FR': [
                    "Parijs", "Marseille", "Lyon", "Toulouse", "Nice",
                    "Nantes", "Strasbourg", "Montpellier", "Bordeaux", "Lille",
                    "Rennes", "Reims", "Le Havre", "Saint-Étienne", "Toulon",
                    "Grenoble", "Dijon", "Angers", "Nîmes", "Villeurbanne"
                ],
                'GB': [
                    "Londen", "Manchester", "Birmingham", "Leeds", "Glasgow",
                    "Sheffield", "Edinburgh", "Liverpool", "Bristol", "Cardiff",
                    "Belfast", "Nottingham", "Hull", "Newcastle", "Stoke-on-Trent",
                    "Coventry", "Sunderland", "Birkenhead", "Islington", "Reading"
                ]
            }
            country = kwargs.get('postal_code_country', 'NL')
            return random.choice(cities.get(country, cities['NL']))
        elif value_type == "Phone Number":
            country = kwargs.get('postal_code_country', 'NL')
            city = kwargs.get('city')
            
            # Define area codes for major cities
            city_area_codes = {
                "Amsterdam": "020",
                "Rotterdam": "010",
                "Den Haag": "070",
                "Utrecht": "030",
                "Eindhoven": "040"
            }
            
            if city and city in city_area_codes:
                area_code = city_area_codes[city]
                return f"+31 {area_code} {random.randint(1000000, 9999999)}"
            
            # Fallback to general phone number format if city is not in our list
            phone_formats = {
                'NL': lambda: f"+31 {random.randint(6, 7)}{random.randint(1000000, 9999999)}",
                'BE': lambda: f"+32 {random.randint(400, 499)}{random.randint(100000, 999999)}",
                'DE': lambda: f"+49 {random.randint(100, 999)}{random.randint(1000000, 9999999)}",
                'FR': lambda: f"+33 {random.randint(1, 9)}{random.randint(10000000, 99999999)}",
                'GB': lambda: f"+44 {random.randint(7000000000, 7999999999)}"
            }
            return phone_formats.get(country, lambda: f"+{random.randint(1, 99)} {random.randint(100000000, 999999999)}")()
        elif value_type == "Random Number":
            min_val = kwargs.get('random_number_min', 0)
            max_val = kwargs.get('random_number_max', 100)
            decimals = kwargs.get('random_number_decimals', 0)
            value = random.uniform(min_val, max_val)
            return f"{value:.{decimals}f}"
        else:
            return "Invalid value type"