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
    st.set_page_config(page_title="Logowanie", page_icon="🔐")
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

# --- 2. FUNKCJE ROUTINGU (OSRM) ---
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

# --- 3. PARSOWANIE KML ---
def parse_kml_robust(file_content):
    placemarks = re.findall(r'<Placemark>(.*?)</Placemark>', file_content, re.DOTALL)
    pts = []
    for pm in placemarks:
        # Próbujemy wyciągnąć nazwę z tagu <name> lub <display_name>
        name_match = re.search(r'<(?:name|display_name)>(.*?)</(?:name|display_name)>', pm)
        name = name_match.group(1) if name_match else "Punkt"
        coords = re.search(r'<coordinates>\s*([\d\.\-]+),\s*([\d\.\-]+)', pm)
        if coords:
            # Tworzymy słownik z kluczem "Etykieta"
            pts.append({"Etykieta": str(name), "lat": float(coords.group(2)), "lng": float(coords.group(1))})
    return pd.DataFrame(pts)

# --- 4. KONFIGURACJA UI ---
st.set_page_config(page_title="Optymalizator Drogowy", layout="wide")

# CSS dla lepszego wyglądu
st.markdown("""
    <style>
    .selection-info { font-size: 13px; color: #1e1e1e; background-color: #e8f0fe; padding: 12px; border-radius: 8px; border-left: 6px solid #4285f4; margin-bottom: 15px; }
    .stMetric { background-color: #f8f9fa; padding: 15px; border-radius: 10px; border: 1px solid #ddd; }
    </style>
    """, unsafe_allow_html=True)

# Inicjalizacja stanów
for key in ['data', 'saved_locations', 'projects']:
    if key not in st.session_state: st.session_state[key] = pd.DataFrame() if key == 'data' else {}
if 'start_name' not in st.session_state: st.session_state.update({'start_name': "Nie wybrano", 'meta_name': "Nie wybrano", 'start_addr': "", 'meta_addr': ""})

# --- SIDEBAR ---
with st.sidebar:
    with st.expander("🚀 Konfiguracja Trasy", expanded=True):
        st.markdown(f'<div class="selection-info">📍 S: {st.session_state["start_name"]}<br>🏁 M: {st.session_state["meta_name"]}</div>', unsafe_allow_html=True)
        up_kml = st.file_uploader("Wgraj KML", type=['kml'])
        if up_kml and st.button("Wczytaj KML"):
            st.session_state['data'] = parse_kml_robust(up_kml.read().decode('utf-8'))
            if 'optimized' in st.session_state: del st.session_state['optimized']
            st.rerun()

    with st.expander("📍 Twoje Bazy"):
        with st.form("add_b"):
            n, a = st.text_input("Nazwa:"), st.text_input("Adres:")
            if st.form_submit_button("Dodaj") and n and a:
                st.session_state['saved_locations'][n] = a; st.rerun()
        for n, a in st.session_state['saved_locations'].items():
            is_s, is_m = (st.session_state['start_name'] == n), (st.session_state['meta_name'] == n)
            st.write(f"**{n}**")
            c1, c2, c3 = st.columns([1, 1, 0.4])
            with c1:
                if is_s: st.write("🟢 START")
                else:
                    if st.button("S", key=f"s_{n}"): st.session_state.update({'start_addr': a, 'start_name': n}); st.rerun()
            with c2:
                if is_m: st.write("🔴 META")
                else:
                    if st.button("M", key=f"m_{n}"): st.session_state.update({'meta_addr': a, 'meta_name': n}); st.rerun()
            with c3:
                if st.button("🗑️", key=f"d_{n}"): del st.session_state['saved_locations'][n]; st.rerun()

    if st.button("🔓 WYLOGUJ"): logout()

# --- PANEL GŁÓWNY ---
st.title("🗺️ Optymalizator Drogowy")

df = st.session_state['data']

# Zabezpieczenie nazw kolumn (KeyError fix)
if not df.empty:
    if 'display_name' in df.columns:
        df = df.rename(columns={'display_name': 'Etykieta'})
        st.session_state['data'] = df

if not df.empty:
    if st.button("🚀 OBLICZ TRASĘ PO DROGACH", type="primary", use_container_width=True):
        if not st.session_state['start_addr'] or not st.session_state['meta_addr']:
            st.error("Wybierz bazę startową i końcową w panelu bocznym!")
        else:
            with st.spinner("Przetwarzanie..."):
                gl = Nominatim(user_agent="v38")
                ls, lm = gl.geocode(st.session_state['start_addr']), gl.geocode(st.session_state['meta_addr'])
                if ls and lm:
                    curr = {"lat": ls.latitude, "lng": ls.longitude, "Etykieta": f"START: {st.session_state['start_name']}"}
                    route = [curr]
                    unvisited = df.to_dict('records')
                    while unvisited:
                        nxt = min(unvisited, key=lambda x: get_road_distance(curr['lat'], curr['lng'], x['lat'], x['lng'])[0])
                        route.append(nxt); curr = nxt; unvisited.remove(nxt)
                    route.append({"Etykieta": f"META: {st.session_state['meta_name']}", "lat": lm.latitude, "lng": lm.longitude})
                    st.session_state['optimized'] = pd.DataFrame(route)
                    
                    full_info = get_full_route_info([[r['lat'], r['lng']] for r in route])
                    if full_info:
                        st.session_state['geometry'], st.session_state['total_dist'], st.session_state['total_time'] = full_info['geometry'], full_info['distance'], full_info['duration']
                    st.rerun()

    # Statystyki
    if 'total_dist' in st.session_state:
        m1, m2, m3 = st.columns(3)
        km, tm = st.session_state['total_dist'] / 1000, st.session_state['total_time'] / 60
        m1.metric("Łączny dystans", f"{km:.2f} km")
        m2.metric("Czas przejazdu", f"{int(tm // 60)}h {int(tm % 60)}min")
        m3.metric("Liczba punktów", f"{len(st.session_state['optimized'])}")

    res_df = st.session_state.get('optimized', df)
    
    # 1. MAPA
    m = folium.Map(location=[res_df['lat'].mean(), res_df['lng'].mean()], zoom_start=11)
    for i, r in res_df.iterrows():
        col = 'green' if i==0 else ('red' if i==len(res_df)-1 and 'optimized' in st.session_state else 'blue')
        label = r['Etykieta'] if 'Etykieta' in r else "Punkt"
        folium.Marker([r['lat'], r['lng']], tooltip=str(label), icon=folium.Icon(color=col)).add_to(m)
    
    if 'geometry' in st.session_state and st.session_state['geometry']:
        flipped_geom = [[c[1], c[0]] for c in st.session_state['geometry']]
        folium.PolyLine(flipped_geom, color="#4285f4", weight=6, opacity=0.8).add_to(m)
        m.fit_bounds(flipped_geom)
    
    st_folium(m, width="100%", height=500, key=f"map_{len(res_df)}")

    # 2. TABELA POD MAPĄ
    st.markdown("### 📋 Kolejność przystanków")
    # Wyświetlamy tylko kolumnę Etykieta
    st.dataframe(res_df[['Etykieta']], use_container_width=True)

else:
    st.info("👈 Wgraj plik KML i wybierz bazy.")
