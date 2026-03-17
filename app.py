import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
import re
import math
import json
import requests
import hashlib

# --- 1. SYSTEM LOGOWANIA (Zapamiętywanie w ramach sesji przeglądarki) ---
if 'authenticated' not in st.session_state:
    st.session_state['authenticated'] = False

def check_password():
    if st.session_state['authenticated']:
        return True
    
    st.set_page_config(page_title="Logowanie", page_icon="🗺️")
    st.title("🔐 Dostęp chroniony")
    with st.form("login_form"):
        pwd_input = st.text_input("Hasło:", type="password")
        if st.form_submit_button("Zaloguj"):
            if "password" in st.secrets and pwd_input == st.secrets["password"]:
                st.session_state['authenticated'] = True
                return True
            else:
                st.error("❌ Błędne hasło")
    return False

if not check_password():
    st.stop()

# --- 2. FUNKCJE POMOCNICZE ---
@st.cache_data(show_spinner=False)
def get_lat_lng(address):
    if not address: return None
    try:
        gl = Nominatim(user_agent="v46_geocoder")
        loc = gl.geocode(address, timeout=10)
        if loc: return {"lat": loc.latitude, "lng": loc.longitude}
    except: pass
    return None

def get_road_distance(lat1, lon1, lat2, lon2):
    try:
        url = f"http://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=false"
        r = requests.get(url, timeout=5)
        res = r.json()
        if res['code'] == 'Ok':
            return res['routes'][0]['distance'], res['routes'][0]['duration']
    except: pass
    return math.sqrt((lat1-lat2)**2 + (lon1-lon2)**2) * 111000, 0

def get_full_route_info(coords_list):
    coords_str = ";".join([f"{c[1]},{c[0]}" for c in coords_list])
    url = f"http://router.project-osrm.org/route/v1/driving/{coords_str}?overview=full&geometries=geojson"
    try:
        r = requests.get(url, timeout=10)
        res = r.json()
        if res['code'] == 'Ok':
            return {'geometry': res['routes'][0]['geometry']['coordinates'], 
                    'distance': res['routes'][0]['distance'], 
                    'duration': res['routes'][0]['duration']}
    except: return None

def parse_kml_robust(file_content, file_name="unknown"):
    placemarks = re.findall(r'<Placemark>(.*?)</Placemark>', file_content, re.DOTALL)
    pts = []
    for pm in placemarks:
        name_match = re.search(r'<(?:name|display_name)>(.*?)</(?:name|display_name)>', pm)
        name = name_match.group(1) if name_match else "Punkt"
        coords = re.search(r'<coordinates>\s*([\d\.\-]+),\s*([\d\.\-]+)', pm)
        if coords:
            pts.append({"display_name": str(name), "lat": float(coords.group(2)), "lng": float(coords.group(1)), "source_file": file_name})
    return pd.DataFrame(pts)

def get_color_for_file(file_name):
    folium_colors = ['blue', 'purple', 'orange', 'cadetblue', 'pink', 'lightblue', 'lightgreen', 'gray']
    hash_idx = int(hashlib.md5(file_name.encode()).hexdigest(), 16) % len(folium_colors)
    return folium_colors[hash_idx]

# --- 3. KONFIGURACJA UI ---
st.set_page_config(page_title="Optymalizator Drogowy", page_icon="🗺️", layout="wide")

# Stan sesji
for key in ['data', 'saved_locations', 'projects', 'start_coords', 'meta_coords']:
    if key not in st.session_state: 
        st.session_state[key] = pd.DataFrame() if 'data' in key else (None if 'coords' in key else {})

if 'start_name' not in st.session_state: 
    st.session_state.update({'start_name': "Nie wybrano", 'meta_name': "Nie wybrano", 'start_addr': "", 'meta_addr': ""})

# --- SIDEBAR ---
with st.sidebar:
    st.header("🗺️ Menu Główne")
    
    with st.expander("🚀 Dane KML", expanded=True):
        up_kmls = st.file_uploader("Wgraj KML", type=['kml'], accept_multiple_files=True)
        if up_kmls and st.button("Wczytaj pliki"):
            all_pts = [parse_kml_robust(f.read().decode('utf-8'), f.name) for f in up_kmls]
            if all_pts:
                st.session_state['data'] = pd.concat(all_pts, ignore_index=True)
                st.rerun()

    with st.expander("📍 Twoje Bazy", expanded=True):
        with st.form("b_form", clear_on_submit=True):
            n, a = st.text_input("Nazwa:"), st.text_input("Adres:")
            if st.form_submit_button("Dodaj bazę") and n and a:
                st.session_state['saved_locations'][n] = a; st.rerun()
        
        st.divider()
        for n, a in st.session_state['saved_locations'].items():
            st.markdown(f"**{n}**")
            c1, c2, c3 = st.columns([1.2, 1.2, 0.5])
            with c1:
                if st.button("Ustaw Start", key=f"s_{n}", use_container_width=True):
                    st.session_state.update({'start_addr': a, 'start_name': n})
                    st.session_state['start_coords'] = get_lat_lng(a)
                    st.rerun()
            with c2:
                if st.button("Ustaw Metę", key=f"m_{n}", use_container_width=True):
                    st.session_state.update({'meta_addr': a, 'meta_name': n})
                    st.session_state['meta_coords'] = get_lat_lng(a)
                    st.rerun()
            with c3:
                # Wyśrodkowany kosz
                st.markdown("<div style='text-align: center;'>", unsafe_allow_html=True)
                if st.button("🗑️", key=f"d_{n}"):
                    del st.session_state['saved_locations'][n]; st.rerun()
                st.markdown("</div>", unsafe_allow_html=True)
            st.divider()

    if st.button("🔓 WYLOGUJ", use_container_width=True):
        for key in list(st.session_state.keys()): del st.session_state[key]
        st.rerun()

# --- PANEL GŁÓWNY ---
st.title("🗺️ Optymalizator")

df = st.session_state['data']
sc = st.session_state['start_coords']
mc = st.session_state['meta_coords']

# Logika unikania nakładania się ikonek (Offset)
display_mc = mc.copy() if mc else None
if sc and mc and sc['lat'] == mc['lat'] and sc['lng'] == mc['lng']:
    display_mc['lat'] += 0.00015 # Minimalne przesunięcie mety w górę
    display_mc['lng'] += 0.00015 # Minimalne przesunięcie mety w bok

if not df.empty or sc or mc:
    if st.button("🚀 OBLICZ TRASĘ (OSRM)", type="primary", use_container_width=True):
        if sc and mc:
            with st.spinner("Szukanie trasy..."):
                curr = {"lat": sc['lat'], "lng": sc['lng'], "display_name": f"START: {st.session_state['start_name']}", "source_file": "START"}
                route = [curr]
                unvisited = df.to_dict('records')
                while unvisited:
                    nxt = min(unvisited, key=lambda x: get_road_distance(curr['lat'], curr['lng'], x['lat'], x['lng'])[0])
                    route.append(nxt); curr = nxt; unvisited.remove(nxt)
                route.append({"lat": mc['lat'], "lng": mc['lng'], "display_name": f"META: {st.session_state['meta_name']}", "source_file": "META"})
                st.session_state['optimized'] = pd.DataFrame(route)
                f_i = get_full_route_info([[r['lat'], r['lng']] for r in route])
                if f_i: st.session_state.update({'geometry': f_i['geometry'], 'dist': f_i['distance'], 'time': f_i['duration']})
                st.rerun()

    # Statystyki
    if 'dist' in st.session_state:
        m1, m2 = st.columns(2)
        m1.metric("Dystans", f"{st.session_state['dist']/1000:.2f} km")
        m2.metric("Czas", f"{int(st.session_state['time']//3600)}h {int((st.session_state['time']%3600)//60)}min")

    # MAPA
    view_df = st.session_state.get('optimized', df)
    m = folium.Map(location=[52.2, 19.2], zoom_start=6)
    
    if sc:
        folium.Marker([sc['lat'], sc['lng']], tooltip="START", icon=folium.Icon(color='green', icon='play')).add_to(m)
    if display_mc:
        folium.Marker([display_mc['lat'], display_mc['lng']], tooltip="META", icon=folium.Icon(color='red', icon='stop')).add_to(m)

    for i, r in view_df.iterrows():
        if r['source_file'] not in ["START", "META"]:
            folium.Marker([r['lat'], r['lng']], tooltip=r['display_name'], 
                          icon=folium.Icon(color=get_color_for_file(r['source_file']))).add_to(m)
    
    if 'geometry' in st.session_state:
        folium.PolyLine([[c[1], c[0]] for c in st.session_state['geometry']], color="#4285f4", weight=5).add_to(m)
        m.fit_bounds([[sc['lat'], sc['lng']], [mc['lat'], mc['lng']]])

    st_folium(m, width="100%", height=550, key=f"map_{len(view_df)}")

    # TABELA
    st.markdown("### 📋 Lista przystanków")
    st.dataframe(view_df[['display_name', 'source_file']], use_container_width=True, 
                 column_config={"display_name": "Etykieta", "source_file": "Źródło"})

else:
    st.info("Wgraj KML i ustaw Start/Metę.")
