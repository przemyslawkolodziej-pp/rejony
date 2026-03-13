import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
import re
import time
import math

# --- KONFIGURACJA STRONY ---
st.set_page_config(page_title="Optymalizator Kurierski", layout="wide")

st.title("🚚 Optymalizator Trasy: Szczawin Kościelny i okolice")
st.markdown("Aplikacja wyciąga adresy z pliku KML, znajduje ich współrzędne i układa trasę od Startu do Mety.")

# --- FUNKCJE POMOCNICZE ---

def parse_addresses_from_kml(file_content):
    """Wyciąga dane adresowe z tagów ExtendedData w pliku KML."""
    pnas = re.findall(r'<Data name="PNA_DORECZ">\s*<value>(.*?)</value>', file_content)
    miejsca = re.findall(r'<Data name="MIEJSC_DORECZ">\s*<value>(.*?)</value>', file_content)
    ulice = re.findall(r'<Data name="ULICA_DORECZ">\s*<value>(.*?)</value>', file_content)
    numery = re.findall(r'<Data name="NR_DOM_DORECZ">\s*<value>(.*?)</value>', file_content)
    
    data = []
    for p, m, u, n in zip(pnas, miejsca, ulice, numery):
        full_addr = f"{u} {n}, {p} {m}, Polska"
        display_name = f"{m}, ul. {u} {n}"
        data.append({"address": full_addr, "display_name": display_name})
    
    return pd.DataFrame(data)

def geocode_points(df):
    """Zamienia adresy tekstowe na współrzędne geograficzne."""
    geolocator = Nominatim(user_agent="my_route_optimizer_app_v3")
    lats, lngs = [], []
    
    progress_text = "Trwa geokodowanie adresów... Proszę czekać (limit 1 zapytanie/sek)."
    my_bar = st.progress(0, text=progress_text)
    
    for i, row in df.iterrows():
        try:
            time.sleep(1.1)  # Wymóg darmowego serwera Nominatim
            location = geolocator.geocode(row['address'])
            if location:
                lats.append(location.latitude)
                lngs.append(location.longitude)
            else:
                lats.append(None)
                lngs.append(None)
        except:
            lats.append(None)
            lngs.append(None)
        
        my_bar.progress((i + 1) / len(df), text=f"Przetworzono {i+1} z {len(df)} adresów")
    
    df['lat'] = lats
    df['lng'] = lngs
    return df.dropna(subset=['lat', 'lng']).reset_index(drop=True)

def calculate_distance(p1, p2):
    """Odległość euklidesowa."""
    return math.sqrt((p1['lat'] - p2['lat'])**2 + (p1['lng'] - p2['lng'])**2)

def optimize_route(df, start_idx, end_idx):
    """Algorytm Najbliższego Sąsiada z uwzględnieniem punktu startu i mety."""
    unvisited = df.to_dict('records')
    
    start_node = unvisited.pop(start_idx)
    # Po wyjęciu startu musimy znaleźć nowy indeks mety
    end_node = None
    for i, node in enumerate(unvisited):
        if node['display_name'] == df.iloc[end_idx]['display_name']:
            end_node = unvisited.pop(i)
            break
            
    route = [start_node]
    current = start_node
    
    # Jeśli meta była jedynym innym punktem, po prostu ją dodaj
    if not unvisited and end_node:
        route.append(end_node)
        return pd.DataFrame(route)

    while unvisited:
        next_node = min(unvisited, key=lambda x: calculate_distance(current, x))
        route.append(next_node)
        unvisited.remove(next_node)
        current = next_node
        
    if end_node:
        route.append(end_node)
        
    return pd.DataFrame(route)

# --- LOGIKA APLIKACJI ---

uploaded_file = st.sidebar.file_uploader("Wgraj plik KML (ten bez koordynat)", type=['txt', 'kml'])

if uploaded_file:
    content = uploaded_file.read().decode('utf-8')
    
    # Inicjalizacja danych w sesji
    if 'raw_df' not in st.session_state:
        st.session_state['raw_df'] = parse_addresses_from_kml(content)

    raw_df = st.session_state['raw_df']
    st.sidebar.write(f"Wczytano {len(raw_df)} adresów.")

    if st.sidebar.button("🌍 1. Znajdź punkty na mapie"):
        with st.spinner("Geokodowanie..."):
            geocoded_df = geocode_points(raw_df)
            st.session_state['data'] = geocoded_df
            if 'optimized' in st.session_state: del st.session_state['optimized']

    if 'data' in st.session_state:
        df = st.session_state['data']
        
        st.divider()
        c1, c2 = st.columns(2)
        with c1:
            start_name = st.selectbox("Wybierz punkt STARTOWY:", df['display_name'], index=0)
        with c2:
            # Domyślnie ostatni na liście jako meta
            end_name = st.selectbox("Wybierz punkt DOCELOWY (Metę):", df['display_name'], index=len(df)-1)

        if st.button("🚀 2. Optymalizuj trasę"):
            s_idx = df[df['display_name'] == start_name].index[0]
            e_idx = df[df['display_name'] == end_name].index[0]
            
            if s_idx == e_idx:
                st.error("Punkt startowy i docelowy nie mogą być takie same!")
            else:
                optimized_df = optimize_route(df, s_idx, e_idx)
                st.session_state['optimized'] = optimized_df
                st.balloons()

        # --- WYŚWIETLANIE WYNIKÓW ---
        current_df = st.session_state.get('optimized', df)
        
        col_list, col_map = st.columns([1, 2])
        
        with col_list:
            st.subheader("📋 Plan podróży")
            st.dataframe(current_df[['display_name']], use_container_width=True, height=500)
            if st.button("Resetuj trasę"):
                if 'optimized' in st.session_state: del st.session_state['optimized']
                st.rerun()

        with col_map:
            st.subheader("🗺️ Mapa")
            
            # Tworzenie obiektu mapy
            m = folium.Map(location=[current_df['lat'].mean(), current_df['lng'].mean()], zoom_start=12)
            
            path_points = []
            for i, row in current_df.iterrows():
                # Kolory ikon
                if i == 0:
                    icon_color = 'green'
                    tooltip = "START"
                elif 'optimized' in st.session_state and i == len(current_df) - 1:
                    icon_color = 'red'
                    tooltip = "META"
                else:
                    icon_color = 'blue'
                    tooltip = f"Punkt {i+1}"
                
                folium.Marker(
                    [row['lat'], row['lng']],
                    popup=row['display_name'],
                    tooltip=f"{tooltip}: {row['display_name']}",
                    icon=folium.Icon(color=icon_color, icon='info-sign')
                ).addTo(m)
                
                path_points.append([row['lat'], row['lng']])
            
            # Linia trasy
            if 'optimized' in st.session_state and len(path_points) > 1:
                folium.PolyLine(path_points, color="royalblue", weight=5, opacity=0.8).addTo(m)
            
            st_folium(m, width="100%", height=600, key="map_view")

else:
    st.info("👈 Wgraj plik KML/TXT w panelu bocznym, aby rozpocząć.")
