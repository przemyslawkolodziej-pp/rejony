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

# --- INICJALIZACJA PAMIĘCI ---
if 'saved_locations' not in st.session_state:
    st.session_state['saved_locations'] = {}

if 'data' not in st.session_state:
    st.session_state['data'] = pd.DataFrame(columns=['address', 'display_name', 'lat', 'lng', 'ready'])
if 'start_addr' not in st.session_state:
    st.session_state['start_addr'] = ""
if 'meta_addr' not in st.session_state:
    st.session_state['meta_addr'] = ""

# --- FUNKCJE POMOCNICZE ---

def parse_kml_smart(file_content):
    placemarks = re.findall(r'<Placemark>(.*?)</Placemark>', file_content, re.DOTALL)
    data = []
    for pm in placemarks:
        name_match = re.search(r'<name>(.*?)</name>', pm)
        name = name_match.group(1) if name_match else "Punkt"
        coords = re.search(r'<coordinates>\s*([\d\.]+),\s*([\d\.]+)', pm)
        if coords:
            data.append({
                "address": name, "display_name": name, 
                "lat": float(coords.group(2)), "lng": float(coords.group(1)), "ready": True
            })
        else:
            msc = re.search(r'<Data name=".*?MIEJSC.*?">\s*<value>(.*?)</value>', pm, re.IGNORECASE)
            ulica = re.search(r'<Data name=".*?ULICA.*?">\s*<value>(.*?)</value>', pm, re.IGNORECASE)
            nr = re.search(r'<Data name=".*?NR_DOM.*?">\s*<value>(.*?)</value>', pm, re.IGNORECASE)
            if msc:
                addr = f"{ulica.group(1) if ulica else ''} {nr.group(1) if nr else ''}, {msc.group(1)}, Polska"
                data.append({
                    "address": addr, 
                    "display_name": f"{msc.group(1)} {ulica.group(1) if ulica else ''} {nr.group(1) if nr else ''}", 
                    "lat": None, "lng": None, "ready": False
                })
    return pd.DataFrame(data)

def geocode_single(address, geolocator):
    try:
        time.sleep(1.1)
        location = geolocator.geocode(address, timeout=10)
        return (location.latitude, location.longitude) if location else (None, None)
    except: return None, None

# --- SIDEBAR: ZARZĄDZANIE PUNKTAMI STAŁYMI ---
st.sidebar.header("📍 Twoje Punkty Stałe")

with st.sidebar.expander("➕ Dodaj nowy punkt"):
    new_name = st.text_input("Nazwa (np. WER Warszawa):")
    new_addr = st.text_input("Pełny adres punktu:")
    if st.button("Zapisz punkt"):
        if new_name and new_addr:
            st.session_state['saved_locations'][new_name] = new_addr
            st.rerun()

if st.session_state['saved_locations']:
    st.sidebar.write("Ustaw jako:")
    for name, addr in st.session_state['saved_locations'].items():
        c1, c2, c3 = st.sidebar.columns([1, 1, 0.4])
        if c1.button(f"S: {name}", use_container_width=True, help=f"Start: {addr}"):
            st.session_state['start_addr'] = addr
        if c2.button(f"M: {name}", use_container_width=True, help=f"Meta: {addr}"):
            st.session_state['meta_addr'] = addr
        if c3.button("🗑️", key=f"del_{name}"):
            del st.session_state['saved_locations'][name]
            st.rerun()
else:
    st.sidebar.info("Lista punktów jest pusta.")

st.sidebar.divider()

# --- SIDEBAR: REJON I PLIKI ---
st.sidebar.header("🚀 Konfiguracja Trasy")
st.session_state['start_addr'] = st.sidebar.text_input("Adres STARTU:", value=st.session_state['start_addr'])
st.session_state['meta_addr'] = st.sidebar.text_input("Adres METY:", value=st.session_state['meta_addr'])

uploaded_file = st.sidebar.file_uploader("Wgraj plik KML/TXT", type=['kml', 'txt'])

if uploaded_file and st.sidebar.button("➕ Dodaj punkty z pliku", use_container_width=True):
    new_df = parse_kml_smart(uploaded_file.read().decode('utf-8'))
    geolocator = Nominatim(user_agent="route_optimizer_v14")
    to_geo = new_df[new_df['lat'].isna()]
    
    if not to_geo.empty:
        prog = st.progress(0)
        for i, (idx, row) in enumerate(to_geo.iterrows()):
            lat, lng = geocode_single(row['address'], geolocator)
            new_df.at[idx, 'lat'], new_df.at[idx, 'lng'] = lat, lng
            prog.progress((i + 1) / len(to_geo))
    
    st.session_state['data'] = pd.concat([st.session_state['data'], new_df.dropna(subset=['lat'])], ignore_index=True).drop_duplicates(subset=['address'])
    st.sidebar.success(f"Dodano! Razem: {len(st.session_state['data'])} pkt.")

if st.sidebar.button("🗑️ Wyczyść listę rejonu", use_container_width=True):
    st.session_state['data'] = pd.DataFrame(columns=['address', 'display_name', 'lat', 'lng', 'ready'])
    if 'optimized' in st.session_state: del st.session_state['optimized']
    st.rerun()

# --- PANEL GŁÓWNY ---
if not st.session_state['data'].empty:
    df = st.session_state['data']
    if st.button("🚀 OBLICZ OPTYMALNĄ TRASĘ", type="primary", use_container_width=True):
        if not st.session_state['start_addr'] or not st.session_state['meta_addr']:
            st.error("Ustaw Start i Metę (użyj punktów stałych lub wpisz adresy).")
        else:
            geolocator = Nominatim(user_agent="route_optimizer_v14")
            s_lat, s_lng = geocode_single(st.session_state['start_addr'], geolocator)
            m_lat, m_lng = geocode_single(st.session_state['meta_addr'], geolocator)
            
            if s_lat and m_lat:
                start_node = {"display_name": "🏠 START", "lat": s_lat, "lng": s_lng}
                end_node = {"display_name": "🏁 META", "lat": m_lat, "lng": m_lng}
                
                unvisited = df.to_dict('records')
                route, current = [start_node], start_node
                while unvisited:
                    next_node = min(unvisited, key=lambda x: math.sqrt((current['lat']-x['lat'])**2 + (current['lng']-x['lng'])**2))
                    route.append(next_node)
                    unvisited.remove(next_node)
                route.append(end_node)
                st.session_state['optimized'] = pd.DataFrame(route)
            else:
                st.error("Nie znaleziono lokalizacji Startu/Mety.")

    res_df = st.session_state.get('optimized', df)
    cl, cr = st.columns([1, 2])
    with cl:
        st.subheader("📋 Plan")
        st.dataframe(res_df[['display_name']], use_container_width=True, height=600)
    with cr:
        st.subheader("🗺️ Mapa")
        m = folium.Map(location=[res_df['lat'].mean(), res_df['lng'].mean()], zoom_start=11)
        pts = []
        for i, row in res_df.iterrows():
            color = 'green' if i == 0 else ('red' if i == len(res_df)-1 and 'optimized' in st.session_state else 'blue')
            folium.Marker([row['lat'], row['lng']], tooltip=f"{i+1}. {row['display_name']}", icon=folium.Icon(color=color)).addTo(m)
            pts.append([row['lat'], row['lng']])
        if 'optimized' in st.session_state:
            folium.PolyLine(pts, color="royalblue", weight=4).addTo(m)
        st_folium(m, width="100%", height=600, key="v14")
else:
    st.info("👈 Wgraj plik i ustaw punkty startu/mety.")
