import streamlit as st
from scraper import MaterialScraper
from price_calculator import PriceCalculator
import threading
from api import app
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

def run_api():
    """Start de FastAPI server in een aparte thread"""
    uvicorn.run(app, host="127.0.0.1", port=8080)

def get_scraper():
    """Geeft een instantie van de MaterialScraper"""
    return MaterialScraper()

def get_calculator():
    """Geeft een instantie van de PriceCalculator"""
    return PriceCalculator()

def display_field_details(field):
    """Toont details van een gevonden veld"""
    if field.get('label'):
        st.write(f"Label: {field['label']}")
    if field.get('id'):
        st.write(f"ID: {field['id']}")
    if field.get('name'):
        st.write(f"Name: {field['name']}")
    if field.get('value'):
        st.write(f"Value: {field['value']}")
    if field.get('type'):
        st.write(f"Type: {field['type']}")

def main():
    # Start de API server in een aparte thread
    api_thread = threading.Thread(target=run_api, daemon=True)
    api_thread.start()

    # Page config
    st.set_page_config(
        page_title="Materiaal Dimensie Analyzer",
        page_icon="🔍",
        layout="wide"
    )
    
    # Tabs voor UI en API
    tab_ui, tab_api = st.tabs(["Web Interface", "API Documentatie"])
    
    with tab_ui:
        # Sidebar configuratie
        with st.sidebar:
            st.title("⚙️ Configuratie")
            show_raw_json = st.toggle("Toon ruwe JSON data", False)
            calculate_price = st.toggle("Bereken prijs", False)
            
            if calculate_price:
                st.divider()
                st.subheader("📐 Afmetingen")
                dimensions = {
                    'dikte': st.number_input("Dikte (mm)", min_value=1, value=2, step=1),
                    'lengte': st.number_input("Lengte (mm)", min_value=1, value=1000, step=1),
                    'breedte': st.number_input("Breedte (mm)", min_value=1, value=1000, step=1)
                }
            
            st.divider()
            st.markdown("""
            ### Help
            Deze tool analyseert webpagina's op zoek naar:
            - Dikte velden (2-30mm)
            - Lengte/hoogte velden
            - Breedte velden
            """)
        
        # Hoofdcontent
        st.title("🔍 Materiaal Dimensie Analyzer")
        st.write("Voer een URL in om de dimensie velden te analyseren.")
        
        # URL input met history
        url = st.text_input(
            "Website URL",
            placeholder="https://voorbeeld.nl/product",
            help="Voer de volledige URL in van de productpagina"
        )
        
        # Analyze knop (geen form nodig voor enkele input)
        if st.button("Analyseer Dimensie Velden", type="primary"):
            if not url:
                st.error("⚠️ Voer eerst een URL in!")
                return
            
            try:
                with st.spinner("🔍 Bezig met analyseren..."):
                    scraper = get_scraper()
                    results = scraper.analyze_form_fields(url)
                    
                    if results and any(results['dimension_fields'].values()):
                        st.success("✅ Analyse succesvol!")
                        
                        # Dimensie tabs
                        dimension_types = {
                            'dikte': '📏 Dikte',
                            'lengte': '📐 Lengte/Hoogte',
                            'breedte': '⬌ Breedte',
                            'prijs': '💰 Prijs'
                        }
                        
                        tab_dikte, tab_lengte, tab_breedte, tab_prijs = st.tabs(dimension_types.values())
                        
                        # Dikte tab
                        with tab_dikte:
                            fields = results['dimension_fields']['dikte']
                            if fields:
                                st.write(f"{len(fields)} dikte veld(en) gevonden")
                                for i, field in enumerate(fields, 1):
                                    st.subheader(f"Veld {i}")
                                    display_field_details(field)
                            else:
                                st.info("Geen dikte velden gevonden")
                        
                        # Lengte tab
                        with tab_lengte:
                            fields = results['dimension_fields']['lengte']
                            if fields:
                                st.write(f"{len(fields)} lengte/hoogte veld(en) gevonden")
                                for i, field in enumerate(fields, 1):
                                    st.subheader(f"Veld {i}")
                                    display_field_details(field)
                            else:
                                st.info("Geen lengte/hoogte velden gevonden")
                        
                        # Breedte tab
                        with tab_breedte:
                            fields = results['dimension_fields']['breedte']
                            if fields:
                                st.write(f"{len(fields)} breedte veld(en) gevonden")
                                for i, field in enumerate(fields, 1):
                                    st.subheader(f"Veld {i}")
                                    display_field_details(field)
                            else:
                                st.info("Geen breedte velden gevonden")
                        
                        # Prijs tab
                        with tab_prijs:
                            fields = results['dimension_fields']['prijs']
                            if fields:
                                st.write(f"{len(fields)} prijs veld(en) gevonden")
                                for i, field in enumerate(fields, 1):
                                    st.subheader(f"Veld {i}")
                                    if field.get('is_m2_price'):
                                        st.success("✅ Dit is een m² prijs!")
                                    if field.get('price_type'):
                                        st.info(f"Type: {field['price_type']} prijs")
                                    if field.get('price_value'):
                                        st.metric("Gevonden prijs", f"€ {field['price_value']}")
                                    display_field_details(field)
                            else:
                                st.info("Geen prijs velden gevonden")
                        
                        # Bereken prijs als gewenst
                        if calculate_price:
                            st.divider()
                            st.subheader("💰 Prijsberekening")
                            
                            with st.spinner("💭 Bezig met prijsberekening..."):
                                calculator = get_calculator()
                                prices = calculator.calculate_price(
                                    url=url,
                                    dimension_fields=results['dimension_fields'],
                                    dimensions=dimensions
                                )
                                
                                if prices:
                                    excl_btw, incl_btw = prices  # Unpack de tuple
                                    col1, col2 = st.columns(2)
                                    with col1:
                                        st.metric("Prijs excl. BTW", f"€ {excl_btw:.2f}")
                                        oppervlakte = dimensions['lengte'] * dimensions['breedte'] / 1000000  # mm² naar m²
                                        st.metric("Oppervlakte", f"{oppervlakte:.2f} m²")
                                    with col2:
                                        st.metric("Prijs incl. BTW", f"€ {incl_btw:.2f}")
                                        st.metric("Dikte", f"{dimensions['dikte']} mm")
                        
                        # JSON data
                        if show_raw_json:
                            st.divider()
                            st.subheader("🔧 Ruwe JSON Data")
                            st.json(results)
                    else:
                        st.warning("❌ Geen dimensie velden gevonden op deze pagina")
                        
            except Exception as e:
                st.error(f"❌ Er is een fout opgetreden: {str(e)}")
    
    with tab_api:
        st.header("API Documentatie")
        st.markdown("""
        ### Analyze Endpoint
        
        **URL:** `/analyze`  
        **Method:** `POST`  
        **Request Body:**
        ```json
        {
            "url": "string"
        }
        ```
        
        **Response:**
        ```json
        {
            "url": "string",
            "dimension_fields": {
                "dikte": [...],
                "lengte": [...],
                "breedte": [...],
                "prijs": [...]
            }
        }
        ```
        
        ### Price Endpoint
        
        **URL:** `/price`  
        **Method:** `POST`  
        **Request Body:**
        ```json
        {
            "url": "string",
            "dimensions": {
                "dikte": float,
                "lengte": float,
                "breedte": float
            }
        }
        ```
        
        **Response:**
        ```json
        {
            "price_excl_btw": float,
            "price_incl_btw": float
        }
        ```
        
        ### Python Voorbeeld
        ```python
        import requests
        
        # Analyze endpoint
        response = requests.post(
            "https://your-app.streamlit.app/analyze",
            json={"url": "https://example.com/product"}
        )
        results = response.json()
        
        # Price endpoint
        response = requests.post(
            "https://your-app.streamlit.app/price",
            json={
                "url": "https://example.com/product",
                "dimensions": {
                    "dikte": 2.0,
                    "lengte": 1000.0,
                    "breedte": 1000.0
                }
            }
        )
        prices = response.json()
        ```
        """)

if __name__ == "__main__":
    main()