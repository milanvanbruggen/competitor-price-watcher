from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
import platform
import os
import re
from fuzzywuzzy import fuzz

class MaterialScraper:
    def __init__(self):
        # Browser initialiseren
        self.driver = None
        self._seen_size_fields = set()
        # Minimum score voor fuzzy matching
        self.MIN_FUZZY_SCORE = 80
        try:
            # Chrome opties configureren
            chrome_options = Options()
            chrome_options.add_argument('--headless')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            
            # Detecteer Apple Silicon
            if platform.processor() == 'arm':
                chrome_path = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
                if os.path.exists(chrome_path):
                    chrome_options.binary_location = chrome_path
            
            self.driver = webdriver.Chrome(options=chrome_options)
            self.wait = WebDriverWait(self.driver, 10)
            
        except Exception as e:
            print(f"Error bij initialiseren van de browser: {str(e)}")

    def analyze_form_fields(self, url):
        """Analyseert een pagina om specifieke dimensie velden te vinden"""
        if not self.driver:
            raise ValueError("Browser is niet correct geïnitialiseerd")
            
        try:
            self.driver.get(url)
            
            # Zoek eerst naar dimensievelden
            dimension_elements = self.driver.find_elements(By.CSS_SELECTOR, 'input, select, [contenteditable="true"]')
            
            # Zoek apart naar prijselementen met XPath voor tekst matching
            price_elements = self.driver.find_elements(By.XPATH, 
                ".//*[contains(@id,'price') or contains(@id,'Price') or contains(@id,'prijs') or " +
                "contains(@id,'Prijs') or contains(@class,'price') or contains(@class,'Price') or " +
                "contains(@class,'prijs') or contains(@class,'Prijs') or contains(text(),'€') or " +
                "contains(text(),'EUR') or contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'per m2') or " +
                "contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'per m²')]" +
                "[not(contains(@class,'totalprice'))][not(ancestor::*[@id='basket'])]"
            )
            
            # Categorieën voor verschillende type velden
            dimension_fields = {
                'dikte': [],
                'lengte': [],
                'breedte': [],
                'prijs': []
            }
            
            # Verwerk dimensievelden
            for element in dimension_elements:
                field_info = self._get_field_info(element)
                if not field_info:
                    continue

                # Bepaal het type dimensie veld
                dimension_type = self._determine_dimension_type(field_info)
                if dimension_type:
                    # Valideer de waarde als die beschikbaar is
                    if self._validate_dimension_value(dimension_type, field_info.get('value')):
                        dimension_fields[dimension_type].append(field_info)
            
            # Verwerk prijselementen
            for element in price_elements:
                field_info = self._get_field_info(element)
                if field_info and field_info.get('price_related'):
                    dimension_fields['prijs'].append(field_info)
            
            # Filter dubbele velden en sorteer op betrouwbaarheid
            for dim_type in dimension_fields:
                if dim_type != 'prijs':  # Prijsvelden nog niet sorteren
                    dimension_fields[dim_type] = self._sort_fields_by_reliability(dimension_fields[dim_type])
            
            # Vind het prijselement dat het dichtst bij de dimensievelden ligt
            if dimension_fields['prijs'] and any(dimension_fields[dim_type] for dim_type in ['dikte', 'lengte', 'breedte']):
                # Verzamel XPaths van dimensievelden
                dim_xpaths = []
                for dim_type in ['dikte', 'lengte', 'breedte']:
                    if dimension_fields[dim_type]:
                        xpath = dimension_fields[dim_type][0].get('xpath')
                        if xpath:
                            dim_xpaths.append(xpath)
                
                if dim_xpaths:
                    # Sorteer prijselementen op basis van afstand tot dimensievelden
                    dimension_fields['prijs'].sort(key=lambda x: self._calculate_xpath_distance(x.get('xpath', ''), dim_xpaths))
            
            return {
                'url': url,
                'dimension_fields': dimension_fields
            }

        except Exception as e:
            print(f"Error tijdens analyseren: {str(e)}")
            return None
    
    def _get_field_info(self, element):
        """Verzamelt alle relevante informatie over een form element"""
        try:
            # Check eerst het type - skip ongewenste types
            element_type = element.get_attribute('type')
            if element_type in ['hidden', 'submit', 'button', 'checkbox', 'radio']:
                return None
            
            info = {
                'tag': element.tag_name,
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
            element_text = element.text.lower() if element.text else ''
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

            # Voeg XPath toe voor afstandsberekening
            info['xpath'] = self._get_element_xpath(element)
            
            # Filter lege waardes
            return {k: v for k, v in info.items() if v}
            
        except Exception as e:
            print(f"Error bij verwerken element: {str(e)}")
            return None

    def _get_element_xpath(self, element):
        """Genereer XPath voor een element"""
        try:
            return self.driver.execute_script("""
                function getPathTo(element) {
                    if (element.id !== '')
                        return `//*[@id="${element.id}"]`;
                    if (element === document.body)
                        return '/html/body';

                    let ix = 0;
                    let siblings = element.parentNode.childNodes;

                    for (let sibling of siblings) {
                        if (sibling === element)
                            return getPathTo(element.parentNode) + '/' + element.tagName.toLowerCase() + '[' + (ix + 1) + ']';
                        if (sibling.nodeType === 1 && sibling.tagName === element.tagName)
                            ix++;
                    }
                }
                return getPathTo(arguments[0]);
            """, element)
        except:
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

    def _find_label_for_element(self, element):
        """Zoekt het label dat bij een form element hoort"""
        try:
            # Probeer label te vinden via for attribute
            element_id = element.get_attribute('id')
            if element_id:
                label = self.driver.find_element(By.CSS_SELECTOR, f'label[for="{element_id}"]')
                if label:
                    return label.text.strip()
            
            # Probeer label te vinden als parent element
            parent = element.find_element(By.XPATH, '..')
            if parent.tag_name == 'label':
                return parent.text.strip()
            
            # Zoek naar een label in de buurt
            nearby_label = element.find_element(By.XPATH, './preceding::label[1]')
            if nearby_label:
                return nearby_label.text.strip()
                
        except NoSuchElementException:
            pass
        
        return None
        
    def _calculate_xpath_distance(self, price_xpath, dim_xpaths):
        """Bereken de 'afstand' tussen XPaths door gemeenschappelijke voorouders te tellen"""
        if not price_xpath:
            return float('inf')
        
        total_distance = 0
        for dim_xpath in dim_xpaths:
            # Split paths
            price_parts = price_xpath.split('/')
            dim_parts = dim_xpath.split('/')
            
            # Vind gemeenschappelijke voorouders
            common_length = 0
            for i in range(min(len(price_parts), len(dim_parts))):
                if price_parts[i] == dim_parts[i]:
                    common_length += 1
                else:
                    break
            
            # Bereken afstand
            distance = (len(price_parts) - common_length) + (len(dim_parts) - common_length)
            total_distance += distance
        
        return total_distance / len(dim_xpaths)  # Gemiddelde afstand tot alle dimensievelden

    def __del__(self):
        if hasattr(self, 'driver') and self.driver:
            try:
                self.driver.quit()
            except:
                pass 