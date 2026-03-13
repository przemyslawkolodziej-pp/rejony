import streamlit as st
import folium
from streamlit_folium import st_folium
from pykml import parser
import pandas as pd

# 1. Konfiguracja strony (musi być na samym początku kodu)
st.set_page_config(
    page_title="Optymalizator Tras KML",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("📍 Mój Optymalizator Tras z Google My Maps")
st.markdown("""
Ta aplikacja pozwala wczytać plik KML z Twoimi pinezkami, wyświetlić je na mapie i w przyszłości wyznaczyć najkrótszą drogę.
""")

# 2. Panel boczny (Sidebar)
with st.sidebar:
    st.header("⚙️ Ustawienia")
    uploaded_file = st.file_uploader("Wgraj plik KML wyeksportowany z Google", type=['kml'])
    
    st.divider()
    
    start_point = st.text_input("Nazwa punktu START (np. Dom)", "Start")
    end_point = st.text_input("Nazwa punktu META (np. Magazyn)", "Meta")
    
    st.divider()
    
    optimize_btn = st.button("🚀 Oblicz optymalną trasę", type="primary")

# 3. Funkcja do przetwarzania pliku KML
def parse_kml(file):
    try:
        root = parser.parse(file).getroot()
        points = []
        # Standardowa przestrzeń nazw dla plików KML z Google
        ns = {'kml': 'http://www.opengis.net/kml/2.2'}
        
        # Szukanie wszystkich Placemarków (pinezek)
        for pm in root.xpath('.//kml:Placemark', namespaces=ns):
            name = str(pm.name) if hasattr(pm, 'name') else "Bez nazwy"
            # Wyciąganie współrzędnych (longitude, latitude, altitude)
            if hasattr(pm, 'Point') and hasattr(pm.Point, 'coordinates'):
                coords = str(pm.Point.coordinates).strip().split(',')
                points.append({
                    "name": name,
                    "lat": float(coords[1]),
                    "lng": float(coords[0])
                })
        return pd.DataFrame(points)
