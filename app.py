import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
import re
import time
import math
import json
import requests

# --- 1. SYSTEM LOGOWANIA ---
def logout():
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()

if 'authenticated' not in st.session_state:
    st.session_state['authenticated'] = False

if not st.session_state['authenticated']:
    # Tutaj też ustawiłem ikonkę mapy dla okna logowania
    st.set_page_config(page_title="Logowanie", page_icon="🗺️")
    st.title("🔐 Dostęp chroniony")
    with st.form("login_form"):
        pwd_input = st.text_input("Hasło:", type="password")
        if st.form_submit_button("Zaloguj"):
            if "password" in st.secrets and pwd_input == st.secrets["password"]:
                st.session_state['authenticated'] = True
                st.rerun()
            else:
                st.error("❌ Błędne hasło")
    st.stop()

# --- 2. FUNKCJE POMOCNICZE (ROUTING OSRM) ---
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
            route = res['routes'][0]
            return {'geometry': route['geometry']['coordinates'], 'distance': route['distance'], 'duration': route['duration']}
    except: return None

def parse_kml_robust(file_content):
    placemarks = re.findall(r'<Placemark>(.*?)</Placemark>', file_content, re.DOTALL)
    pts = []
    for pm in placemarks:
        name_match = re.search(r'<(?:name|display_name)>(.*?)</(?:name|display_name)>', pm)
        name = name_match.group(1) if name_match else "Punkt"
        coords = re.search(r'<coordinates>\s*([\d\.\-]+),\s*([\d\.\-]+)', pm)
        if coords:
            pts.append({"display_name": str(name), "lat": float(coords.group(2)), "lng": float(coords.group(1))})
    return pd.DataFrame(pts)

# --- 3. GŁÓWNA KONFIGURACJA UI ---
# Ustawienie ikonki mapy (🗺️) dla całej aplikacji
st.set_page_config(page_title="Optymalizator Drogowy", page_icon="🗺️", layout="wide")

if 'data' not in st.session_state: st.session_state['data'] = pd.DataFrame()
if 'saved_locations' not in st.session_state: st.session_state['saved_locations'] = {}
if 'start_name' not in st.session_state: st.session_state.update({'start_name': "Nie wybrano", 'meta_name': "Nie wybrano", 'start_addr': "", 'meta_addr': ""})

# --- SIDEBAR ---
with st.sidebar:
    st.header("🗺️ Menu")
    with st.expander("🚀 Konfiguracja Trasy", expanded=True):
        st.write(f"S: **{st.session_state['start_name']}** | M: **{st.session_state['meta_name']}**")
        up_kml = st.file_uploader("Wgraj KML", type=['kml'])
        if up_kml and st.button("Wczytaj punkty"):
            st.session_state['data'] = parse_kml_robust(up_kml.read().decode('utf-8'))
            if 'optimized' in st.session_state: del st.session_state['optimized']
            st.rerun()

    with st.expander("📍 Twoje Bazy"):
        with st.form("b_form"):
            n, a = st.text_input("Nazwa:"), st.text_input("Adres:")
            if st.form_submit_button("Dodaj"):
                st.session_state['saved_locations'][n] = a; st.rerun()
        for n, a in st.session_state['saved_locations'].items():
            c1, c2 = st.columns(2)
            if c1.button("S", key=f"s_{n}"): st.session_state.update({'start_addr': a, 'start_name': n}); st.rerun()
            if c2.button("M", key=f"m_{n}"): st.session_state.update({'meta_addr': a, 'meta_name': n}); st.rerun()

    if st.button("🔓 WYLOGUJ", use_container_width=True): logout()

# --- PANEL GŁÓWNY ---
st.title("🗺️ Optymalizator")

df = st.session_state['data']

if not df.empty:
    if st.button("🚀 OBLICZ TRASĘ PO DROGACH", type="primary", use_container_width=True):
        if st.session_state['start_addr'] and st.session_state['meta_addr']:
            with st.spinner("Liczenie trasy..."):
                gl = Nominatim(user_agent="v41")
                ls, lm = gl.geocode(st.session_state['start_addr']), gl.geocode(st.session_state['meta_addr'])
                if ls and lm:
                    curr = {"lat": ls.latitude, "lng": ls.longitude, "display_name": f"START: {st.session_state['start_name']}"}
                    route = [curr]
                    unvisited = df.to_dict('records')
                    while unvisited:
                        nxt = min(unvisited, key=lambda x: get_road_distance(curr['lat'], curr['lng'], x['lat'], x['lng'])[0])
                        route.append(nxt); curr = nxt; unvisited.remove(nxt)
                    route.append({"display_name": f"META: {st.session_state['meta_name']}", "lat": lm.latitude, "lng": lm.longitude})
                    st.session_state['optimized'] = pd.DataFrame(route)
                    
                    f_i = get_full_route_info([[r['lat'], r['lng']] for r in route])
                    if f_i: st.session_state.update({'geometry': f_i['geometry'], 'dist': f_i['distance'], 'time': f_i['duration']})
                    st.rerun()

    if 'dist' in st.session_state:
        m1, m2 = st.columns(2)
        m1.metric("Dystans", f"{st.session_state['dist']/1000:.2f} km")
        m2.metric("Czas jazdy", f"{int(st.session_state['time']//3600)}h {int((st.session_state['time']%3600)//60)}min")

    res_df = st.session_state.get('optimized', df)
    
    # 1. MAPA
    m = folium.Map(location=[res_df['lat'].mean(), res_df['lng'].mean()], zoom_start=11)
    for i, r in res_df.iterrows():
        col = 'green' if i==0 else ('red' if i==len(res_df)-1 and 'optimized' in st.session_state else 'blue')
        folium.Marker([r['lat'], r['lng']], tooltip=str(r['display_name']), icon=folium.Icon(color=col)).add_to(m)
    
    if 'geometry' in st.session_state:
        flip = [[c[1], c[0]] for c in st.session_state['geometry']]
        folium.PolyLine(flip, color="#4285f4", weight=6).add_to(m)
        m.fit_bounds(flip)
    
    st_folium(m, width="100%", height=500, key=f"map_{len(res_df)}")

    # 2. TABELA (Wizualna zmiana na Etykieta)
    st.markdown("### 📋 Kolejność przystanków")
    st.dataframe(
        res_df[['display_name']], 
        use_container_width=True,
        column_config={"display_name": "Etykieta"}
    )

else:
    st.info("Wgraj KML.")
