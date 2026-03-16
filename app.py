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

st.title("🗺️ Uniwersalny Optymalizator Tras")

# --- FUNKCJE POMOCNICZE ---

def parse_any_kml(file_content):
    """Wyciąga dane adresowe z pliku KML."""
    pnas = re.findall(r'<Data name=".*?PNA.*?">\s*<value>(.*?)</value>', file_content, re.IGNORECASE)
    miejsca = re.findall(r'<Data name=".*?MIEJSC.*?">\s*<value>(.*?)</value>', file_content, re.IGNORECASE)
    ulice = re.findall(r'<Data name=".*?ULICA.*?">\s*<value>(.*?)</value>', file_content, re.IGNORECASE)
    numery = re.findall(r'<Data name=".*?NR_DOM.*?">\s*<value>(.*?)</value>', file_content, re.IGNORECASE)
    
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
    """Zamienia adresy na współrzędne z obsługą błędów."""
    geolocator = Nominatim(user_agent="route_optimizer_v5_final")
    lats, lngs = [], []
    
    my_bar = st.progress(0)
    status_text = st.empty()
    
    for i, row in df.iterrows():
        try:
            status_text.text(f"📍 Lokalizowanie ({i+1}/{len(df)}): {row['display_name']}")
            time.sleep(1.2)  # Bezpieczny odstęp dla darmowego serwera
            location = geolocator.geocode(row['address'], timeout=10)
            if location:
                lats.append(location.latitude)
                lngs.append(location.longitude)
            else:
                lats.append(None)
                lngs.append(None)
        except Exception as e:
            st.warning(f"Problem z adresem {row['display_name']}: {e}")
            lats.append(None)
            lngs.append(None)
        
        my_bar.progress((i + 1) / len(df))
    
    df['lat'] = lats
    df['lng'] = lngs
    status_text.empty()
    return df.dropna(subset=['lat', 'lng']).reset_index(drop=True)

def calculate_distance(p1, p2):
    return math.sqrt((p1['lat'] - p2['lat'])**2 + (p1['lng'] - p2['lng'])**2)

def optimize_route(df, start_idx, end_idx):
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

# --- OBSŁUGA PLIKU ---
uploaded_file = st.sidebar.file_uploader("Wgraj plik KML/TXT", type=['kml', 'txt'])

if uploaded_file:
    # Zarządzanie sesją przy zmianie pliku
    if 'current_filename' not in st.session_state or st.session_state['current_filename'] != uploaded_file.name:
        st.session_state['current_filename'] = uploaded_file.name
        content = uploaded_file.read().decode('utf-8')
        st.session_state['raw_df'] = parse_any_kml(content)
        if 'data' in st.session_state: del st.session_state['data']
        if 'optimized' in st.session_state: del st.session_state['optimized']

    raw_df = st.session_state['raw_df']
    st.sidebar.info(f"Wczytano {len(raw_df)} adresów.")

    if st.sidebar.button("🌍 1. Znajdź punkty na mapie", use_container_width=True):
        geocoded_res = geocode_points(raw_df)
        if not geocoded_res.empty:
            st.session_state['data'] = geocoded_res
            st.rerun()

    # --- PANEL GŁÓWNY ---
    if 'data' in st.session_state:
        df = st.session_state['data']
        
        st.write("### ⚙️ Ustawienia trasy")
        c1, c2 = st.columns(2)
        with c1:
            start_name = st.selectbox("Start:", df['display_name'], index=0)
        with c2:
            end_name = st.selectbox("Meta:", df['display_name'], index=len(df)-1)

        if st.button("🚀 2. Oblicz optymalną trasę", type="primary", use_container_width=True):
            s_idx = df[df['display_name'] == start_name].index[0]
            e_idx = df[df['display_name'] == end_name].index[0]
            st.session_state['optimized'] = optimize_route(df, s_idx, e_idx)

        # --- WIDOK MAPY I LISTY ---
        current_df = st.session_state.get('optimized', df)
        
        col_list, col_map = st.columns([1, 2])
        
        with col_list:
            st.subheader("📋 Plan")
            st.dataframe(current_df[['display_name']], use_container_width=True, height=500)
            if st.button("Skasuj trasę"):
                if 'optimized' in st.session_state: del st.session_state['optimized']
                st.rerun()

        with col_map:
            st.subheader("🗺️ Mapa")
            
            # Tworzymy mapę TYLKO gdy mamy współrzędne
            if not current_df.empty:
                m = folium.Map(location=[current_df['lat'].mean(), current_df['lng'].mean()], zoom_start=11)
                
                path_coords = []
                for i, row in current_df.iterrows():
                    color = 'blue'
                    if i == 0: color = 'green'
                    elif 'optimized' in st.session_state and i == len(current_df)-1: color = 'red'
                    
                    folium.Marker(
                        location=[row['lat'], row['lng']],
                        popup=row['display_name'],
                        tooltip=f"{i+1}. {row['display_name']}",
                        icon=folium.Icon(color=color, icon='info-sign')
                    ).addTo(m)
                    path_coords.append([row['lat'], row['lng']])
                
                if 'optimized' in st.session_state and len(path_coords) > 1:
                    folium.PolyLine(path_coords, color="royalblue", weight=4).addTo(m)
                
                st_folium(m, width="100%", height=500, key="map_stable")
    else:
        st.warning("Kliknij przycisk w panelu bocznym, aby zlokalizować adresy na mapie.")
else:
    st.info("👈 Wgraj plik, aby rozpocząć.")
