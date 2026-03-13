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
    except Exception as e:
        st.error(f"Błąd podczas czytania pliku: {e}")
        return None

# 4. Główna sekcja wyświetlania
if uploaded_file:
    df = parse_kml(uploaded_file)
    
    if df is not None and not df.empty:
        col1, col2 = st.columns([1, 2])
        
        with col1:
            st.subheader("📋 Lista punktów")
            st.write(f"Znaleziono punktów: **{len(df)}**")
            st.dataframe(df[['name']], use_container_width=True, height=400)
            
        with col2:
            st.subheader("🗺️ Podgląd mapy")
            
            # Centrowanie mapy na średnich współrzędnych
            m = folium.Map(location=[df.lat.mean(), df.lng.mean()], zoom_start=10)
            
            # Dodawanie pinezek na mapę
            for _, row in df.iterrows():
                # Logika kolorów ikon
                icon_color = 'blue'
                if row['name'].lower() == start_point.lower():
                    icon_color = 'green'
                elif row['name'].lower() == end_point.lower():
                    icon_color = 'red'
                
                folium.Marker(
                    [row.lat, row.lng], 
                    popup=row['name'],
                    tooltip=row['name'],
                    icon=folium.Icon(color=icon_color, icon='info-sign')
                ).addTo(m)
            
            # Logika po kliknięciu przycisku optymalizacji
            if optimize_btn:
                st.info("Algorytm optymalizacji (TSP) zostanie uruchomiony tutaj.")
                # Na razie rysujemy linię w kolejności z pliku jako demonstrację
                folium.PolyLine(
                    df[['lat', 'lng']].values, 
                    color="royalblue", 
                    weight=4, 
                    opacity=0.7,
                    dash_array='10'
                ).addTo(m)
                
                st.success("Trasa została wyznaczona (podgląd kolejności z pliku).")
            
            # Wyświetlenie mapy w Streamlit
            st_folium(m, width="100%", height=500)
    else:
        st.warning("Plik KML nie zawiera poprawnych punktów geograficznych.")
else:
    st.info("👈 Zacznij od wgrania pliku KML w panelu bocznym.")

# 5. Stopka
st.divider()
st.caption("Aplikacja stworzona do optymalizacji logistyki. Dane nie są zapisywane na serwerze.")
