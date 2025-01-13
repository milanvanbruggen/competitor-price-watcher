import re
from typing import Dict, Optional, Tuple, List
from playwright.async_api import async_playwright, Page

class PriceCalculator:
    def __init__(self):
        print("Initialiseren PriceCalculator...")

    async def calculate_price(self, url: str, dimensions: dict, dimension_fields: dict = None) -> Tuple[float, float]:
        """Calculate price based on dimensions"""
        print(f"\nStart prijsberekening voor {url}")
        
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch()
                page = await browser.new_page()
                await page.goto(url)
                
                # 1. Eerst zoeken naar directe m² prijzen
                print("\nZoeken naar m² prijs zonder formulier interactie...")
                prices = await self._get_m2_price(page)
                if prices is not None:  # Aangepast om None check te doen
                    print(f"Gevonden m² prijzen zonder formulier: €{prices[0]:.2f} ex BTW / €{prices[1]:.2f} incl BTW")
                    await browser.close()
                    return prices

                print("\nGeen directe m² prijs gevonden, proberen via formulier...")
                
                if not dimension_fields:
                    print("Geen dimensie velden gevonden")
                    await browser.close()
                    return 0.0, 0.0

                # 2. Detecteer de eenheid en verzamel initiële prijzen
                uses_centimeters = await self._detect_unit(page)
                print(f"Gebruikte eenheid: {'centimeters' if uses_centimeters else 'millimeters'}")

                # Verzamel eerst alle prijselementen voor vergelijking
                initial_prices = await self._collect_price_elements(page)
                print(f"Aantal prijselementen voor invullen: {len(initial_prices)}")

                # 3. Vul dimensies in en monitor prijsveranderingen
                fields_filled = False
                for field_name, value in dimensions.items():
                    if field_name in dimension_fields and dimension_fields[field_name]:
                        # Vul veld in
                        field_filled = await self._fill_dimension_field(page, dimension_fields[field_name][0], value, uses_centimeters)
                        if not field_filled:
                            print(f"Kon {field_name} niet invullen met waarde {value}")
                            await browser.close()
                            return 0.0, 0.0
                        fields_filled = True
                        
                        # Wacht even en check voor prijsveranderingen
                        await page.wait_for_timeout(1000)
                        current_prices = await self._collect_price_elements(page)
                        changed_prices = self._find_changed_prices(initial_prices, current_prices)
                        
                        # Als we een prijsverandering zien, gebruik deze
                        if changed_prices:
                            price_info = changed_prices[0]
                            price = price_info['price']
                            is_incl = price_info['is_incl']
                            
                            # Converteer naar m² prijs
                            area_m2 = (dimensions['lengte'] / 1000) * (dimensions['breedte'] / 1000)  # mm naar m²
                            if area_m2 > 0:
                                price = round(price / area_m2, 2)
                                
                            if is_incl:
                                excl_btw = round(price / 1.21, 2)
                                incl_btw = price
                            else:
                                excl_btw = price
                                incl_btw = round(price * 1.21, 2)
                            
                            print(f"Prijs per m² gevonden tijdens invullen: €{excl_btw:.2f} ex BTW / €{incl_btw:.2f} incl BTW")
                            await browser.close()
                            return excl_btw, incl_btw
                
                if not fields_filled:
                    print("Geen dimensie velden kunnen invullen")
                    await browser.close()
                    return 0.0, 0.0

                # 4. Wacht op laatste prijsupdate en check nogmaals
                await page.wait_for_timeout(1000)
                final_prices = await self._collect_price_elements(page)
                changed_prices = self._find_changed_prices(initial_prices, final_prices)

                if changed_prices:
                    price_info = changed_prices[0]
                    price = price_info['price']
                    is_incl = price_info['is_incl']
                    
                    # Converteer naar m² prijs
                    area_m2 = (dimensions['lengte'] / 1000) * (dimensions['breedte'] / 1000)  # mm naar m²
                    if area_m2 > 0:
                        price = round(price / area_m2, 2)
                        
                    if is_incl:
                        excl_btw = round(price / 1.21, 2)
                        incl_btw = price
                    else:
                        excl_btw = price
                        incl_btw = round(price * 1.21, 2)
                    
                    print(f"Prijs per m² gevonden na invullen: €{excl_btw:.2f} ex BTW / €{incl_btw:.2f} incl BTW")
                    await browser.close()
                    return excl_btw, incl_btw

                print("Geen prijsveranderingen gedetecteerd")
                await browser.close()
                return 0.0, 0.0
                
        except Exception as e:
            print(f"Error tijdens prijsberekening: {str(e)}")
            raise

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
                        
                        # Converteer naar mm indien nodig
                        if 'cm' in option['text'].lower():
                            option_value *= 10

                        diff = abs(option_value - target_value)
                        print(f"Vergelijking: {option_value}mm vs {target_value}mm (verschil: {diff})")
                        
                        if diff < smallest_diff:
                            smallest_diff = diff
                            best_match = option['value']
                            print(f"Nieuwe beste match gevonden: {option['text']} (verschil: {diff})")

                except Exception as e:
                    print(f"Error bij verwerken optie {option['text']}: {str(e)}")
                    continue

            if best_match and smallest_diff < 1.0:  # Alleen accepteren als verschil kleiner is dan 1mm
                await page.select_option(selector, best_match)
                await page.wait_for_timeout(500)
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

    def _extract_price(self, text: str) -> float:
        """Extraheert prijs uit tekst"""
        if not text:
            return 0.0
        
        text = text.lower()
        
        # Verschillende prijs patronen
        price_patterns = [
            r'€\s*(\d+(?:[.,]\d{2})?)\s*(?:per\s*m[²2]|/\s*m[²2])',  # €10.99 per m² of €10,99/m²
            r'(\d+(?:[.,]\d{2})?)\s*(?:€|eur|euro)\s*(?:per\s*m[²2]|/\s*m[²2])',  # 10.99€ per m²
            r'(?:per\s*m[²2]|/\s*m[²2])\s*€\s*(\d+(?:[.,]\d{2})?)',  # per m² €10.99
        ]
        
        for pattern in price_patterns:
            matches = re.findall(pattern, text)
            if matches:
                # Vervang komma door punt en converteer naar float
                price = float(matches[0].replace(',', '.'))
                # Valideer dat de prijs realistisch is (tussen €5 en €500 per m²)
                if 5.0 <= price <= 500.0:
                    return price
            
        return 0.0

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