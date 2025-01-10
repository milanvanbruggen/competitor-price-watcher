from playwright.sync_api import sync_playwright
import re
from typing import Dict, Optional

class PriceCalculator:
    def __init__(self):
        print("Initialiseren PriceCalculator...")

    def _get_m2_price(self, page, dimensions=None) -> Optional[tuple[float, float]]:
        """Haalt de m² prijs op van de pagina en geeft tuple terug (excl_btw, incl_btw)"""
        print("\nZoeken naar m² prijs...")
        
        # Eerst zoeken naar prijzen met m² indicatie
        m2_price_selectors = [
            "text=/€.*\\/.*m[²2]/i",  # Match prijzen met /m² of /m2
            "text=/€.*per.*m[²2]/i",  # Match prijzen met per m² of per m2
            "text=/.*m[²2].*€/i",  # Match prijzen waar m² voor het bedrag staat
            "text=/.*vierkante.*meter.*€/i",  # Match prijzen met "vierkante meter"
            "[class*='price']:has-text(/m[²2]/i)",
            "[class*='prijs']:has-text(/m[²2]/i)",
            "[class*='price-m2']",
            "[class*='price_m2']",
            "[class*='prijs-m2']",
            "[class*='prijs_m2']"
        ]
        
        # Dan zoeken naar prijzen exclusief BTW
        ex_vat_selectors = [
            "text=/€.*m.*excl/i",
            "text=/€.*excl.*m/i",
            "text=excl. btw",
            "text=excl btw",
            "[class*='price']:has-text('excl')",
            "[class*='prijs']:has-text('excl')",
            "[class*='price-ex']",
            "[class*='price_ex']",
            "[class*='prijs-ex']",
            "[class*='prijs_ex']"
        ]
        
        # Dan zoeken naar prijzen inclusief BTW
        incl_vat_selectors = [
            "text=/€.*m.*incl/i",
            "text=/€.*incl.*m/i",
            "text=incl. btw",
            "text=incl btw",
            "[class*='price']:has-text('incl')",
            "[class*='prijs']:has-text('incl')",
            "[class*='price-inc']",
            "[class*='price_inc']",
            "[class*='prijs-inc']",
            "[class*='prijs_inc']"
        ]
        
        # Als laatste algemene prijs selectors
        general_selectors = [
            "[class*='price']",
            "[class*='prijs']",
            "text=/€/",
            "text=/eur/i",
            "text=/euro/i"
        ]

        def extract_price_from_element(element, dimensions=None) -> Optional[tuple[float, bool]]:
            """Extraheert prijs en BTW status uit een element en zijn directe kinderen"""
            try:
                # Haal de volledige HTML structuur op van het element
                html = element.evaluate('el => el.outerHTML')
                text = element.evaluate('el => el.innerText')
                print(f"Analyseer element: {html}")
                print(f"Element tekst: {text}")
                
                # Check BTW indicatie in dit element en directe kinderen
                is_incl_vat = any(term in text.lower() for term in ['incl', 'inclusief', 'inc.', 'incl.', 'including', 'with vat', 'btw inbegrepen'])
                is_ex_vat = any(term in text.lower() for term in ['excl', 'exclusief', 'ex.', 'excl.', 'excluding', 'ex btw', 'zonder btw'])
                
                # Zoek naar prijspatroon met m² indicator
                price_match = re.search(r'€?\s*(\d+(?:\.\d{3})*(?:[.,]\d{2})?|\d+(?:,\d{3})*(?:\.\d{2})?)\s*(?:\/\s*m[²2]|per\s*m[²2])?', text)
                if price_match:
                    price_str = price_match.group(1)
                    # Verwijder duizendtal separators en zet komma's om naar punten
                    price_str = price_str.replace('.', '').replace(',', '.')
                    price = float(price_str)
                    
                    # Check of het een m² prijs is
                    is_m2_price = bool(re.search(r'(?:\/\s*m[²2]|per\s*m[²2]|m[²2]\s*prijs|vierkante\s*meter)', text.lower()))
                    
                    # Als het geen m² prijs is maar we hebben dimensies, bereken de m² prijs
                    if not is_m2_price and dimensions and 'lengte' in dimensions and 'breedte' in dimensions:
                        area_m2 = (dimensions['lengte'] / 1000) * (dimensions['breedte'] / 1000)  # mm naar m²
                        if area_m2 > 0:
                            price = round(price / area_m2, 2)
                            print(f"Prijs per stuk €{price_str} omgerekend naar m² prijs: €{price:.2f}")
                            is_m2_price = True
                    
                    if not is_m2_price:
                        print(f"Prijs €{price} is geen m² prijs, overslaan")
                        return None
                    
                    print(f"M² prijs gevonden: €{price}")
                    
                    # Als we een duidelijke BTW indicatie hebben in dezelfde container
                    if is_incl_vat and not is_ex_vat:
                        print(f"Prijs €{price} gevonden met inclusief BTW indicatie")
                        return price, True
                    elif is_ex_vat and not is_incl_vat:
                        print(f"Prijs €{price} gevonden met exclusief BTW indicatie")
                        return price, False
                    
                    # Als geen duidelijke indicatie in dit element, kijk naar parent
                    parent = element.evaluate("""el => {
                        const parent = el.parentElement;
                        return parent ? parent.innerText : '';
                    }""")
                    
                    is_parent_incl = any(term in parent.lower() for term in ['incl', 'inclusief', 'inc.', 'incl.', 'including', 'with vat', 'btw inbegrepen'])
                    is_parent_ex = any(term in parent.lower() for term in ['excl', 'exclusief', 'ex.', 'excl.', 'excluding', 'ex btw', 'zonder btw'])
                    
                    if is_parent_incl and not is_parent_ex:
                        print(f"Prijs €{price} gevonden met inclusief BTW indicatie in parent")
                        return price, True
                    elif is_parent_ex and not is_parent_incl:
                        print(f"Prijs €{price} gevonden met exclusief BTW indicatie in parent")
                        return price, False
                    
                    # Als nog steeds geen duidelijke indicatie, kijk naar siblings
                    siblings = element.evaluate("""el => {
                        const siblings = Array.from(el.parentElement.children);
                        return siblings.map(s => s.innerText).join(' ');
                    }""")
                    
                    is_sibling_incl = any(term in siblings.lower() for term in ['incl', 'inclusief', 'inc.', 'incl.', 'including', 'with vat', 'btw inbegrepen'])
                    is_sibling_ex = any(term in siblings.lower() for term in ['excl', 'exclusief', 'ex.', 'excl.', 'excluding', 'ex btw', 'zonder btw'])
                    
                    if is_sibling_incl and not is_sibling_ex:
                        print(f"Prijs €{price} gevonden met inclusief BTW indicatie in siblings")
                        return price, True
                    elif is_sibling_ex and not is_sibling_incl:
                        print(f"Prijs €{price} gevonden met exclusief BTW indicatie in siblings")
                        return price, False
                    
                    # Als nog steeds geen indicatie, neem aan dat het exclusief is
                    print(f"Geen BTW indicatie gevonden voor prijs €{price}, aangenomen dat het exclusief BTW is")
                    return price, False
                    
            except Exception as e:
                print(f"Error bij element analyse: {str(e)}")
            return None

        def convert_price(price: float, is_incl_vat: bool) -> tuple[float, float]:
            """Converteert een prijs naar zowel ex als incl BTW"""
            try:
                if is_incl_vat:
                    incl_btw = round(float(price), 2)
                    excl_btw = round(float(price) / 1.21, 2)
                    print(f"Prijs €{incl_btw:.2f} is inclusief BTW, ex BTW: €{excl_btw:.2f}")
                    return excl_btw, incl_btw
                else:
                    excl_btw = round(float(price), 2)
                    incl_btw = round(float(price) * 1.21, 2)
                    print(f"Prijs €{excl_btw:.2f} is exclusief BTW, incl BTW: €{incl_btw:.2f}")
                    return excl_btw, incl_btw
            except Exception as e:
                print(f"Error bij prijs conversie: {str(e)}")
                return 0.0, 0.0

        def find_price_in_elements(elements, context="", dimensions=None) -> Optional[tuple[float, float]]:
            """Zoekt naar prijzen in een lijst van elementen"""
            for element in elements:
                try:
                    price_info = extract_price_from_element(element, dimensions)
                    if price_info:
                        price, is_incl = price_info
                        result = convert_price(price, is_incl)
                        if result:
                            return result  # Dit is al een tuple
                except Exception as e:
                    print(f"Error bij element analyse: {str(e)}")
            return None

        # Zoek eerst naar expliciete m² prijzen
        print("Zoeken naar expliciete m² prijzen...")
        for selector in m2_price_selectors:
            try:
                elements = page.query_selector_all(selector)
                prices = find_price_in_elements(elements, "M² prijs", dimensions)
                if prices:
                    return prices
            except Exception as e:
                print(f"Error bij m² prijs selector {selector}: {str(e)}")
                continue

        # Zoek dan naar expliciete ex BTW prijzen
        print("\nZoeken naar prijzen exclusief BTW...")
        for selector in ex_vat_selectors:
            try:
                elements = page.query_selector_all(selector)
                prices = find_price_in_elements(elements, "Ex BTW", dimensions)
                if prices:
                    return prices
            except Exception as e:
                print(f"Error bij ex BTW selector {selector}: {str(e)}")
                continue

        # Zoek dan naar inclusief BTW prijzen
        print("\nZoeken naar prijzen inclusief BTW...")
        for selector in incl_vat_selectors:
            try:
                elements = page.query_selector_all(selector)
                prices = find_price_in_elements(elements, "Incl BTW", dimensions)
                if prices:
                    return prices
            except Exception as e:
                print(f"Error bij incl BTW selector {selector}: {str(e)}")
                continue

        # Als laatste probeer algemene prijzen
        print("\nZoeken naar algemene prijzen...")
        for selector in general_selectors:
            try:
                elements = page.query_selector_all(selector)
                prices = find_price_in_elements(elements, "Algemeen", dimensions)
                if prices:
                    return prices
            except Exception as e:
                print(f"Error bij algemene selector {selector}: {str(e)}")
                continue
        
        return None

    def _fill_dimension_field(self, page, field, value, dim_type, uses_centimeters):
        """Vult een dimensie veld in en wacht op updates"""
        try:
            # Converteer waarde naar cm indien nodig
            display_value = value
            if dim_type in ['lengte', 'breedte'] and uses_centimeters:
                display_value = value / 10  # mm naar cm
                print(f"Waarde geconverteerd van {value}mm naar {display_value}cm")
            
            if field.get('tag') == 'select':
                selector = f"#{field['id']}" if field.get('id') else f"[name='{field['name']}']"
                print(f"Probeer select via: {selector}")
                
                try:
                    # Probeer eerst het element te vinden zonder zichtbaarheidscheck
                    select_element = page.query_selector(selector)
                    if not select_element:
                        print(f"Select element niet gevonden: {selector}")
                        return False
                        
                    # Haal alle opties op
                    options = page.eval_on_selector(selector, """select => {
                        return Array.from(select.options).map(option => ({
                            value: option.value,
                            text: option.text.trim()
                        }));
                    }""")
                    print(f"Beschikbare opties: {options}")
                    
                    # Zoek de beste match voor de dikte
                    if dim_type == 'dikte':
                        best_match = None
                        smallest_diff = float('inf')
                        
                        for option in options:
                            try:
                                # Haal numerieke waarde uit de tekst (bijv. "2mm" -> 2)
                                text = option['text'].lower()
                                # Verwijder niet-numerieke karakters behalve punt en komma
                                numeric_part = re.search(r'(\d+(?:[.,]\d+)?)', text)
                                if numeric_part:
                                    option_value = float(numeric_part.group(1).replace(',', '.'))
                                    
                                    # Als de tekst 'cm' bevat, converteer naar mm
                                    if 'cm' in text:
                                        option_value *= 10
                                    
                                    diff = abs(option_value - value)
                                    print(f"Vergelijk optie {text} ({option_value}mm) met gewenste waarde {value}mm (verschil: {diff})")
                                    
                                    if diff < smallest_diff:
                                        smallest_diff = diff
                                        best_match = option['value']
                                        print(f"Nieuwe beste match: {text} (waarde: {option['value']})")
                            except (ValueError, AttributeError) as e:
                                print(f"Kon waarde niet extraheren uit optie {option['text']}: {str(e)}")
                                continue
                    else:
                        # Voor andere velden, gebruik de bestaande logica
                        best_match = None
                        smallest_diff = float('inf')
                        for option in options:
                            try:
                                # Probeer eerst de value te gebruiken
                                try:
                                    option_value = float(option['value'])
                                except ValueError:
                                    # Als value geen getal is, probeer de text
                                    option_value = float(option['text'].replace(',', '.'))
                                
                                diff = abs(option_value - value)
                                if diff < smallest_diff:
                                    smallest_diff = diff
                                    best_match = option['value']
                            except ValueError:
                                continue
                    
                    if best_match:
                        print(f"Beste match gevonden: {best_match}")
                        # Gebruik evaluate om de waarde direct te zetten
                        page.evaluate(f"""
                            const select = document.querySelector('{selector}');
                            if (select) {{
                                select.value = '{best_match}';
                                select.dispatchEvent(new Event('change', {{ bubbles: true }}));
                                select.dispatchEvent(new Event('blur', {{ bubbles: true }}));
                            }}
                        """)
                        page.wait_for_timeout(500)  # Wacht op prijsupdate
                        return True
                    else:
                        print(f"Geen geschikte optie gevonden voor {value}")
                        return False
                except Exception as e:
                    print(f"Error bij verwerken select element: {str(e)}")
                    return False
            else:
                # Normale input velden
                if field.get('id'):
                    selector = f"#{field['id']}"
                    print(f"Probeer via ID: {selector}")
                    input_element = page.locator(selector)
                    input_element.fill(str(display_value))  # Gebruik geconverteerde waarde
                    input_element.evaluate('element => element.blur()')  # Simuleer blur event
                    page.wait_for_timeout(500)  # Wacht op prijsupdate
                    return True
                elif field.get('name'):
                    selector = f"[name='{field['name']}']"
                    print(f"Probeer via name: {selector}")
                    input_element = page.locator(selector)
                    input_element.fill(str(display_value))  # Gebruik geconverteerde waarde
                    input_element.evaluate('element => element.blur()')  # Simuleer blur event
                    page.wait_for_timeout(500)  # Wacht op prijsupdate
                    return True
                elif field.get('class'):
                    selector = f".{field['class'].replace(' ', '.')}"
                    print(f"Probeer via class: {selector}")
                    input_element = page.locator(selector)
                    input_element.fill(str(display_value))  # Gebruik geconverteerde waarde
                    input_element.evaluate('element => element.blur()')  # Simuleer blur event
                    page.wait_for_timeout(500)  # Wacht op prijsupdate
                    return True
                
                return False
        except Exception as e:
            print(f"Error bij invullen {dim_type}: {str(e)}")
            return False

    def calculate_price(self, url: str, dimension_fields: Dict, dimensions: Dict[str, float]) -> Optional[tuple[float, float]]:
        """
        Zoekt eerst naar m² prijzen op de pagina zonder formulier interactie.
        Als geen m² prijs gevonden wordt, vult het de dimensie velden in en probeert opnieuw.
        Returns tuple (excl_btw, incl_btw) of None als geen prijs gevonden.
        """
        page = None
        playwright = None
        browser = None
        context = None
        
        try:
            print(f"\nStart prijsberekening voor {url}")
            
            # Start nieuwe Playwright instantie
            playwright = sync_playwright().start()
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            print("Nieuwe pagina geopend")
            
            page.goto(url)
            print("Pagina geladen")
            
            # Probeer eerst m² prijs te vinden zonder formulier interactie
            print("\nZoeken naar m² prijs zonder formulier interactie...")
            prices = self._get_m2_price(page)
            if prices:
                print(f"Gevonden m² prijzen zonder formulier: €{prices[0]:.2f} ex BTW / €{prices[1]:.2f} incl BTW")
                return prices

            print("\nGeen directe m² prijs gevonden, proberen via formulier...")
            
            # Als geen directe m² prijs gevonden, probeer via formulier
            # Detecteer de eenheid die de pagina gebruikt
            uses_centimeters = False
            print("\nZoeken naar eenheid indicatoren...")
            
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
                    form_elements = page.query_selector_all(selector)
                    for form_element in form_elements:
                        text = form_element.inner_text().lower()
                        print(f"Tekst gevonden in formulier gebied: {text}")
                        if any(term in text for term in ['cm', 'centimeter', 'centimeters']):
                            print("Centimeters (cm) gedetecteerd in formulier gebied")
                            uses_centimeters = True
                            break
                        elif any(term in text for term in ['mm', 'millimeter', 'millimeters']):
                            print("Millimeters (mm) gedetecteerd in formulier gebied")
                            uses_centimeters = False
                            break
                except Exception as e:
                    print(f"Error bij zoeken in formulier gebied: {str(e)}")
                    continue
            
            # Als nog geen eenheid gevonden, zoek in labels en andere relevante elementen
            if not any(term in page.content().lower() for term in ['cm', 'centimeter', 'centimeters', 'mm', 'millimeter', 'millimeters']):
                unit_indicators = page.query_selector_all("label, .form-label, .input-label, .field-label, .input-group, .input-addon")
                for indicator in unit_indicators:
                    try:
                        text = indicator.inner_text().lower()
                        print(f"Tekst gevonden in label: {text}")
                        if any(term in text for term in ['cm', 'centimeter', 'centimeters']):
                            print("Centimeters (cm) gedetecteerd in labels")
                            uses_centimeters = True
                            break
                        elif any(term in text for term in ['mm', 'millimeter', 'millimeters']):
                            print("Millimeters (mm) gedetecteerd in labels")
                            uses_centimeters = False
                            break
                    except Exception as e:
                        print(f"Error bij label check: {str(e)}")
                        continue
            
            print(f"Gebruikte eenheid: {'centimeters' if uses_centimeters else 'millimeters'}")
            
            # Vul eerst alle velden in
            fields_filled = {
                'dikte': False,
                'lengte': False,
                'breedte': False
            }
            
            # Vul eerst dikte in omdat dit vaak andere opties beïnvloedt
            if 'dikte' in dimension_fields and dimension_fields['dikte']:
                print("\nInvullen dikte...")
                dikte_field = dimension_fields['dikte'][0]
                if self._fill_dimension_field(page, dikte_field, dimensions['dikte'], 'dikte', uses_centimeters):
                    fields_filled['dikte'] = True
                    # Wacht even zodat de pagina kan updaten
                    page.wait_for_timeout(1000)
            
            # Vul dan lengte en breedte in
            for dim_type in ['lengte', 'breedte']:
                if dim_type in dimension_fields and dimension_fields[dim_type]:
                    print(f"\nInvullen {dim_type}...")
                    field = dimension_fields[dim_type][0]
                    if self._fill_dimension_field(page, field, dimensions[dim_type], dim_type, uses_centimeters):
                        fields_filled[dim_type] = True
                        # Wacht even zodat de pagina kan updaten
                        page.wait_for_timeout(1000)
            
            # Check of alle velden zijn ingevuld
            if not all(fields_filled.values()):
                missing = [dim for dim, filled in fields_filled.items() if not filled]
                print(f"Waarschuwing: Niet alle velden ingevuld: {missing}")
            
            # Wacht extra lang op laatste prijsupdate
            print("Wachten op laatste prijsupdate...")
            page.wait_for_timeout(2000)

            # Probeer m² prijs te vinden
            prices = self._get_m2_price(page, dimensions)
            if prices:
                print(f"Gevonden m² prijzen: €{prices[0]:.2f} ex BTW / €{prices[1]:.2f} incl BTW")
                return prices

            # Als geen m2 prijs gevonden, probeer algemene prijzen
            print("\nGeen m² prijs gevonden, zoeken naar algemene prijs...")
            price_selectors = [
                "[class*='price']",
                "[class*='prijs']",
                "[id*='price']",
                "[id*='prijs']",
                "span:has-text(/€/)",
                "div:has-text(/€/)",
                "[class*='total']",  # Voeg selectors toe voor totaalprijzen
                "[id*='total']",
                "[class*='amount']",
                "[id*='amount']"
            ]
            
            for selector in price_selectors:
                try:
                    print(f"Probeer selector: {selector}")
                    elements = page.query_selector_all(selector)
                    print(f"Gevonden elementen: {len(elements)}")
                    
                    for element in elements:
                        text = element.inner_text()
                        print(f"Element tekst: {text}")
                        
                        # Zoek naar prijspatroon
                        price_match = re.search(r'€?\s*(\d+(?:[.,]\d{2})?)', text)
                        if price_match:
                            price_str = price_match.group(1).replace(',', '.')
                            price = float(price_str)
                            print(f"Prijs gevonden: €{price}")
                            
                            # Als prijs 0 is, sla over
                            if price == 0:
                                print("Prijs is 0, deze overslaan")
                                continue
                            
                            # Converteer naar m² prijs als we dimensies hebben
                            if dimensions and 'lengte' in dimensions and 'breedte' in dimensions:
                                area_m2 = (dimensions['lengte'] / 1000) * (dimensions['breedte'] / 1000)  # mm naar m²
                                if area_m2 > 0:
                                    m2_price = round(price / area_m2, 2)
                                    print(f"Prijs per m²: €{m2_price:.2f}")
                                    
                                    # Check of de prijs inclusief of exclusief BTW is
                                    is_incl_vat = any(term in text.lower() for term in ['incl', 'inclusief', 'inc.', 'incl.'])
                                    if is_incl_vat:
                                        excl_btw = round(m2_price / 1.21, 2)
                                        return excl_btw, m2_price
                                    else:
                                        incl_btw = round(m2_price * 1.21, 2)
                                        return m2_price, incl_btw
                            
                            # Als we hier komen is het een normale prijs
                            is_incl_vat = any(term in text.lower() for term in ['incl', 'inclusief', 'inc.', 'incl.'])
                            if is_incl_vat:
                                excl_btw = round(price / 1.21, 2)
                                return excl_btw, price
                            else:
                                incl_btw = round(price * 1.21, 2)
                                return price, incl_btw
                except Exception as e:
                    print(f"Error bij selector {selector}: {str(e)}")
                    continue
            
            print("Geen prijzen gevonden")
            return None
            
        except Exception as e:
            print(f"Error tijdens prijsberekening: {str(e)}")
            return None
        finally:
            if page:
                try:
                    page.close()
                    print("Pagina gesloten")
                except:
                    pass
            if context:
                try:
                    context.close()
                except:
                    pass
            if browser:
                try:
                    browser.close()
                except:
                    pass
            if playwright:
                try:
                    playwright.stop()
                except:
                    pass 