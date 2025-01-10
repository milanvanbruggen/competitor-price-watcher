import streamlit as st
from scraper import MaterialScraper
from price_calculator import PriceCalculator
import json

# Cache de scraper instantie om hergebruik mogelijk te maken
@st.cache_resource
def get_scraper():
    return MaterialScraper()

@st.cache_resource
def get_calculator():
    return PriceCalculator()

def display_field_details(field):
    """Helper functie om veld details weer te geven"""
    # Belangrijkste attributen in kolommen
    col1, col2 = st.columns(2)
    
    with col1:
        if field.get('label'):
            st.metric("Label", field['label'])
        if field.get('id'):
            st.metric("ID", field['id'])
        if field.get('name'):
            st.metric("Name", field['name'])
    
    with col2:
        if field.get('type'):
            st.metric("Type", field['type'])
        if field.get('value'):
            st.metric("Value", field['value'])
    
    # Overige attributen
    other_attrs = {k: v for k, v in field.items() 
                  if k not in ['label', 'id', 'name', 'type', 'value']}
    if other_attrs:
        with st.expander("Meer eigenschappen"):
            for key, value in other_attrs.items():
                st.text(f"{key}: {value}")

def main():
    # Page config
    st.set_page_config(
        page_title="Materiaal Dimensie Analyzer",
        page_icon="🔍",
        layout="wide"
    )
    
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
                    else:
                        st.error("❌ Kon geen prijs vinden op de pagina")
                
                # JSON data
                if show_raw_json:
                    st.divider()
                    st.subheader("🔧 Ruwe JSON Data")
                    st.json(results)
            else:
                st.warning("❌ Geen dimensie velden gevonden op deze pagina")

        except Exception as e:
            st.error(f"❌ Er is een fout opgetreden: {str(e)}")

if __name__ == "__main__":
    main()