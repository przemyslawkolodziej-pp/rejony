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
    # Możesz tutaj dopisać swoje stałe punkty na start
    st.session_state['saved_locations'] = {
        "Dom": "Twoja Ulica 1, 00-000 Miasto",
        "Magazyn": "Przemysłowa 10, 00-000 Miasto"
    }
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
        name = re.search(r'<name>(.*?)</name>', pm)
        name = name.group(1) if name else "Punkt"
        coords = re.search(r'<coordinates>\s*([\d\.]+),\s*([\d\.]+)', pm)
        if coords:
            data.append({"address": name, "display_name": name, "lat": float(coords.group(2)), "lng": float(coords.group(1)), "ready": True})
        else:
            msc = re.search(r'<Data name=".*?MIEJSC.*?">\s*<value>(.*?)</value>', pm, re.IGNORECASE)
            ulica = re.search(r'<Data name=".*?ULICA.*?">\s*<value>(.*?)</value>', pm, re.IGNORECASE)
            nr = re.search(r'<Data name=".*?NR_DOM.*?">\s*<value>(.*?)</value>', pm, re.IGNORECASE)
            if msc:
                addr = f"{ulica.group(1) if ulica else ''} {nr.group(1) if nr else ''}, {msc.group(1)}, Polska"
                data.append({"address": addr, "display_name": f"{msc.group(1)} {ulica.group(1) if ulica else ''}", "lat": None, "lng": None, "ready": False})
    return pd.DataFrame(data)

def geocode_single(address, geolocator):
    try:
        time.sleep(1.1)
        location = geolocator.geocode(address, timeout=10)
        return (location.latitude, location.longitude) if location else (None, None)
    except: return None, None

# --- SIDEBAR: ZARZĄDZANIE PIGUŁKAMI ---
st.sidebar.header("📍 Twoje Pigułki (Bazy)")

# Dodawanie nowej pigułki
with st.sidebar.expander("➕ Dodaj nową pigułkę"):
    new_name = st.text_input("Nazwa (np. Biuro):")
    new_addr = st.text_input("Adres:")
    if st.button("Zapisz pigułkę"):
        if new_name and new_addr:
            st.session_state['saved_locations'][new_name] = new_addr
            st.rerun()

# Wyświetlanie pigułek
if st.session_state['saved_locations']:
    st.sidebar.write("Kliknij, aby ustawić:")
    for name, addr in st.session_state['saved_locations'].items():
        col1, col2 = st.sidebar.columns(2)
        if col1.button(f"S: {name}", use_container_width=True):
            st.session_state['start_addr'] = addr
        if col2.button(f"M: {name}", use_container_width=True):
            st.session_state['meta_addr'] = addr

st.sidebar.divider()

# --- SIDEBAR: PUNKTY TRASY ---
st.sidebar.header("🚀 Konfiguracja Trasy")
st.session_state['start_addr'] = st.sidebar.text_input("Punkt START:", value=st.session_state['start_addr'])
st.session_state['meta_addr'] = st.sidebar.text_input("Punkt META:", value=st.session_state['meta_addr'])

uploaded_file = st.sidebar.file_uploader("Wgraj KML/TXT", type=['kml', 'txt'])
if uploaded_file and st.sidebar.button("➕ Dodaj punkty z pliku"):
    new_df = parse_kml_smart(uploaded_file.read().decode('utf-8'))
    # Geokodowanie tylko brakujących
    geolocator = Nominatim(user_agent="route_optimizer_v12")
    for idx, row in new_df[new_df['lat'].isna()].iterrows():
        lat, lng = geocode_single(row['address'], geolocator)
        new_df.at[idx, 'lat'], new_df.at[idx, 'lng'] = lat, lng
    
    st.session_state['data'] = pd.concat([st.session_state['data'], new_df.dropna(subset=['lat'])], ignore_index=True).drop_duplicates(subset=['address'])
    st.sidebar.success(f"Baza: {len(st.session_state['data'])} pkt.")

if st.sidebar.button("🗑️ Wyczyść listę punktów"):
    st.session_state['data'] = pd.DataFrame(columns=['address', 'display_name', 'lat', 'lng', 'ready'])
    if 'optimized' in st.session_state: del st.session_state['optimized']
    st.rerun()

# --- PANEL GŁÓWNY ---
if not st.session_state['data'].empty:
    df = st.session_state['data']
    if st.button("🚀 OBLICZ OPTYMALNĄ TRASĘ", type="primary", use_container_width=True):
        if not st.session_state['start_addr'] or not st.session_state['meta_addr']:
            st.error("Ustaw Start i Metę (użyj pigułek lub wpisz adres).")
        else:
            geolocator = Nominatim(user_agent="route_optimizer_v12")
            s_lat, s_lng = geocode_single(st.session_state['start_addr'], geolocator)
            m_lat, m_lng = geocode_single(st.session_state['meta_addr'], geolocator)
            
            if s_lat and m_lat:
                start_node = {"display_name": "🏠 START", "lat": s_lat, "lng": s_lng}
                end_node = {"display_name": "🏁 META", "lat": m_lat, "lng": m_lng}
                
                # Algorytm najbliższego sąsiada
                unvisited = df.to_dict('records')
                route = [start_node]
                current = start_node
                while unvisited:
                    next_node = min(unvisited, key=lambda x: math.sqrt((current['lat']-x['lat'])**2 + (current['lng']-x['lng'])**2))
                    route.append(next_node)
                    unvisited.remove(next_node)
                route.append(end_node)
                st.session_state['optimized'] = pd.DataFrame(route)
            else:
                st.error("Nie udało się zlokalizować Twojego Startu/Mety.")

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
        st_folium(m, width="100%", height=600, key="v12")
else:
    st.info("👈 Dodaj punkty z pliku KML i ustaw Start/Metę pigułką.")
