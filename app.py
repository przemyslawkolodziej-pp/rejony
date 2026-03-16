import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
import re
import time
import math

import streamlit_authenticator as stauth
st.write("### TWÓJ HASH DO HASŁA 'moje_tajne_haslo':")
st.code(stauth.Hasher(['Rejony.PP.777']).generate()[0])

# --- KONFIGURACJA STRONY ---
st.set_page_config(page_title="Optymalizator Tras", layout="wide")

st.markdown("""
    <style>
    div[data-testid="column"] { display: flex; align-items: center; justify-content: center; }
    .stButton button { width: 100%; }
    </style>
    """, unsafe_allow_html=True)

st.title("🗺️ Optymalizator Tras")

# --- INICJALIZACJA PAMIĘCI ---
if 'saved_locations' not in st.session_state: st.session_state['saved_locations'] = {}
if 'projects' not in st.session_state: st.session_state['projects'] = {}
if 'data' not in st.session_state: st.session_state['data'] = pd.DataFrame(columns=['address', 'display_name', 'lat', 'lng'])
if 'start_addr' not in st.session_state: st.session_state['start_addr'] = ""
if 'meta_addr' not in st.session_state: st.session_state['meta_addr'] = ""

# --- FUNKCJE POMOCNICZE ---

def parse_kml_custom(file_content):
    placemarks = re.findall(r'<Placemark>(.*?)</Placemark>', file_content, re.DOTALL)
    data = []
    for pm in placemarks:
        name_match = re.search(r'<name>(.*?)</name>', pm)
        name = name_match.group(1) if name_match else "Punkt"
        lat_match = re.search(r'<Data name="Latitude">\s*<value>(.*?)</value>', pm, re.IGNORECASE)
        lng_match = re.search(r'<Data name="Longitude">\s*<value>(.*?)</value>', pm, re.IGNORECASE)
        lat, lng = None, None
        if lat_match and lng_match:
            try:
                lat = float(lat_match.group(1).replace(',', '.'))
                lng = float(lng_match.group(1).replace(',', '.'))
            except: pass
        if lat is None or lng is None:
            coords_match = re.search(r'<coordinates>\s*([\d\.\-]+),\s*([\d\.\-]+)', pm)
            if coords_match:
                lng = float(coords_match.group(1))
                lat = float(coords_match.group(2))
        if lat is not None and lng is not None:
            data.append({"address": name, "display_name": name, "lat": lat, "lng": lng})
    return pd.DataFrame(data)

def geocode_single(address, geolocator):
    try:
        time.sleep(1.1)
        location = geolocator.geocode(address, timeout=10)
        return (location.latitude, location.longitude) if location else (None, None)
    except: return (None, None)

# --- SIDEBAR: PROJEKTY ---
st.sidebar.header("📁 Twoje Projekty")

with st.sidebar.expander("💾 Zarządzaj projektami"):
    proj_name = st.text_input("Nazwa projektu (np. Rejon Północ):")
    if st.button("Zapisz aktualny projekt"):
        if proj_name:
            st.session_state['projects'][proj_name] = {
                'data': st.session_state['data'].copy(),
                'start': st.session_state['start_addr'],
                'meta': st.session_state['meta_addr']
            }
            st.success(f"Zapisano projekt: {proj_name}")
        else:
            st.warning("Podaj nazwę projektu!")

if st.session_state['projects']:
    selected_proj = st.sidebar.selectbox("Wybierz projekt:", list(st.session_state['projects'].keys()))
    col_load, col_del = st.sidebar.columns(2)
    if col_load.button("Wczytaj projekt"):
        proj = st.session_state['projects'][selected_proj]
        st.session_state['data'] = proj['data'].copy()
        st.session_state['start_addr'] = proj['start']
        st.session_state['meta_addr'] = proj['meta']
        if 'optimized' in st.session_state: del st.session_state['optimized']
        st.rerun()
    if col_del.button("Usuń projekt"):
        del st.session_state['projects'][selected_proj]
        st.rerun()

st.sidebar.divider()

# --- SIDEBAR: PUNKTY STAŁE ---
st.sidebar.header("📍 Twoje Punkty Stałe")
with st.sidebar.expander("➕ Dodaj nowy punkt"):
    new_name = st.text_input("Nazwa (np. WER Warszawa):")
    new_addr = st.text_input("Pełny adres punktu:")
    if st.button("Zapisz punkt"):
        if new_name and new_addr:
            st.session_state['saved_locations'][new_name] = new_addr
            st.rerun()

if st.session_state['saved_locations']:
    for name, addr in st.session_state['saved_locations'].items():
        c1, c2, c3 = st.sidebar.columns([1, 1, 0.6])
        if c1.button(f"S: {name}", key=f"s_{name}"): st.session_state['start_addr'] = addr
        if c2.button(f"M: {name}", key=f"m_{name}"): st.session_state['meta_addr'] = addr
        if c3.button("🗑️", key=f"del_{name}"):
            del st.session_state['saved_locations'][name]
            st.rerun()

st.sidebar.divider()

# --- SIDEBAR: REJON ---
st.sidebar.header("🚀 Rejon")
st.session_state['start_addr'] = st.sidebar.text_input("Adres STARTU:", value=st.session_state['start_addr'])
st.session_state['meta_addr'] = st.sidebar.text_input("Adres METY:", value=st.session_state['meta_addr'])

uploaded_file = st.sidebar.file_uploader("Wgraj plik KML/TXT", type=['kml', 'txt'])
if uploaded_file and st.sidebar.button("➕ Dodaj punkty z pliku"):
    new_df = parse_kml_custom(uploaded_file.read().decode('utf-8'))
    if not new_df.empty:
        st.session_state['data'] = pd.concat([st.session_state['data'], new_df], ignore_index=True).drop_duplicates(subset=['lat', 'lng'])
        st.sidebar.success(f"Dodano {len(new_df)} punktów.")
    else: st.sidebar.error("Brak koordynatów w pliku.")

if st.sidebar.button("🗑️ Wyczyść listę rejonu"):
    st.session_state['data'] = pd.DataFrame(columns=['address', 'display_name', 'lat', 'lng'])
    if 'optimized' in st.session_state: del st.session_state['optimized']
    st.rerun()

# --- PANEL GŁÓWNY ---
df = st.session_state['data']

if not df.empty:
    if st.button("🚀 OBLICZ OPTYMALNĄ TRASĘ", type="primary", use_container_width=True):
        if not st.session_state['start_addr'] or not st.session_state['meta_addr']:
            st.error("Ustaw adresy Startu i Mety!")
        else:
            geolocator = Nominatim(user_agent="optymalizator_tras_v19")
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
                st.rerun()
            else: st.error("Nie znaleziono lokalizacji Startu/Mety.")

    res_df = st.session_state.get('optimized', df)
    cl, cr = st.columns([1, 2])
    with cl:
        st.subheader("📋 Plan trasy")
        st.dataframe(res_df[['display_name']], use_container_width=True, height=600)
    with cr:
        st.subheader("🗺️ Mapa")
        try:
            map_df = res_df.copy()
            map_df['lat'] = pd.to_numeric(map_df['lat'], errors='coerce')
            map_df['lng'] = pd.to_numeric(map_df['lng'], errors='coerce')
            map_df = map_df.dropna(subset=['lat', 'lng'])
            if not map_df.empty:
                m = folium.Map(location=[map_df['lat'].mean(), map_df['lng'].mean()], zoom_start=11)
                pts = []
                for i, row in map_df.iterrows():
                    color = 'green' if i == 0 else ('red' if i == len(map_df)-1 and 'optimized' in st.session_state else 'blue')
                    folium.Marker(location=[row['lat'], row['lng']], tooltip=f"{i+1}. {row['display_name']}", icon=folium.Icon(color=color, icon='info-sign')).addTo(m)
                    pts.append([row['lat'], row['lng']])
                if 'optimized' in st.session_state and len(pts) > 1:
                    folium.PolyLine(pts, color="royalblue", weight=4, opacity=0.8).addTo(m)
                st_folium(m, width="100%", height=600, key="optymalizator_map")
        except Exception as e: st.error(f"Błąd mapy: {e}")
else:
    st.info("👈 Wgraj plik KML i ustaw punkty trasy lub wczytaj projekt.")
