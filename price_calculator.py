from playwright.async_api import async_playwright, Page, expect
from typing import Dict, Any, Optional, Tuple, List
from domain_config import DomainConfig
import logging
import re

class PriceCalculator:
    """Calculate prices based on dimensions for different domains"""
    
    def __init__(self, domain_config: DomainConfig):
        """Initialize calculator with domain configuration"""
        self.domain_config = domain_config
        logging.info("Initialiseren PriceCalculator...")

    async def calculate_price(self, url: str, dimensions: Dict[str, float]) -> Tuple[float, float]:
        """Calculate price based on dimensions using domain configuration"""
        logging.info(f"\n{'='*50}")
        logging.info(f"Start prijsberekening voor {url}")
        logging.info(f"Input dimensies: {dimensions}")
        
        # Convert dimension names to match configuration
        converted_dimensions = {
            'thickness': dimensions.get('dikte', 0),
            'length': dimensions.get('lengte', 0),
            'width': dimensions.get('breedte', 0)
        }
        logging.info(f"Omgezette dimensies: {converted_dimensions}")
        
        config = self.domain_config.get_config(url)
        if not config:
            raise ValueError(f"No configuration found for URL: {url}")
        logging.info(f"Gevonden configuratie: {config}")

        async with async_playwright() as p:
            logging.info("Starting browser...")
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            try:
                # Wacht tot de pagina volledig geladen is
                logging.info(f"Navigeren naar {url}")
                await page.goto(url, wait_until="networkidle")
                
                logging.info("Pagina geladen, wachten op stabilisatie...")
                await page.wait_for_load_state("domcontentloaded")
                await page.wait_for_timeout(2000)
                
                # Convert dimensions based on domain units
                converted_units = self._convert_dimensions(converted_dimensions, config['units'])
                logging.info(f"Dimensies omgezet naar juiste eenheden: {converted_units}")
                
                # Fill in dimensions
                logging.info("\nInvullen van dimensies:")
                for field_type, value in converted_units.items():
                    field_config = config['selectors'].get(field_type)
                    if not field_config or not field_config['exists']:
                        continue
                        
                    try:
                        logging.info(f"\nZoeken naar {field_type} veld met selector: {field_config['selector']}")
                        # Wacht tot het element zichtbaar en enabled is
                        element = await page.wait_for_selector(field_config['selector'], state="visible", timeout=5000)
                        
                        if field_config['type'] == 'select':
                            await self._fill_select_field(page, field_config['selector'], value)
                        else:
                            logging.info(f"Input veld gevonden, waarde invullen: {value}")
                            await element.fill(str(value))
                            await element.evaluate('(el) => { el.dispatchEvent(new Event("change", { bubbles: true })); el.dispatchEvent(new Event("input", { bubbles: true })); }')
                        
                        # Wacht na elke veld invulling
                        await page.wait_for_timeout(1000)
                    except Exception as e:
                        await browser.close()
                        raise ValueError(f"Error bij invullen van {field_type}: {str(e)}")
                
                # Wacht tot prijs update
                try:
                    logging.info("\nWachten op prijs update:")
                    price_config = config['price']
                    logging.info(f"Zoeken naar prijs element met selector: {price_config['selector']}")
                    
                    # Wacht tot prijs element zichtbaar is
                    await page.wait_for_selector(price_config['selector'], state="visible", timeout=5000)
                    price_element = await page.query_selector(price_config['selector'])
                    
                    if price_element:
                        # Wacht op mogelijke prijs updates
                        initial_price = await price_element.text_content()
                        logging.info(f"Initiële prijs tekst: '{initial_price}'")
                        
                        # Wacht maximaal 5 seconden op prijswijziging
                        max_attempts = 10
                        for attempt in range(max_attempts):
                            await page.wait_for_timeout(500)
                            current_price = await price_element.text_content()
                            
                            if current_price != initial_price:
                                logging.info(f"Prijs gewijzigd van '{initial_price}' naar '{current_price}'")
                                break
                            elif attempt == max_attempts - 1:
                                logging.info("Geen prijswijziging gedetecteerd na wachten")
                        
                        price = self._extract_price(current_price)
                        logging.info(f"Geëxtraheerde prijs: {price}")
                        
                        if price_config['includes_vat']:
                            logging.info("Prijs is inclusief BTW, berekenen excl. BTW")
                            price_incl_vat = price
                            price_excl_vat = price / 1.21
                        else:
                            logging.info("Prijs is exclusief BTW, berekenen incl. BTW")
                            price_excl_vat = price
                            price_incl_vat = price * 1.21
                        
                        # Rond de prijzen af op 2 decimalen
                        price_excl_vat = round(price_excl_vat, 2)
                        price_incl_vat = round(price_incl_vat, 2)
                        
                        logging.info(f"Finale prijzen: €{price_excl_vat:.2f} ex BTW / €{price_incl_vat:.2f} incl BTW")
                        await browser.close()
                        return price_excl_vat, price_incl_vat
                    else:
                        logging.error("Prijs element niet gevonden")
                except Exception as e:
                    logging.error(f"Error bij ophalen prijs: {str(e)}")
                
                await browser.close()
                return 0, 0
            except Exception as e:
                await browser.close()
                raise ValueError(f"Error bij berekenen prijs: {str(e)}")

    async def _detect_unit(self, page) -> bool:
        """Detecteert of de pagina centimeters of millimeters gebruikt"""
        try:
            # Zoek eerst in de buurt van het formulier
            form_area_selectors = [
                "form",
                ".form",
                ".calculator",
                "#calculator",
                ".product-options",
                ".configurator"
            ]
            
            for selector in form_area_selectors:
                try:
                    elements = await page.query_selector_all(selector)
                    for element in elements:
                        text = await element.inner_text()
                        text = text.lower()
                        if any(term in text for term in ['cm', 'centimeter', 'centimeters']):
                            print("Centimeters (cm) gedetecteerd in formulier gebied")
                            return True
                        elif any(term in text for term in ['mm', 'millimeter', 'millimeters']):
                            print("Millimeters (mm) gedetecteerd in formulier gebied")
                            return False
                except Exception as e:
                    print(f"Error bij zoeken in formulier gebied: {str(e)}")
                    continue
            
            # Als nog geen eenheid gevonden, zoek in labels
            content = await page.content()
            if not any(term in content.lower() for term in ['cm', 'centimeter', 'centimeters', 'mm', 'millimeter', 'millimeters']):
                elements = await page.query_selector_all("label, .form-label, .input-label, .field-label")
                for element in elements:
                    try:
                        text = await element.inner_text()
                        text = text.lower()
                        if any(term in text for term in ['cm', 'centimeter', 'centimeters']):
                            print("Centimeters (cm) gedetecteerd in labels")
                            return True
                        elif any(term in text for term in ['mm', 'millimeter', 'millimeters']):
                            print("Millimeters (mm) gedetecteerd in labels")
                            return False
                    except Exception as e:
                        print(f"Error bij label check: {str(e)}")
                        continue
            
            # Standaard millimeters
            return False
            
        except Exception as e:
            print(f"Error bij eenheid detectie: {str(e)}")
            return False

    async def _fill_dimension_field(self, page, field_info, value, uses_centimeters):
        """Vult een dimensie veld in"""
        try:
            # Voor select velden laten we de eenheid conversie over aan _handle_select_field
            if field_info['tag'] == 'select':
                success = await self._handle_select_field(page, field_info, value)
                if not success:
                    print(f"Kon geen passende optie vinden voor waarde {value}mm in {field_info.get('label', 'select veld')}")
                    return False
            else:
                # Alleen voor gewone input velden converteren we naar cm indien nodig
                display_value = value
                if uses_centimeters:
                    display_value = value / 10  # mm naar cm
                    print(f"Waarde geconverteerd van {value}mm naar {display_value}cm")

                selector = f"#{field_info['id']}"
                input_element = await page.wait_for_selector(selector)
                await input_element.fill(str(display_value))
                await input_element.evaluate('element => element.blur()')
                await page.wait_for_timeout(500)

            return True

        except Exception as e:
            print(f"Error bij invullen veld: {str(e)}")
            return False

    async def _handle_select_field(self, page, field_info, value):
        """Handelt select velden af"""
        try:
            selector = f"#{field_info['id']}"
            if not await page.query_selector(selector):
                # Als we het veld niet direct kunnen vinden, probeer alternatieve selectors
                alternative_selectors = [
                    "select:has(option:has-text('mm'))",
                    "select.variation__select",
                    "[class*='variation'] select",
                    "select:has-text('dikte')",
                    "select:has-text('Dikte')"
                ]
                for alt_selector in alternative_selectors:
                    element = await page.query_selector(alt_selector)
                    if element:
                        selector = alt_selector
                        break

            # Haal alle opties op
            options = await page.evaluate(f"""
                () => {{
                    const select = document.querySelector('{selector}');
                    if (!select) return [];
                    return Array.from(select.options).map(option => ({{
                        value: option.value,
                        text: option.text.trim()
                    }}));
                }}
            """)

            print(f"\nBeschikbare opties voor {field_info.get('label', 'select veld')}:")
            for opt in options:
                print(f"- {opt['text']} (waarde: {opt['value']})")

            # Zoek de beste match
            best_match = None
            smallest_diff = float('inf')
            target_value = value  # We werken altijd in mm

            for option in options:
                try:
                    # Haal numerieke waarde uit de tekst
                    numeric_match = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:mm|cm)?', option['text'].lower())
                    if numeric_match:
                        option_value = float(numeric_match.group(1).replace(',', '.'))
                        
                        # Als er een eenheid is gespecificeerd, gebruik die
                        if 'cm' in option['text'].lower():
                            option_value *= 10  # Converteer cm naar mm
                        # Als er geen eenheid is, kijk naar de context van het veld
                        elif not any(unit in option['text'].lower() for unit in ['mm', 'cm']):
                            # Kijk naar het label of omliggende tekst voor eenheid indicatie
                            label_text = field_info.get('label', '').lower()
                            if 'cm' in label_text or 'centimeter' in label_text:
                                option_value *= 10  # Converteer cm naar mm
                            # Anders gaan we ervan uit dat het dezelfde eenheid is als onze target

                        diff = abs(option_value - target_value)
                        print(f"Vergelijking: {option_value}mm vs {target_value}mm (verschil: {diff})")
                        
                        if diff < smallest_diff:
                            smallest_diff = diff
                            best_match = option['value']
                            print(f"Nieuwe beste match gevonden: {option['text']} (verschil: {diff})")
                    else:
                        # Probeer pure getallen te matchen (zonder eenheid)
                        pure_number_match = re.search(r'^\s*(\d+(?:[.,]\d+)?)\s*$', option['text'])
                        if pure_number_match:
                            option_value = float(pure_number_match.group(1).replace(',', '.'))
                            # Kijk naar het label of omliggende tekst voor eenheid indicatie
                            label_text = field_info.get('label', '').lower()
                            if 'cm' in label_text or 'centimeter' in label_text:
                                option_value *= 10  # Converteer cm naar mm
                            
                            diff = abs(option_value - target_value)
                            print(f"Vergelijking (puur getal): {option_value}mm vs {target_value}mm (verschil: {diff})")
                            
                            if diff < smallest_diff:
                                smallest_diff = diff
                                best_match = option['value']
                                print(f"Nieuwe beste match gevonden (puur getal): {option['text']} (verschil: {diff})")

                except Exception as e:
                    print(f"Error bij verwerken optie {option['text']}: {str(e)}")
                    continue

            if best_match and smallest_diff < 1.0:  # Alleen accepteren als verschil kleiner is dan 1mm
                await page.select_option(selector, best_match)
                await page.wait_for_timeout(500)
                # Trigger change event
                await page.evaluate('(el) => { el.dispatchEvent(new Event("change")); }')
                logging.info("Optie geselecteerd en change event getriggerd")
                return True
            else:
                print(f"Geen geschikte optie gevonden voor {value}mm")
                return False

        except Exception as e:
            print(f"Error bij select veld: {str(e)}")
            return False

    async def _get_m2_price(self, page: Page) -> Tuple[float, float]:
        """Get the price per m² from the page."""
        print("Zoeken naar m² prijs...")
        
        try:
            # Zoek eerst in de product header waar prijzen vaak staan
            header_selectors = [
                '.product-header',
                '.product-info',
                '.product-details',
                '.product-price-container',
                '[class*="product-header"]',
                '[class*="product-info"]',
                '[class*="price-container"]',
                '.product-price',
                '.product-price-ex',
                '.product-price-inc'
            ]
            
            for selector in header_selectors:
                try:
                    containers = await page.query_selector_all(selector)
                    for container in containers:
                        # Haal alle tekst op uit de container
                        container_text = await container.evaluate('node => node.innerText')
                        if not container_text:
                            continue
                            
                        container_text = container_text.lower().strip()
                        print(f"Gevonden container tekst: {container_text}")
                        
                        # Zoek naar m² prijzen
                        if any(term in container_text for term in ['m²', 'm2', 'vierkante meter']):
                            # Zoek eerst naar excl. BTW prijs
                            if 'excl' in container_text:
                                # Probeer verschillende prijs patronen
                                price_patterns = [
                                    r'€\s*(\d+(?:[.,]\d{2})?)',  # €20,00
                                    r'(\d+(?:[.,]\d{2})?)\s*€',  # 20,00€
                                    r'eur\s*(\d+(?:[.,]\d{2})?)',  # EUR 20,00
                                    r'(\d+(?:[.,]\d{2})?)\s*eur'   # 20,00 EUR
                                ]
                                
                                for pattern in price_patterns:
                                    price_matches = re.findall(pattern, container_text)
                                    if price_matches:
                                        excl_price = float(price_matches[0].replace(',', '.'))
                                        if 5.0 <= excl_price <= 500.0:  # Valideer dat prijs realistisch is
                                            print(f"Gevonden m² prijs (excl. BTW): €{excl_price:.2f}")
                                            return excl_price, excl_price * 1.21
                            
                            # Zoek naar incl. BTW prijs
                            if 'incl' in container_text:
                                # Probeer verschillende prijs patronen
                                price_patterns = [
                                    r'€\s*(\d+(?:[.,]\d{2})?)',  # €20,00
                                    r'(\d+(?:[.,]\d{2})?)\s*€',  # 20,00€
                                    r'eur\s*(\d+(?:[.,]\d{2})?)',  # EUR 20,00
                                    r'(\d+(?:[.,]\d{2})?)\s*eur'   # 20,00 EUR
                                ]
                                
                                for pattern in price_patterns:
                                    price_matches = re.findall(pattern, container_text)
                                    if price_matches:
                                        incl_price = float(price_matches[0].replace(',', '.'))
                                        if 5.0 <= incl_price <= 500.0:  # Valideer dat prijs realistisch is
                                            print(f"Gevonden m² prijs (incl. BTW): €{incl_price:.2f}")
                                            return incl_price / 1.21, incl_price
                except Exception as e:
                    print(f"Error bij container {selector}: {str(e)}")
                    continue
            
            # Als geen prijs gevonden in headers, zoek in alle prijs-gerelateerde containers
            price_selectors = [
                '[class*="price"]',
                '[class*="prijs"]',
                '.price-wrapper',
                '.price-container',
                '.product-price',
                'span',  # Ook in losse span elementen zoeken
                'div'    # En div elementen
            ]
            
            for selector in price_selectors:
                try:
                    containers = await page.query_selector_all(selector)
                    for container in containers:
                        # Haal alle tekst op uit de container
                        container_text = await container.evaluate('node => node.innerText')
                        if not container_text:
                            continue
                            
                        container_text = container_text.lower().strip()
                        print(f"Gevonden prijs container tekst: {container_text}")
                        
                        # Zoek naar m² prijzen
                        if any(term in container_text for term in ['m²', 'm2', 'vierkante meter']):
                            # Zoek eerst naar excl. BTW prijs
                            if 'excl' in container_text:
                                # Probeer verschillende prijs patronen
                                price_patterns = [
                                    r'€\s*(\d+(?:[.,]\d{2})?)',  # €20,00
                                    r'(\d+(?:[.,]\d{2})?)\s*€',  # 20,00€
                                    r'eur\s*(\d+(?:[.,]\d{2})?)',  # EUR 20,00
                                    r'(\d+(?:[.,]\d{2})?)\s*eur'   # 20,00 EUR
                                ]
                                
                                for pattern in price_patterns:
                                    price_matches = re.findall(pattern, container_text)
                                    if price_matches:
                                        excl_price = float(price_matches[0].replace(',', '.'))
                                        if 5.0 <= excl_price <= 500.0:  # Valideer dat prijs realistisch is
                                            print(f"Gevonden m² prijs (excl. BTW): €{excl_price:.2f}")
                                            return excl_price, excl_price * 1.21
                            
                            # Zoek naar incl. BTW prijs
                            if 'incl' in container_text:
                                # Probeer verschillende prijs patronen
                                price_patterns = [
                                    r'€\s*(\d+(?:[.,]\d{2})?)',  # €20,00
                                    r'(\d+(?:[.,]\d{2})?)\s*€',  # 20,00€
                                    r'eur\s*(\d+(?:[.,]\d{2})?)',  # EUR 20,00
                                    r'(\d+(?:[.,]\d{2})?)\s*eur'   # 20,00 EUR
                                ]
                                
                                for pattern in price_patterns:
                                    price_matches = re.findall(pattern, container_text)
                                    if price_matches:
                                        incl_price = float(price_matches[0].replace(',', '.'))
                                        if 5.0 <= incl_price <= 500.0:  # Valideer dat prijs realistisch is
                                            print(f"Gevonden m² prijs (incl. BTW): €{incl_price:.2f}")
                                            return incl_price / 1.21, incl_price
                except Exception as e:
                    print(f"Error bij price container {selector}: {str(e)}")
                    continue
                
            print("Geen directe m² prijs gevonden op de pagina")
            # Return None in plaats van 0.0, 0.0 om aan te geven dat we verder moeten gaan met form-based berekening
            return None
            
        except Exception as e:
            print(f"Error bij zoeken naar m² prijs: {str(e)}")
            return None

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