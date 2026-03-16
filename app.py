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

# --- 3. KONFIGURACJA UI ---
st.set_page_config(page_title="Optymalizator Drogowy", page_icon="🗺️", layout="wide")

# CSS dla czytelności baz i statusów
st.markdown("""
    <style>
    .selection-info { font-size: 13px; color: #1e1e1e; background-color: #e8f0fe; padding: 12px; border-radius: 8px; border-left: 6px solid #4285f4; margin-bottom: 15px; }
    .status-text { font-size: 11px; font-weight: bold; text-align: center; margin-top: 5px; color: #2e7d32; }
    .stMetric { background-color: #f8f9fa; padding: 10px; border-radius: 10px; border: 1px solid #eee; }
    </style>
    """, unsafe_allow_html=True)

# Inicjalizacja stanów
for key in ['data', 'saved_locations', 'projects']:
    if key not in st.session_state: 
        st.session_state[key] = pd.DataFrame() if key == 'data' else {}
if 'start_name' not in st.session_state: 
    st.session_state.update({'start_name': "Nie wybrano", 'meta_name': "Nie wybrano", 'start_addr': "", 'meta_addr': ""})

# --- SIDEBAR ---
with st.sidebar:
    st.header("🗺️ Menu Główne")
    
    # 1. KONFIGURACJA I KML
    with st.expander("🚀 Konfiguracja Trasy", expanded=True):
        st.markdown(f'<div class="selection-info">📍 S: {st.session_state["start_name"]}<br>🏁 M: {st.session_state["meta_name"]}</div>', unsafe_allow_html=True)
        up_kml = st.file_uploader("Wgraj KML", type=['kml'])
        if up_kml and st.button("Wczytaj punkty z KML"):
            st.session_state['data'] = parse_kml_robust(up_kml.read().decode('utf-8'))
            if 'optimized' in st.session_state: del st.session_state['optimized']
            st.rerun()
        if st.button("🗑️ Wyczyść aktualne dane"):
            st.session_state['data'] = pd.DataFrame()
            st.session_state.update({'start_name': "Nie wybrano", 'meta_name': "Nie wybrano", 'start_addr': "", 'meta_addr': ""})
            if 'optimized' in st.session_state: del st.session_state['optimized']
            st.rerun()

    # 2. TWOJE BAZY
    with st.expander("📍 Twoje Bazy", expanded=False):
        with st.form("add_base_form", clear_on_submit=True):
            n_n, n_a = st.text_input("Nazwa bazy:"), st.text_input("Adres bazy:")
            if st.form_submit_button("Dodaj bazę") and n_n and n_a:
                st.session_state['saved_locations'][n_n] = n_a
                st.rerun()
        st.divider()
        for n, a in st.session_state['saved_locations'].items():
            is_s, is_m = (st.session_state['start_name'] == n), (st.session_state['meta_name'] == n)
            st.write(f"**{n}**")
            c1, c2, c3 = st.columns([1, 1, 0.4])
            with c1:
                if is_s: st.markdown('<p class="status-text">🟢 START</p>', unsafe_allow_html=True)
                else:
                    if st.button("S", key=f"s_{n}"):
                        st.session_state.update({'start_addr': a, 'start_name': n}); st.rerun()
            with c2:
                if is_m: st.markdown('<p class="status-text">🔴 META</p>', unsafe_allow_html=True)
                else:
                    if st.button("M", key=f"m_{n}"):
                        st.session_state.update({'meta_addr': a, 'meta_name': n}); st.rerun()
            with c3:
                if st.button("🗑️", key=f"d_{n}"): del st.session_state['saved_locations'][n]; st.rerun()
            st.divider()

    # 3. PROJEKTY
    with st.expander("📁 Projekty", expanded=False):
        p_name = st.text_input("Nazwa projektu do zapisu:")
        if st.button("Zapisz bieżący stan"):
            if p_name:
                st.session_state['projects'][p_name] = {
                    'data': st.session_state['data'].copy(),
                    'start_addr': st.session_state['start_addr'], 'meta_addr': st.session_state['meta_addr'],
                    'start_name': st.session_state['start_name'], 'meta_name': st.session_state['meta_name']
                }
                st.toast(f"Projekt {p_name} zapisany!")
        
        if st.session_state['projects']:
            sel_p = st.selectbox("Wczytaj projekt:", list(st.session_state['projects'].keys()))
            cp1, cp2 = st.columns(2)
            if cp1.button("Wczytaj"):
                p = st.session_state['projects'][sel_p]
                st.session_state.update({'data': p['data'].copy(), 'start_addr': p['start_addr'], 'meta_addr': p['meta_addr'], 'start_name': p['start_name'], 'meta_name': p['meta_name']})
                if 'optimized' in st.session_state: del st.session_state['optimized']
                st.rerun()
            if cp2.button("Usuń"):
                del st.session_state['projects'][sel_p]; st.rerun()

    # 4. KOPIA ZAPASOWA JSON
    with st.expander("💾 Kopia zapasowa", expanded=False):
        export_data = {
            "saved_locations": st.session_state['saved_locations'],
            "projects": {k: {**v, "data": v["data"].to_dict()} for k, v in st.session_state['projects'].items()}
        }
        st.download_button("📥 Pobierz Backup (JSON)", data=json.dumps(export_data), file_name="backup_tras.json")
        up_json = st.file_uploader("📤 Wczytaj Backup", type="json")
        if up_json:
            try:
                b = json.load(up_json)
                st.session_state['saved_locations'] = b["saved_locations"]
                for k, v in b["projects"].items():
                    st.session_state['projects'][k] = {**v, "data": pd.DataFrame(v["data"])}
                st.success("Wczytano backup!")
            except: st.error("Błąd pliku JSON.")

    st.markdown('<br>', unsafe_allow_html=True)
    if st.button("🔓 WYLOGUJ", use_container_width=True): logout()

# --- PANEL GŁÓWNY ---
st.title("🗺️ Optymalizator Drogowy")

df = st.session_state['data']

if not df.empty:
    if st.button("🚀 OBLICZ OPTYMALNĄ TRASĘ (OSRM)", type="primary", use_container_width=True):
        if not st.session_state['start_addr'] or not st.session_state['meta_addr']:
            st.error("⚠️ Wybierz Start i Metę w panelu bocznym!")
        else:
            with st.spinner("Szukanie najkrótszej drogi..."):
                gl = Nominatim(user_agent="v42_final")
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
        m1, m2, m3 = st.columns(3)
        m1.metric("Łączny dystans", f"{st.session_state['dist']/1000:.2f} km")
        m2.metric("Czas jazdy", f"{int(st.session_state['time']//3600)}h {int((st.session_state['time']%3600)//60)}min")
        m3.metric("Liczba punktów", len(st.session_state.get('optimized', [])))

    res_df = st.session_state.get('optimized', df)
    
    # MAPA
    m = folium.Map(location=[res_df['lat'].mean(), res_df['lng'].mean()], zoom_start=11)
    for i, r in res_df.iterrows():
        col = 'green' if i==0 else ('red' if i==len(res_df)-1 and 'optimized' in st.session_state else 'blue')
        folium.Marker([r['lat'], r['lng']], tooltip=str(r['display_name']), icon=folium.Icon(color=col)).add_to(m)
    
    if 'geometry' in st.session_state:
        flip = [[c[1], c[0]] for c in st.session_state['geometry']]
        folium.PolyLine(flip, color="#4285f4", weight=6, opacity=0.8).add_to(m)
        m.fit_bounds(flip)
    
    st_folium(m, width="100%", height=500, key=f"map_{len(res_df)}")

    # TABELA (Szeroka, nagłówek "Etykieta")
    st.markdown("### 📋 Kolejność przystanków")
    st.dataframe(
        res_df[['display_name']], 
        use_container_width=True,
        column_config={"display_name": "Etykieta"}
    )
else:
    st.info("👈 Zacznij od wgrania pliku KML i wybrania baz Startu/Mety w panelu bocznym.")
