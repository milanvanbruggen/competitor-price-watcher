from playwright.async_api import async_playwright
import re
from typing import Dict, List, Optional

class MaterialScraper:
    def __init__(self):
        self.MIN_FUZZY_SCORE = 80
        self._seen_size_fields = set()

    async def analyze_form_fields(self, url: str) -> Dict:
        """Analyseert een webpagina voor specifieke dimensie velden"""
        print(f"\nAnalyseren van velden voor {url}")
        
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch()
                page = await browser.new_page()
                await page.goto(url)

                # Dimensie termen om naar te zoeken
                dimension_terms = {
                    'dikte': ['dikte', 'thickness', 'dik'],
                    'lengte': ['lengte', 'length', 'lang'],
                    'breedte': ['breedte', 'width', 'breed'],
                    'hoogte': ['hoogte', 'height', 'hoog']
                }

                # Zoek alle input en select elementen
                elements = await page.query_selector_all('input[type="text"], input[type="number"], select')
                
                dimension_fields = {}
                
                for element in elements:
                    try:
                        # Haal element informatie op
                        element_info = await self._get_field_info(element)
                        if not element_info:
                            continue

                        # Zoek het dichtstbijzijnde label element
                        label_text = await self._find_closest_label(page, element)
                        if label_text:
                            element_info['label'] = label_text

                        # Check voor dimensie termen in label, id, name en omliggende tekst
                        found_dimension = None
                        label_text = (element_info.get('label', '') + ' ' + 
                                    element_info.get('id', '') + ' ' + 
                                    element_info.get('name', '')).lower()

                        # Zoek ook in omliggende tekst
                        surrounding_text = await self._get_surrounding_text(page, element)
                        if surrounding_text:
                            label_text += ' ' + surrounding_text.lower()

                        # Check voor elke dimensie term
                        for dimension, terms in dimension_terms.items():
                            if any(term in label_text for term in terms):
                                found_dimension = dimension
                                print(f"Gevonden {dimension} veld: {label_text}")
                                break

                        if found_dimension:
                            if found_dimension not in dimension_fields:
                                dimension_fields[found_dimension] = []
                            dimension_fields[found_dimension].append(element_info)

                    except Exception as e:
                        print(f"Error bij verwerken element: {str(e)}")
                        continue

                await browser.close()
                return dimension_fields

        except Exception as e:
            print(f"Error bij analyseren velden: {str(e)}")
            return {}

    async def _get_field_info(self, element) -> Optional[Dict]:
        """Verzamelt relevante informatie over een form element"""
        try:
            # Basis element informatie
            tag_name = await element.evaluate('element => element.tagName.toLowerCase()')
            element_id = await element.evaluate('element => element.id')
            element_name = await element.evaluate('element => element.name')
            element_type = await element.evaluate('element => element.type')
            
            return {
                'tag': tag_name,
                'type': element_type,
                'id': element_id,
                'name': element_name
            }

        except Exception as e:
            print(f"Error bij ophalen element info: {str(e)}")
            return None

    async def _find_closest_label(self, page, element) -> Optional[str]:
        """Vindt het dichtstbijzijnde label voor een element"""
        try:
            # 1. Check voor een expliciet gekoppeld label via for/id
            element_id = await element.evaluate('element => element.id')
            if element_id:
                label = await page.query_selector(f'label[for="{element_id}"]')
                if label:
                    return await label.inner_text()

            # 2. Check voor een parent label
            parent_label = await element.evaluate('''
                element => {
                    let parent = element.parentElement;
                    while (parent) {
                        if (parent.tagName.toLowerCase() === 'label') {
                            return parent.innerText;
                        }
                        parent = parent.parentElement;
                    }
                    return null;
                }
            ''')
            if parent_label:
                return parent_label

            return None

        except Exception as e:
            print(f"Error bij zoeken label: {str(e)}")
            return None

    async def _get_surrounding_text(self, page, element) -> Optional[str]:
        """Haalt tekst op rondom het element"""
        try:
            surrounding_text = await element.evaluate('''
                element => {
                    // Verzamel tekst van siblings en parent
                    let text = '';
                    let parent = element.parentElement;
                    
                    if (parent) {
                        // Voeg tekst van vorige sibling toe
                        let prev = element.previousElementSibling;
                        if (prev) text += ' ' + prev.innerText;
                        
                        // Voeg tekst van volgende sibling toe
                        let next = element.nextElementSibling;
                        if (next) text += ' ' + next.innerText;
                        
                        // Voeg parent tekst toe
                        text += ' ' + parent.innerText;
                    }
                    
                    return text.trim();
                }
            ''')
            return surrounding_text

        except Exception as e:
            print(f"Error bij ophalen omliggende tekst: {str(e)}")
            return None

    async def _find_label_for_element(self, element) -> Optional[str]:
        """Zoekt het label dat bij een form element hoort"""
        try:
            # Probeer label te vinden via for attribute
            element_id = await element.get_attribute('id')
            if element_id:
                label = await element.evaluate(f"""el => {{
                    const label = document.querySelector('label[for="{element_id}"]');
                    return label ? label.textContent : null;
                }}""")
                if label:
                    return label.strip()
            
            # Probeer label te vinden als parent element
            label = await element.evaluate("""el => {
                const parent = el.closest('label');
                return parent ? parent.textContent : null;
            }""")
            if label:
                return label.strip()
            
            # Zoek naar een label in de buurt
            nearby_label = await element.evaluate("""el => {
                const prev = el.previousElementSibling;
                return prev && prev.tagName === 'LABEL' ? prev.textContent : null;
            }""")
            if nearby_label:
                return nearby_label.strip()
                
        except Exception as e:
            print(f"Error bij zoeken label: {str(e)}")
            
        return None

    async def _determine_dimension_type(self, field_info: Dict) -> Optional[str]:
        """Bepaalt het type dimensie van een veld"""
        # Skip search/zoek velden
        field_type = field_info.get('type', '').lower()
        if field_type == 'search':
            return None
            
        # Combineer alle tekst voor analyse
        text_to_check = ' '.join(str(value).lower() for value in field_info.values() if value)
        
        # Check eerst op size/maat patronen
        size_patterns = [
            r'size',
            r'maat',
            r'afmeting',
            r'dimension'
        ]
        
        if any(re.search(pattern, text_to_check) for pattern in size_patterns):
            # Check op A/B/1/2 patronen voor lengte/breedte
            if any(pattern in text_to_check for pattern in ['a', '1', 'sizea', 'size1', 'maata', 'maat1']):
                return 'lengte'
            if any(pattern in text_to_check for pattern in ['b', '2', 'sizeb', 'size2', 'maatb', 'maat2']):
                return 'breedte'
        
        # Patronen voor verschillende dimensies
        dikte_patterns = [
            r'dikte',
            r'dik(te)?',
            r'thickness',
            r'd(\.|\s|$)',  # d. of d aan eind
            r'stark(e)?',
            r'mm\s*dik',
            r'cm\s*dik'
        ]
        
        lengte_patterns = [
            r'lengte',
            r'lang',
            r'length',
            r'l(\.|\s|$)',  # l. of l aan eind
            r'lange',
            r'lang(e)?',
            r'hoogte',
            r'height',
            r'hoog'
        ]
        
        breedte_patterns = [
            r'breedte',
            r'breed',
            r'width',
            r'b(\.|\s|$)',  # b. of b aan eind
            r'breit(e)?',
            r'wijdte'
        ]
        
        # Check patronen
        if any(re.search(pattern, text_to_check) for pattern in dikte_patterns):
            return 'dikte'
        elif any(re.search(pattern, text_to_check) for pattern in lengte_patterns):
            return 'lengte'
        elif any(re.search(pattern, text_to_check) for pattern in breedte_patterns):
            return 'breedte'
        
        return None

    async def _validate_dimension_value(self, dimension_type: str, value: Optional[str]) -> bool:
        """Valideert of een waarde past bij het type dimensie"""
        if not value:
            return True  # Geen waarde om te valideren
            
        try:
            # Verwijder niet-numerieke karakters behalve punt en komma
            clean_value = re.sub(r'[^0-9.,]', '', str(value).replace(',', '.'))
            if not clean_value:
                return True  # Geen numerieke waarde om te valideren
                
            num_value = float(clean_value)
            
            if dimension_type == 'dikte':
                return 0.1 <= num_value <= 100  # Dikte tussen 0.1mm en 100mm
            elif dimension_type in ['lengte', 'breedte']:
                return 1 <= num_value <= 5000   # Lengte/Breedte tussen 1mm en 5000mm
                
        except:
            return True  # Bij twijfel, accepteer het veld
        
        return True

    async def _sort_fields_by_reliability(self, fields: List[Dict]) -> List[Dict]:
        """Sorteert velden op basis van betrouwbaarheid en verwijdert duplicaten"""
        if not fields:
            return []
            
        def reliability_score(field):
            score = 0
            
            # Verhoog score voor specifieke attributen
            if field.get('label'): score += 5
            if field.get('id'): score += 3
            if field.get('name'): score += 2
            if field.get('placeholder'): score += 1
            if field.get('type') == 'number': score += 2
            if field.get('type') == 'text': score += 1
            
            return score
            
        # Sorteer op betrouwbaarheid
        sorted_fields = sorted(fields, key=reliability_score, reverse=True)
        
        # Verwijder mogelijke duplicaten
        unique_fields = []
        seen_ids = set()
        seen_names = set()
        
        for field in sorted_fields:
            field_id = field.get('id')
            field_name = field.get('name')
            
            if field_id and field_id in seen_ids:
                continue
            if field_name and field_name in seen_names:
                continue
                
            if field_id:
                seen_ids.add(field_id)
            if field_name:
                seen_names.add(field_name)
                
            unique_fields.append(field)
            
        return unique_fields 