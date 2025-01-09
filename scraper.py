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

class MaterialScraper:
    def __init__(self):
        # Browser initialiseren
        self.driver = None
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
            
            # Zoek alle potentiële form elementen
            elements = self.driver.find_elements(By.CSS_SELECTOR, 'input, select, [contenteditable="true"]')
            
            # Categorieën voor verschillende type velden
            dimension_fields = {
                'dikte': [],
                'lengte': [],
                'breedte': []
            }
            
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
            
            # Filter dubbele velden en sorteer op betrouwbaarheid
            for dim_type in dimension_fields:
                dimension_fields[dim_type] = self._sort_fields_by_reliability(dimension_fields[dim_type])
            
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
                'value': element.get_attribute('value'),
                'label': self._find_label_for_element(element),
                'aria_label': element.get_attribute('aria-label'),
                'title': element.get_attribute('title')
            }
            
            # Voeg data-attributen toe
            for attr in element.get_property('attributes'):
                if attr['name'].startswith('data-'):
                    info[attr['name']] = attr['value']
            
            # Filter lege waardes
            return {k: v for k, v in info.items() if v}
            
        except:
            return None

    def _determine_dimension_type(self, field_info):
        """Bepaalt of een veld voor dikte, lengte of breedte is"""
        # Combineer alle tekst informatie
        field_text = ' '.join(str(v).lower() for v in field_info.values())
        
        # Dikte patronen
        dikte_patterns = [
            r'dikte',
            r'thickness',
            r'd\s*=',
            r'materiaaldikte',
            r'plaatdikte'
        ]
        
        # Lengte/hoogte patronen
        lengte_patterns = [
            r'lengte',
            r'length',
            r'hoogte',
            r'height',
            r'l\s*=',
            r'h\s*='
        ]
        
        # Breedte patronen
        breedte_patterns = [
            r'breedte',
            r'width',
            r'b\s*=',
            r'w\s*='
        ]
        
        # Check patronen
        for pattern in dikte_patterns:
            if re.search(pattern, field_text):
                return 'dikte'
                
        for pattern in lengte_patterns:
            if re.search(pattern, field_text):
                return 'lengte'
                
        for pattern in breedte_patterns:
            if re.search(pattern, field_text):
                return 'breedte'
        
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
        
    def __del__(self):
        if hasattr(self, 'driver') and self.driver:
            try:
                self.driver.quit()
            except:
                pass 