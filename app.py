import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
import re
import time
import math

# --- KONFIGURACJA STRONY ---
st.set_page_config(page_title="Optymalizator Tras", layout="wide")

st.title("Optymalizator Tras")

# --- FUNKCJE POMOCNICZE ---

def parse_any_kml(file_content):
    pnas = re.findall(r'<Data name=".*?PNA.*?">\s*<value>(.*?)</value>', file_content, re.IGNORECASE)
    miejsca = re.findall(r'<Data name=".*?MIEJSC.*?">\s*<value>(.*?)</value>', file_content, re.IGNORECASE)
    ulice = re.findall(r'<Data name=".*?ULICA.*?">\s*<value>(.*?)</value>', file_content, re.IGNORECASE)
    numery = re.findall(r'<Data name=".*?NR_DOM.*?">\s*<value>(.*?)</value>', file_content, re.IGNORECASE)
    
    data = []
    if miejsca:
        for p, m, u, n in zip(pnas, miejsca, ulice, numery):
            full_addr = f"{u} {n}, {p} {m}, Polska"
            display_name = f"{m}, {u} {n}"
            data.append({"address": full_addr, "display_name": display_name})
    else:
        names = re.findall(r'<Placemark>.*?<name>(.*?)</name>', file_content, re.DOTALL)
        data = [{"address": n, "display_name": n} for n in names]
    
    return pd.DataFrame(data)

def geocode_single(address, geolocator):
    try:
        time.sleep(1.2)
        location = geolocator.geocode(address, timeout=10)
        if location:
            return location.latitude, location.longitude
    except:
        pass
    return None, None

def geocode_points(df):
    geolocator = Nominatim(user_agent="route_optimizer_v10")
    lats, lngs = [], []
    my_bar = st.progress(0)
    status_text = st.empty()
    
    for i, row in df.iterrows():
        status_text.text(f"📍 Lokalizowanie ({i+1}/{len(df)}): {row['display_name']}")
        lat, lng = geocode_single(row['address'], geolocator)
        lats.append(lat)
        lngs.append(lng)
        my_bar.progress((i + 1) / len(df))
    
    df['lat'] = lats
    df['lng'] = lngs
    status_text.empty()
    return df.dropna(subset=['lat', 'lng']).reset_index(drop=True)

def calculate_distance(p1, p2):
    return math.sqrt((p1['lat'] - p2['lat'])**2 + (p1['lng'] - p2['lng'])**2)

def optimize_route(df, start_node, end_node):
    # Punkty do odwiedzenia (wszystkie poza startem i metą z okienek)
    to_visit = df[(df['display_name'] != "🏠 MÓJ START") & (df['display_name'] != "🏁 MOJA META")].to_dict('records')
    
    route = [start_node]
    current = start_node
    
    while to_visit:
        next_node = min(to_visit, key=lambda x: calculate_distance(current, x))
        route.append(next_node)
        to_visit.remove(next_node)
        current = next_node
        
    route.append(end_node)
    return pd.DataFrame(route)

# --- PANEL BOCZNY ---
st.sidebar.header("🏠 Punkty Stałe")
custom_start = st.sidebar.text_input("Adres STARTU:", placeholder="Ulica, Numer, Miasto")
custom_meta = st.sidebar.text_input("Adres METY:", placeholder="Ulica, Numer, Miasto")

st.sidebar.divider()
st.sidebar.header("📁 Pliki Rejonów")
uploaded_file = st.sidebar.file_uploader("Wgraj plik KML/TXT", type=['kml', 'txt'])

# Inicjalizacja bazy punktów w sesji
if 'data' not in st.session_state:
    st.session_state['data'] = pd.DataFrame(columns=['address', 'display_name', 'lat', 'lng'])

if uploaded_file:
    if st.sidebar.button("➕ Dodaj punkty z tego plika", use_container_width=True):
        content = uploaded_file.read().decode('utf-8')
        new_raw = parse_any_kml(content)
        new_geocoded = geocode_points(new_raw)
        
        # Łączenie z istniejącymi punktami
        st.session_state['data'] = pd.concat([st.session_state['data'], new_geocoded], ignore_index=True).drop_duplicates(subset=['address'])
        st.sidebar.success(f"Dodano punkty! Łącznie masz ich: {len(st.session_state['data'])}")

if st.sidebar.button("🗑️ Wyczyść wszystko", use_container_width=True):
    st.session_state['data'] = pd.DataFrame(columns=['address', 'display_name', 'lat', 'lng'])
    if 'optimized' in st.session_state: del st.session_state['optimized']
    st.rerun()

# --- PANEL GŁÓWNY ---
if not st.session_state['data'].empty:
    df = st.session_state['data']
    
    st.write(f"### ⚙️ Optymalizacja (Liczba punktów: {len(df)})")
    st.info(f"Trasa: {custom_start if custom_start else 'brak'} ➡️ {len(df)} punktów ➡️ {custom_meta if custom_meta else 'brak'}")

    if st.button("🚀 Oblicz optymalną trasę", type="primary", use_container_width=True):
        if not custom_start or not custom_meta:
            st.error("Wpisz adres Startu i Mety w panelu bocznym!")
        else:
            geolocator = Nominatim(user_agent="route_optimizer_v10")
            
            # Geokodowanie bazy start/meta tylko przy obliczaniu
            s_lat, s_lng = geocode_single(custom_start, geolocator)
            m_lat, m_lng = geocode_single(custom_meta, geolocator)
            
            if s_lat and m_lat:
                start_node = {"address": custom_start, "display_name": "🏠 MÓJ START", "lat": s_lat, "lng": s_lng}
                end_node = {"address": custom_meta, "display_name": "🏁 MOJA META", "lat": m_lat, "lng": m_lng}
                
                st.session_state['optimized'] = optimize_route(df, start_node, end_node)
            else:
                st.error("Nie znaleziono adresu Startu lub Mety. Sprawdź pisownię.")

    # WYNIKI
    res_df = st.session_state.get('optimized', df)
    
    col_l, col_r = st.columns([1, 2])
    with col_l:
        st.subheader("📋 Plan")
        st.dataframe(res_df[['display_name']], use_container_width=True, height=600)

    with col_r:
        st.subheader("🗺️ Mapa")
        try:
            m = folium.Map(location=[res_df['lat'].mean(), res_df['lng'].mean()], zoom_start=11)
            pts = []
            for i, row in res_df.iterrows():
                color = 'blue'
                if i == 0: color = 'green'
                elif 'optimized' in st.session_state and i == len(res_df)-1: color = 'red'
                
                folium.Marker(
                    [row['lat'], row['lng']],
                    tooltip=f"{i+1}. {row['display_name']}",
                    icon=folium.Icon(color=color, icon='info-sign')
                ).addTo(m)
                pts.append([row['lat'], row['lng']])
            
            if 'optimized' in st.session_state and len(pts) > 1:
                folium.PolyLine(pts, color="royalblue", weight=4).addTo(m)
            
            st_folium(m, width="100%", height=600, key="v10_map")
        except:
            st.write("Wgraj dane, aby zobaczyć mapę.")
else:
    st.info("👈 Wpisz adresy start/meta i dodaj pierwszy plik KML/TXT.")
