import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
import re
import time
import math

# --- KONFIGURACJA STRONY ---
st.set_page_config(page_title="Universal Route Optimizer", layout="wide")

st.title("🗺️ Optymalizator Tras Kurierskich")
st.markdown("""
Ta aplikacja działa z dowolnym plikiem KML z Google My Maps. 
Automatycznie wykrywa adresy, znajduje współrzędne i układa najkrótszą drogę między wybranymi punktami.
""")

# --- FUNKCJE POMOCNICZE ---

def parse_any_kml(file_content):
    """Przeszukuje plik KML w poszukiwaniu danych adresowych w różnych formatach."""
    # Szukamy najczęstszych nazw pól adresowych stosowanych przez Google/Excel
    pnas = re.findall(r'<Data name=".*?PNA.*?">\s*<value>(.*?)</value>', file_content, re.IGNORECASE)
    miejsca = re.findall(r'<Data name=".*?MIEJSC.*?">\s*<value>(.*?)</value>', file_content, re.IGNORECASE)
    ulice = re.findall(r'<Data name=".*?ULICA.*?">\s*<value>(.*?)</value>', file_content, re.IGNORECASE)
    numery = re.findall(r'<Data name=".*?NR_DOM.*?">\s*<value>(.*?)</value>', file_content, re.IGNORECASE)
    
    # Jeśli nie znaleziono standardowych nazw, spróbuj wyciągnąć pozycje z nazw Placemarków
    if not miejsca:
        names = re.findall(r'<Placemark>.*?<name>(.*?)</name>', file_content, re.DOTALL)
        data = [{"address": n, "display_name": n} for n in names]
    else:
        data = []
        for p, m, u, n in zip(pnas, miejsca, ulice, numery):
            full_addr = f"{u} {n}, {p} {m}, Polska"
            display_name = f"{m}, {u} {n}"
            data.append({"address": full_addr, "display_name": display_name})
    
    return pd.DataFrame(data)

def geocode_points(df):
    """Zamienia adresy na współrzędne."""
    geolocator = Nominatim(user_agent="universal_route_optimizer_v4")
    lats, lngs = [], []
    
    my_bar = st.progress(0, text="Lokalizowanie punktów na mapie...")
    
    for i, row in df.iterrows():
        try:
            time.sleep(1.1) # Wymóg darmowego API
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
        
        my_bar.progress((i + 1) / len(df), text=f"Lokalizacja: {i+1} / {len(df)}")
    
    df['lat'] = lats
    df['lng'] = lngs
    return df.dropna(subset=['lat', 'lng']).reset_index(drop=True)

def calculate_distance(p1, p2):
    """Dystans między punktami."""
    return math.sqrt((p1['lat'] - p2['lat'])**2 + (p1['lng'] - p2['lng'])**2)

def optimize_route(df, start_idx, end_idx):
    """Algorytm Najbliższego Sąsiada."""
    unvisited = df.to_dict('records')
    
    start_node = unvisited.pop(start_idx)
    end_node = None
    for i, node in enumerate(unvisited):
        if node['display_name'] == df.iloc[end_idx]['display_name']:
            end_node = unvisited.pop(i)
            break
            
    route = [start_node]
    current = start_node
    
    while unvisited:
        next_node = min(unvisited, key=lambda x: calculate_distance(current, x))
        route.append(next_node)
        unvisited.remove(next_node)
        current = next_node
        
    if end_node:
        route.append(end_node)
        
    return pd.DataFrame(route)

# --- PANEL BOCZNY ---
st.sidebar.header("📁 Wczytywanie Danych")
uploaded_file = st.sidebar.file_uploader("Wgraj plik KML lub TXT", type=['kml', 'txt'])

if uploaded_file:
    # Czytanie pliku
    content = uploaded_file.read().decode('utf-8')
    
    # Resetowanie sesji przy nowym pliku
    if 'last_uploaded' not in st.session_state or st.session_state['last_uploaded'] != uploaded_file.name:
        st.session_state['last_uploaded'] = uploaded_file.name
        st.session_state['raw_df'] = parse_any_kml(content)
        if 'data' in st.session_state: del st.session_state['data']
        if 'optimized' in st.session_state: del st.session_state['optimized']

    raw_df = st.session_state['raw_df']
    st.sidebar.info(f"Wczytano {len(raw_df)} punktów.")

    if st.sidebar.button("🌍 Znajdź punkty na mapie", use_container_width=True):
        with st.spinner("Przeszukiwanie bazy map..."):
            st.session_state['data'] = geocode_points(raw_df)

    # --- PANEL GŁÓWNY ---
    if 'data' in st.session_state:
        df = st.session_state['data']
        
        st.write("### ⚙️ Konfiguracja Trasy")
        c1, c2 = st.columns(2)
        with c1:
            start_name = st.selectbox("Punkt STARTOWY:", df['display_name'], index=0)
        with c2:
            end_name = st.selectbox("Punkt DOCELOWY (META):", df['display_name'], index=len(df)-1)

        if st.button("🚀 Oblicz optymalną trasę", type="primary", use_container_width=True):
            s_idx = df[df['display_name'] == start_name].index[0]
            e_idx = df[df['display_name'] == end_name].index[0]
            
            if s_idx == e_idx and len(df) > 1:
                st.error("Start i Meta muszą być różnymi punktami!")
            else:
                st.session_state['optimized'] = optimize_route(df, s_idx, e_idx)
                st.balloons()

        # --- WYNIKI ---
        current_df = st.session_state.get('optimized', df)
        
        res_col, map_col = st.columns([1, 2])
        
        with res_col:
            st.subheader("📋 Lista przystanków")
            st.dataframe(current_df[['display_name']], use_container_width=True, height=600)
            if st.button("Wyczyść trasę"):
                if 'optimized' in st.session_state: del st.session_state['optimized']
                st.rerun()

        with map_col:
            st.subheader("🗺️ Mapa interaktywna")
            m = folium.Map(location=[current_df['lat'].mean(), current_df['lng'].mean()], zoom_start=11)
            
            path_pts = []
            for i, row in current_df.iterrows():
                if i == 0: color = 'green'
                elif 'optimized' in st.session_state and i == len(current_df)-1: color = 'red'
                else: color = 'blue'
                
                folium.Marker(
                    [row['lat'], row['lng']],
                    popup=row['display_name'],
                    tooltip=f"{i+1}. {row['display_name']}",
                    icon=folium.Icon(color=color, icon='info-sign')
                ).addTo(m)
                path_pts.append([row['lat'], row['lng']])
            
            if 'optimized' in st.session_state and len(path_pts) > 1:
                folium.PolyLine(path_pts, color="royalblue", weight=5, opacity=0.8).addTo(m)
            
            st_folium(m, width="100%", height=600, key="universal_map")
else:
    st.info("👈 Wgraj plik z rejonem (KML/TXT), aby rozpocząć pracę.")
