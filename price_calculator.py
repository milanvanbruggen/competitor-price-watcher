import re
from typing import Dict, Optional, Tuple, List
from playwright.async_api import async_playwright

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
                if prices:
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
            options = await page.evaluate(f"""
                () => {{
                    const select = document.querySelector('{selector}');
                    return Array.from(select.options).map(option => ({{
                        value: option.value,
                        text: option.text.trim()
                    }}));
                }}
            """)

            # Eerst analyseren we alle opties om de eenheid te bepalen
            mm_count = 0
            cm_count = 0
            for option in options:
                option_text = option['text'].lower()
                if 'mm' in option_text:
                    mm_count += 1
                elif 'cm' in option_text:
                    cm_count += 1

            # Bepaal de eenheid op basis van de opties
            uses_millimeters = mm_count >= cm_count
            print(f"\nEenheid analyse: {mm_count} opties in mm, {cm_count} opties in cm")
            print(f"Standaard eenheid voor vergelijking: {'millimeters' if uses_millimeters else 'centimeters'}")

            best_match = None
            smallest_diff = float('inf')
            
            # Input waarde is altijd in mm, alleen converteren als opties in cm zijn
            compare_value = value if uses_millimeters else value / 10
            print(f"\nZoeken naar beste match voor {compare_value}{'mm' if uses_millimeters else 'cm'}:")

            for option in options:
                try:
                    # Probeer numerieke waarde uit tekst te halen
                    numeric_match = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:mm|cm)?', option['text'].lower())
                    if numeric_match:
                        option_value = float(numeric_match.group(1).replace(',', '.'))
                        option_text = option['text'].lower()
                        
                        # Bepaal de eenheid van deze specifieke optie
                        option_in_mm = 'mm' in option_text
                        option_in_cm = 'cm' in option_text
                        
                        # Als de optie een expliciete eenheid heeft die anders is dan onze standaard,
                        # converteer de optie waarde naar onze standaard eenheid
                        if uses_millimeters and option_in_cm:
                            option_value = option_value * 10  # cm naar mm
                            print(f"Optie {option['text']} geconverteerd van {option_value/10}cm naar {option_value}mm")
                        elif not uses_millimeters and option_in_mm:
                            option_value = option_value / 10  # mm naar cm
                            print(f"Optie {option['text']} geconverteerd van {option_value*10}mm naar {option_value}cm")
                            
                        diff = abs(option_value - compare_value)
                        print(f"Vergelijking: {option['text']} ({option_value}{'mm' if uses_millimeters else 'cm'}) vs {compare_value}{'mm' if uses_millimeters else 'cm'} - verschil: {diff}")
                        
                        # Accepteer alleen matches met een verschil kleiner dan 1.0
                        if diff < 1.0 and diff < smallest_diff:
                            smallest_diff = diff
                            best_match = option['value']
                            print(f"Nieuwe beste match gevonden: {option['text']} (verschil: {diff})")
                except ValueError as e:
                    print(f"Error bij verwerken optie {option['text']}: {str(e)}")
                    continue

            if best_match:
                await page.select_option(selector, best_match)
                await page.wait_for_timeout(500)
                return True
            else:
                print(f"Geen match gevonden voor waarde {compare_value}{'mm' if uses_millimeters else 'cm'} (maximaal toegestaan verschil: 1.0)")
                return False

        except Exception as e:
            print(f"Error bij select veld: {str(e)}")
            return False

    async def _get_m2_price(self, page, dimensions=None) -> Optional[Tuple[float, float]]:
        """Haalt de m² prijs op van de pagina"""
        try:
            # Zoek eerst naar elementen met m² indicatie
            m2_selectors = [
                'text=/m²/',
                'text=/m2/',
                'text=/per m²/',
                'text=/per m2/',
                'text=/vierkante meter/',
                'text=/€.*\\/m[²2]/',
                'text=/.*m[²2].*€/'
            ]

            for selector in m2_selectors:
                try:
                    elements = await page.query_selector_all(selector)
                    for element in elements:
                        try:
                            # Haal de tekst op van het element en zijn parent containers
                            element_text = await element.text_content()
                            if not element_text:
                                continue
                                
                            # Ga 3 niveaus omhoog om parent tekst te verzamelen
                            parent = element
                            container_text = element_text
                            for _ in range(3):
                                try:
                                    parent = await parent.evaluate('node => node.parentElement')
                                    if parent:
                                        parent_text = await parent.text_content()
                                        if parent_text:
                                            container_text = parent_text
                                except:
                                    break
                                
                            container_text = container_text.lower().strip()
                            print(f"Gevonden tekst voor m² prijs: {container_text}")
                            
                            # Zoek alle prijzen in de tekst
                            price_matches = re.finditer(r'€\s*(\d+(?:[.,]\d{2})?)', container_text)
                            prices = []
                            
                            for match in price_matches:
                                price_str = match.group(1).replace(',', '.')
                                try:
                                    price = float(price_str)
                                    if price > 0:
                                        # Bepaal context voor deze specifieke prijs
                                        context_start = max(0, match.start() - 30)
                                        context_end = min(len(container_text), match.end() + 30)
                                        price_context = container_text[context_start:context_end]
                                        
                                        # Check of deze prijs incl of excl BTW is
                                        is_incl = 'incl' in price_context
                                        is_excl = 'excl' in price_context
                                        
                                        if is_incl or is_excl:
                                            prices.append((price, is_incl))
                                except:
                                    continue
                            
                            # Als we beide prijzen hebben gevonden
                            if len(prices) == 2:
                                # Sorteer op prijs (laagste eerst)
                                prices.sort(key=lambda x: x[0])
                                excl_btw = prices[0][0]  # Laagste prijs is excl BTW
                                incl_btw = prices[1][0]  # Hoogste prijs is incl BTW
                                
                                # Valideer dat de prijzen ongeveer 21% verschillen
                                if 1.15 <= (incl_btw / excl_btw) <= 1.25:
                                    print(f"M² prijzen gevonden: €{excl_btw:.2f} excl. BTW / €{incl_btw:.2f} incl. BTW")
                                    return excl_btw, incl_btw
                            
                            # Als we maar één prijs hebben
                            elif len(prices) == 1:
                                price, is_incl = prices[0]
                                if is_incl:
                                    excl_btw = round(price / 1.21, 2)
                                    print(f"M² prijs gevonden (incl. BTW): €{price:.2f}")
                                    return excl_btw, price
                                else:
                                    incl_btw = round(price * 1.21, 2)
                                    print(f"M² prijs gevonden (excl. BTW): €{price:.2f}")
                                    return price, incl_btw
                                    
                        except Exception as e:
                            print(f"Error bij verwerken element: {str(e)}")
                            continue

                except Exception as e:
                    print(f"Error bij m² prijs selector {selector}: {str(e)}")
                    continue

            # Als geen m² prijs gevonden, probeer te zoeken in de hele pagina tekst
            try:
                content = await page.content()
                content = content.lower()
                
                # Zoek naar prijzen met m² indicatie
                price_matches = re.finditer(r'€\s*(\d+(?:[.,]\d{2})?)\s*(?:\/|\s+per\s+)m[²2]', content)
                prices = []
                
                for match in price_matches:
                    price_str = match.group(1).replace(',', '.')
                    try:
                        price = float(price_str)
                        if price > 0:
                            # Zoek in de context of het incl of excl BTW is
                            context_start = max(0, match.start() - 30)
                            context_end = min(len(content), match.end() + 30)
                            context = content[context_start:context_end]
                            
                            is_incl = 'incl' in context
                            is_excl = 'excl' in context
                            
                            if is_incl or is_excl:
                                prices.append((price, is_incl))
                    except:
                        continue
                
                # Als we beide prijzen hebben gevonden
                if len(prices) == 2:
                    # Sorteer op prijs (laagste eerst)
                    prices.sort(key=lambda x: x[0])
                    excl_btw = prices[0][0]  # Laagste prijs is excl BTW
                    incl_btw = prices[1][0]  # Hoogste prijs is incl BTW
                    
                    # Valideer dat de prijzen ongeveer 21% verschillen
                    if 1.15 <= (incl_btw / excl_btw) <= 1.25:
                        print(f"M² prijzen gevonden in tekst: €{excl_btw:.2f} excl. BTW / €{incl_btw:.2f} incl. BTW")
                        return excl_btw, incl_btw
                
                # Als we maar één prijs hebben
                elif len(prices) == 1:
                    price, is_incl = prices[0]
                    if is_incl:
                        excl_btw = round(price / 1.21, 2)
                        print(f"M² prijs gevonden in tekst (incl. BTW): €{price:.2f}")
                        return excl_btw, price
                    else:
                        incl_btw = round(price * 1.21, 2)
                        print(f"M² prijs gevonden in tekst (excl. BTW): €{price:.2f}")
                        return price, incl_btw
                        
            except Exception as e:
                print(f"Error bij zoeken in pagina tekst: {str(e)}")

            return None

        except Exception as e:
            print(f"Error bij m² prijs detectie: {str(e)}")
            return None

    def _extract_price(self, text: str) -> float:
        """Extraheert prijs uit tekst"""
        if not text:
            return 0.0
        
        text = text.lower()
        
        # Verschillende prijs patronen
        price_patterns = [
            r'€\s*(\d+(?:[.,]\d{2})?)',  # €10.99 of €10,99
            r'eur\s*(\d+(?:[.,]\d{2})?)',  # eur10.99
            r'euro\s*(\d+(?:[.,]\d{2})?)',  # euro10.99
            r'(\d+(?:[.,]\d{2})?)\s*(?:eur|euro|€)',  # 10.99€ of 10.99eur
            r'(\d+(?:[.,]\d{2})?)',  # Alleen nummer als laatste optie
        ]
        
        for pattern in price_patterns:
            matches = re.findall(pattern, text)
            if matches:
                # Vervang komma door punt en converteer naar float
                return float(matches[0].replace(',', '.'))
            
        return 0.0

    async def _collect_price_elements(self, page) -> List[Dict]:
        """Verzamelt alle elementen met prijzen"""
        prices = []
        
        # Zoek alleen in relevante tekst elementen
        selectors = [
            'p', 'span', 'div', 'td', 'th', 'label',
            '[class*="price"]', '[class*="prijs"]',
            '[id*="price"]', '[id*="prijs"]'
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
                        
                        # Valideer dat de tekst een geldige prijs bevat
                        if any(indicator in text for indicator in ['€', 'eur']) and \
                           any(indicator in text for indicator in ['incl', 'excl']):
                            # Extraheer de prijs
                            price = self._extract_price(text)
                            if price > 0:
                                # Check BTW indicatie
                                is_incl = any(term in text for term in ['incl', 'inclusief', 'inc.', 'incl.'])
                                
                                prices.append({
                                    'element': element,
                                    'text': text,
                                    'price': price,
                                    'is_incl': is_incl
                                })
                                print(f"Gevonden prijs in element: €{price:.2f} ({'incl' if is_incl else 'excl'} BTW)")
                    except Exception as e:
                        continue
            except Exception as e:
                continue
                
        return prices

    def _find_changed_prices(self, initial_prices: List[Dict], updated_prices: List[Dict]) -> List[Dict]:
        """Vindt prijzen die zijn veranderd na het invullen van dimensies"""
        changed = []
        
        # Maak een map van initiële prijzen voor snelle vergelijking
        initial_map = {p['text']: p['price'] for p in initial_prices}
        
        # Check welke prijzen zijn veranderd
        for price_info in updated_prices:
            text = price_info['text']
            price = price_info['price']
            
            # Als de tekst nieuw is of de prijs is veranderd
            if text not in initial_map or initial_map[text] != price:
                # Extra validatie dat de prijs echt een prijs is
                if any(indicator in text for indicator in ['€', 'eur']) and \
                   any(indicator in text for indicator in ['incl', 'excl']):
                    print(f"Prijs veranderd/toegevoegd: {text} -> €{price:.2f}")
                    changed.append(price_info)
                
        return changed 