from playwright.sync_api import sync_playwright
from fuzzywuzzy import fuzz
import re

class MaterialScraper:
    def __init__(self):
        self._seen_size_fields = set()
        # Minimum score voor fuzzy matching
        self.MIN_FUZZY_SCORE = 80

    def analyze_form_fields(self, url):
        """Analyseert een pagina om specifieke dimensie velden te vinden"""
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(url)
            
            # Zoek naar dimensievelden
            dimension_fields = {
                'dikte': [],
                'lengte': [],
                'breedte': [],
                'prijs': []
            }
            
            # Zoek alle relevante elementen
            elements = page.query_selector_all('input, select, [contenteditable="true"]')
            
            # Verwerk dimensievelden
            for element in elements:
                field_info = self._get_field_info(element)
                if not field_info:
                    continue

                # Bepaal het type dimensie veld
                dimension_type = self._determine_dimension_type(field_info)
                if dimension_type:
                    # Valideer de waarde als die beschikbaar is
                    if self._validate_dimension_value(dimension_type, field_info.get('value')):
                        dimension_fields[dimension_type].append(field_info)
            
            # Zoek apart naar prijselementen
            price_elements = page.query_selector_all(
                '[id*="price"], [id*="Price"], [id*="prijs"], [id*="Prijs"], ' +
                '[class*="price"], [class*="Price"], [class*="prijs"], [class*="Prijs"], ' +
                ':text-matches("€|EUR|per m2|per m²", "i")'
            )
            
            # Verwerk prijselementen
            for element in price_elements:
                field_info = self._get_field_info(element)
                if field_info and field_info.get('price_related'):
                    dimension_fields['prijs'].append(field_info)
            
            # Filter dubbele velden en sorteer op betrouwbaarheid
            for dim_type in dimension_fields:
                if dim_type != 'prijs':  # Prijsvelden nog niet sorteren
                    dimension_fields[dim_type] = self._sort_fields_by_reliability(dimension_fields[dim_type])
            
            browser.close()
            
            return {
                'url': url,
                'dimension_fields': dimension_fields
            }
    
    def _get_field_info(self, element):
        """Verzamelt alle relevante informatie over een form element"""
        try:
            # Check eerst het type - skip ongewenste types
            element_type = element.get_attribute('type')
            if element_type in ['hidden', 'submit', 'button', 'checkbox', 'radio']:
                return None
            
            info = {
                'tag': element.evaluate('el => el.tagName.toLowerCase()'),
                'type': element_type,
                'id': element.get_attribute('id'),
                'name': element.get_attribute('name'),
                'class': element.get_attribute('class'),
                'placeholder': element.get_attribute('placeholder'),
                'value': element.get_attribute('value')
            }

            # Zoek het label
            label = self._find_label_for_element(element)
            if label:
                info['label'] = label

            # Zoek naar prijsinformatie in het element en omliggende elementen
            element_text = element.inner_text() or ''
            element_id = (info['id'] or '').lower()
            element_class = (info['class'] or '').lower()
            
            # Specifiek zoeken naar m2 prijzen
            m2_price_terms = ['/m2', '/m²', 'per m2', 'per m²', 'prijs/m2', 'prijs/m²', 'per vierkante meter']
            if any(term in element_text.lower() for term in m2_price_terms):
                info['price_related'] = True
                info['is_m2_price'] = True
                # Probeer een prijs te extraheren
                price_match = re.search(r'€?\s*(\d+[.,]\d{2})\s*(?:/m2|/m²|per m2|per m²)?', element_text)
                if price_match:
                    info['price_value'] = price_match.group(1).replace(',', '.')
                    info['price_type'] = 'm2'
            else:
                # Algemene prijsinformatie
                price_terms = ['prijs', 'price', 'euro', 'eur']
                if any(term in element_text or term in element_id or term in element_class for term in price_terms):
                    info['price_related'] = True
                    # Probeer een prijs te extraheren
                    price_match = re.search(r'€?\s*(\d+[.,]\d{2})', element_text)
                    if price_match:
                        info['price_value'] = price_match.group(1).replace(',', '.')
                        info['price_type'] = 'total'

            # Filter lege waardes
            return {k: v for k, v in info.items() if v}
            
        except Exception as e:
            print(f"Error bij verwerken element: {str(e)}")
            return None

    def _find_label_for_element(self, element):
        """Zoekt het label dat bij een form element hoort"""
        try:
            # Probeer label te vinden via for attribute
            element_id = element.get_attribute('id')
            if element_id:
                label = element.evaluate(f'el => document.querySelector(\'label[for="{element_id}"]\')?.textContent')
                if label:
                    return label.strip()
            
            # Probeer label te vinden als parent element
            parent = element.evaluate('el => el.parentElement')
            if parent and parent.tag_name.lower() == 'label':
                return parent.inner_text().strip()
            
            # Zoek naar een label in de buurt
            nearby_label = element.evaluate('el => el.previousElementSibling?.tagName === "LABEL" ? el.previousElementSibling.textContent : null')
            if nearby_label:
                return nearby_label.strip()
                
        except Exception:
            pass
        
        return None

    def _fuzzy_match(self, text, terms, min_score=None):
        """Fuzzy matching voor een tekst tegen een lijst van termen"""
        if min_score is None:
            min_score = self.MIN_FUZZY_SCORE
            
        # Verwijder speciale karakters en maak lowercase
        clean_text = ''.join(c.lower() for c in text if c.isalnum())
        
        for term in terms:
            clean_term = ''.join(c.lower() for c in term if c.isalnum())
            
            # Exacte match heeft voorrang
            if clean_term == clean_text:
                return True, 100
                
            # Ratio voor hele string
            ratio = fuzz.ratio(clean_text, clean_term)
            if ratio >= min_score:
                return True, ratio
                
            # Partial ratio voor delen van de string
            partial = fuzz.partial_ratio(clean_text, clean_term)
            if partial >= min_score:
                return True, partial
                
            # Token sort ratio voor woorden in andere volgorde
            token_sort = fuzz.token_sort_ratio(clean_text, clean_term)
            if token_sort >= min_score:
                return True, token_sort
        
        return False, 0

    def _determine_dimension_type(self, field_info):
        """Bepaalt of een veld voor dikte, lengte of breedte is"""
        # Skip search/zoek velden
        field_type = field_info.get('type', '').lower()
        field_id = field_info.get('id', '').lower()
        field_name = field_info.get('name', '').lower()
        
        # Skip zoek/search velden met fuzzy matching
        search_terms = ['search', 'zoek', 'zoeken', 'find']
        is_search, _ = self._fuzzy_match(field_id, search_terms) or self._fuzzy_match(field_name, search_terms)
        if is_search or field_type == 'search':
            return None
            
        # Combineer alle tekst informatie
        field_text = ' '.join(str(v).lower() for v in [
            field_info.get('label', ''),
            field_id,
            field_name,
            field_info.get('placeholder', ''),
            field_info.get('value', '')
        ])

        # Check eerst op size/maat patronen (hoogste prioriteit)
        size_terms = ['size', 'maat', 'maten', 'afmeting', 'afmetingen', 'dimension']
        if any(self._fuzzy_match(field_id, [term])[0] for term in size_terms) or \
           any(self._fuzzy_match(field_name, [term])[0] for term in size_terms):
            
            # Check op A/B/1/2 patronen
            if any(pattern in field_id.lower() or pattern in field_name.lower() for pattern in ['a', '1', 'sizea', 'size1', 'maata', 'maat1']):
                return 'lengte'
            if any(pattern in field_id.lower() or pattern in field_name.lower() for pattern in ['b', '2', 'sizeb', 'size2', 'maatb', 'maat2']):
                return 'breedte'

        # Definieer dimensie-gerelateerde termen
        dimension_terms = {
            'dikte': ['dikte', 'thickness', 'sized', 'maat_d', 'size_d', 'dikke', 'dik'],
            'lengte': ['lengte', 'length', 'hoogte', 'height', 'sizel', 'sizeh', 'maat_l', 'maat_h', 'lang', 'hoog'],
            'breedte': ['breedte', 'width', 'sizew', 'maat_b', 'maat_w', 'breed', 'wijdte']
        }
        
        # Speciale check voor dikte velden
        if field_info.get('tag') == 'select':
            # Voor select elements, check of de opties dikte-gerelateerd zijn
            is_dikte, score = self._fuzzy_match(field_text, dimension_terms['dikte'])
            if is_dikte:
                print(f"Fuzzy match voor dikte in select element: {score}%")
                return 'dikte'
        
        # Check voor directe dimensie indicators met fuzzy matching
        for dim_type, indicators in dimension_terms.items():
            # Check in ID
            is_match, score = self._fuzzy_match(field_id, indicators)
            if is_match:
                print(f"Fuzzy match voor {dim_type} in ID: {score}%")
                return dim_type
                
            # Check in name
            is_match, score = self._fuzzy_match(field_name, indicators)
            if is_match:
                print(f"Fuzzy match voor {dim_type} in name: {score}%")
                return dim_type
        
        # Als nog geen match, check specifieke patronen in de tekst met fuzzy matching
        dimension_patterns = {
            'dikte': ['mm dikte', 'cm dikte', 'dikte in', 'diktemaat'],
            'lengte': ['mm lengte', 'cm lengte', 'lengte in', 'hoogte in', 'lengtemaat'],
            'breedte': ['mm breedte', 'cm breedte', 'breedte in', 'breedtemaat']
        }
        
        for dim_type, patterns in dimension_patterns.items():
            is_match, score = self._fuzzy_match(field_text, patterns, min_score=75)  # Iets lagere score voor patronen
            if is_match:
                print(f"Fuzzy match voor {dim_type} patroon: {score}%")
                return dim_type
        
        return None

    def _validate_dimension_value(self, dimension_type, value):
        """Valideert of een waarde past bij het type dimensie"""
        if not value:
            return True  # Geen waarde om te valideren
            
        try:
            # Verwijder niet-numerieke karakters behalve punt en komma
            clean_value = re.sub(r'[^0-9.,]', '', value.replace(',', '.'))
            if not clean_value:
                return True  # Geen numerieke waarde om te valideren
                
            num_value = float(clean_value)
            
            if dimension_type == 'dikte':
                return 0.1 <= num_value <= 100  # Dikte tussen 0.1mm en 100mm
            elif dimension_type == 'lengte':
                return 1 <= num_value <= 5000   # Lengte tussen 1mm en 5000mm
            elif dimension_type == 'breedte':
                return 1 <= num_value <= 5000   # Breedte tussen 1mm en 5000mm
                
        except:
            return True  # Bij twijfel, accepteer het veld
        
        return True

    def _sort_fields_by_reliability(self, fields):
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
        
        # Verwijder mogelijke duplicaten (velden die naar waarschijnlijk hetzelfde zijn)
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