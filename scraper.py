from playwright.async_api import async_playwright
import re
from typing import Dict, List, Optional

class MaterialScraper:
    def __init__(self):
        self.MIN_FUZZY_SCORE = 80
        self._seen_size_fields = set()

    async def analyze_form_fields(self, url: str) -> Dict:
        """Analyseert een pagina voor dimensie velden"""
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch()
                page = await browser.new_page()
                await page.goto(url)
                
                # Zoek naar input en select elementen
                elements = await page.query_selector_all('input, select')
                
                dimension_fields = {
                    'dikte': [],
                    'lengte': [],
                    'breedte': []
                }
                
                for element in elements:
                    field_info = await self._get_field_info(element)
                    if field_info:
                        dimension_type = field_info.get('dimension_type')
                        if dimension_type in dimension_fields:
                            dimension_fields[dimension_type].append(field_info)
                
                await browser.close()
                return {'dimension_fields': dimension_fields}
                
        except Exception as e:
            print(f"Error bij analyseren form fields: {str(e)}")
            return {'dimension_fields': {}}

    async def _get_field_info(self, element) -> Optional[Dict]:
        """Verzamelt relevante informatie over een form element"""
        try:
            # Element eigenschappen ophalen
            tag_name = await element.evaluate('element => element.tagName.toLowerCase()')
            element_id = await element.evaluate('element => element.id')
            element_name = await element.evaluate('element => element.name')
            element_class = await element.evaluate('element => element.className')
            
            # Label tekst zoeken
            label_text = ""
            
            # 1. Probeer gekoppeld label te vinden via for/id
            if element_id:
                label_element = await element.evaluate(f"""
                    element => {{
                        const label = document.querySelector(`label[for="{element_id}"]`);
                        return label ? label.textContent : null;
                    }}
                """)
                if label_element:
                    label_text = label_element.lower()
            
            # 2. Zoek parent label
            if not label_text:
                parent_label = await element.evaluate("""
                    element => {
                        const label = element.closest('label');
                        return label ? label.textContent : null;
                    }
                """)
                if parent_label:
                    label_text = parent_label.lower()
            
            # 3. Zoek naastgelegen label
            if not label_text:
                sibling_label = await element.evaluate("""
                    element => {
                        const prev = element.previousElementSibling;
                        if (prev && prev.tagName.toLowerCase() === 'label') {
                            return prev.textContent;
                        }
                        const next = element.nextElementSibling;
                        if (next && next.tagName.toLowerCase() === 'label') {
                            return next.textContent;
                        }
                        return null;
                    }
                """)
                if sibling_label:
                    label_text = sibling_label.lower()
            
            # 4. Zoek in placeholder of title
            if not label_text:
                placeholder = await element.evaluate('element => element.placeholder || element.title || ""')
                if placeholder:
                    label_text = placeholder.lower()
            
            # Bepaal dimensie type op basis van tekst
            dimension_type = None
            text_to_check = f"{label_text} {element_id} {element_name} {element_class}".lower()
            
            if any(term in text_to_check for term in ['dikte', 'dik', 'thickness', 'thick']):
                dimension_type = 'dikte'
            elif any(term in text_to_check for term in ['lengte', 'lang', 'length', 'long']):
                dimension_type = 'lengte'
            elif any(term in text_to_check for term in ['breedte', 'breed', 'width', 'wide']):
                dimension_type = 'breedte'
            
            if dimension_type:
                return {
                    'id': element_id,
                    'name': element_name,
                    'tag': tag_name,
                    'dimension_type': dimension_type,
                    'label': label_text
                }
            
            return None
            
        except Exception as e:
            print(f"Error bij verzamelen field info: {str(e)}")
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