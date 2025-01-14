import os
import json
from urllib.parse import urlparse
from typing import Optional, Dict, Any
import logging

class DomainConfig:
    def __init__(self):
        self.configs: Dict[str, Any] = {}
        self._load_configs()
    
    def _load_configs(self):
        """Laad alle domein configuraties uit de config/domains directory"""
        config_dir = os.path.join('config', 'domains')
        logging.info(f"Loading configurations from {config_dir}")
        
        try:
            for filename in os.listdir(config_dir):
                if filename.endswith('.json'):
                    filepath = os.path.join(config_dir, filename)
                    logging.info(f"Loading configuration from {filepath}")
                    try:
                        with open(filepath, 'r') as f:
                            config = json.load(f)
                            self.configs[config['domain']] = config
                            logging.info(f"Loaded configuration for domain: {config['domain']}")
                    except Exception as e:
                        logging.error(f"Error loading {filepath}: {str(e)}")
        except Exception as e:
            logging.error(f"Error accessing config directory: {str(e)}")
            
        logging.info(f"Loaded {len(self.configs)} domain configurations")
    
    def get_config(self, url: str) -> Optional[Dict[str, Any]]:
        """Haal de configuratie op voor een specifieke URL"""
        domain = urlparse(url).netloc.replace('www.', '')
        logging.info(f"Getting configuration for domain: {domain}")
        config = self.configs.get(domain)
        if config:
            logging.info(f"Found configuration for {domain}")
        else:
            logging.warning(f"No configuration found for {domain}")
        return config
    
    def get_selector(self, url: str, field_type: str) -> Optional[Dict[str, Any]]:
        """Haal de selector configuratie op voor een specifiek veld type"""
        config = self.get_config(url)
        if config and 'selectors' in config:
            return config['selectors'].get(field_type)
        return None
    
    def get_units(self, url: str) -> Dict[str, str]:
        """Haal de eenheden configuratie op"""
        config = self.get_config(url)
        if config and 'units' in config:
            return config['units']
        return {'thickness': 'mm', 'dimensions': 'mm'}  # defaults
    
    def get_price_config(self, url: str) -> Optional[Dict[str, Any]]:
        """Haal de prijs configuratie op"""
        config = self.get_config(url)
        if config and 'price' in config:
            return config['price']
        return None 