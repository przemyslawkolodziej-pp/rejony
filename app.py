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
import os

# --- 1. ZAPIS I LOGOWANIE ---
STORAGE_FILE = "data_storage.json"
def save_to_disk():
    data = {"saved_locations": st.session_state['saved_locations'], "projects": {k: {**v, "data": v["data"].to_dict()} for k, v in st.session_state['projects'].items()}}
    with open(STORAGE_FILE, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=4)

def load_from_disk():
    if os.path.exists(STORAGE_FILE):
        try:
            with open(STORAGE_FILE, "r", encoding="utf-8") as f:
                s = json.load(f); st.session_state['saved_locations'] = s.get("saved_locations", {})
                st.session_state['projects'] = {k: {**v, "data": pd.DataFrame(v["data"])} for k, v in s.get("projects", {}).items()}
        except: pass

if 'authenticated' not in st.session_state: st.session_state['authenticated'] = False
def check_password():
    if st.session_state['authenticated']: return True
    st.set_page_config(page_title="Optymalizator", page_icon="🗺️", layout="wide")
    st.title("🔐 Logowanie")
    with st.form("login"):
        p = st.text_input("Hasło:", type="password")
        if st.form_submit_button("Zaloguj"):
            if "password" in st.secrets and p == st.secrets["password"]:
                st.session_state['authenticated'] = True; load_from_disk(); st.rerun()
            else: st.error("❌ Błędne hasło")
    return False

# Inicjalizacja kluczy
for key in ['data', 'optimized_list', 'saved_locations', 'projects', 'start_coords', 'meta_coords', 'total_dist', 'total_time', 'geometries']:
    if key not in st.session_state: 
        st.session_state[key] = pd.DataFrame() if key == 'data' else ([] if key in ['optimized_list', 'geometries'] else ({} if key in ['saved_locations', 'projects'] else None))
if 'start_name' not in st.session_state: st.session_state.update({'start_name': "Nie wybrano", 'meta_name': "Nie wybrano"})

if not check_password(): st.stop()

# --- 2. LOGIKA POMOCNICZA ---
def get_lat_lng(address):
    try:
        gl = Nominatim(user_agent="v59_geo")
        loc = gl.geocode(address, timeout=10)
        return {"lat": loc.latitude, "lng": loc.longitude} if loc else None
    except: return None

def get_math_dist(lat1, lon1, lat2, lon2):
    return math.sqrt((lat1-lat2)**2 + (lon1-lon2)**2)

def get_route_chunked(coords):
    geom, dist, time = [], 0, 0
    for i in range(0, len(coords) - 1, 39):
        chunk = coords[i : i + 40]
        if len(chunk) < 2: break
        url = f"http://router.project-osrm.org/route/v1/driving/{';'.join([f'{c[1]},{c[0]}' for c in chunk])}?overview=full&geometries=geojson"
        try:
            r = requests.get(url, timeout=10).json()
            if r['code'] == 'Ok':
                geom.extend(r['routes'][0]['geometry']['coordinates'])
                dist += r['routes'][0]['distance']
                time += r['routes'][0]['duration']
        except: pass
    return geom, dist, time

def parse_kml(content, name):
    placemarks = re.findall(r'<Placemark>(.*?)</Placemark>', content, re.DOTALL)
    pts = []
    for pm in placemarks:
        n = re.search(r'<(?:name|display_name)>(.*?)</', pm)
        c = re.search(r'<coordinates>\s*([\d\.\-]+),\s*([\d\.\-]+)', pm)
        if c: pts.append({"display_name": n.group(1) if n else "Punkt", "lat": float(c.group(2)), "lng": float(c.group(1)), "source_file": name})
    return pd.DataFrame(pts)

def get_color(idx):
    colors = ['#4285f4', '#ea4335', '#fbbc05', '#34a853', '#ff6d00', '#4615b2', '#00bcd4']
    return colors[idx % len(colors)]

st.markdown("<style>div.stButton > button { height: 45px; width: 100%; font-size: 18px !important; } .selection-info { background-color: #f0f4f8; padding: 10px; border-radius: 5px; border-left: 5px solid #4285f4; margin-bottom: 10px; font-size: 13px; }</style>", unsafe_allow_html=True)

# --- 3. SIDEBAR ---
with st.sidebar:
    st.header("🗺️ Menu")
    
    with st.expander("🚀 Pliki KML", expanded=True):
        st.markdown(f'<div class="selection-info">🏠 Start: {st.session_state["start_name"]}<br>🏁 Meta: {st.session_state["meta_name"]}</div>', unsafe_allow_html=True)
        up = st.file_uploader("Wgraj KML", type=['kml'], accept_multiple_files=True)
        if up and st.button("Wczytaj pliki"):
            all_pts = [parse_kml(f.read().decode('utf-8'), f.name) for f in up]
            if all_pts: st.session_state['data'] = pd.concat(all_pts, ignore_index=True); st.rerun()
        
        # --- NOWOŚĆ: FILTROWANIE PLIKÓW ---
        if not st.session_state['data'].empty:
            st.divider()
            st.markdown("**Widoczność rejonów:**")
            unique_files = st.session_state['data']['source_file'].unique().tolist()
            visible_files = st.multiselect("Pokaż na mapie:", unique_files, default=unique_files)
            # Tworzymy przefiltrowany dataframe tylko do obliczeń/wyświetlania
            filtered_df = st.session_state['data'][st.session_state['data']['source_file'].isin(visible_files)]
        else:
            filtered_df = pd.DataFrame()

    with st.expander("📍 Bazy", expanded=True):
        if st.session_state['saved_locations']:
            sel_b = st.selectbox("Wybierz bazę:", ["---"] + list(st.session_state['saved_locations'].keys()))
            if sel_b != "---":
                addr = st.session_state['saved_locations'][sel_b]
                c1, c2, c3 = st.columns(3)
                if c1.button("🏠", type="primary" if st.session_state['start_name']==sel_b else "secondary"):
                    st.session_state.update({'start_name': sel_b, 'start_coords': get_lat_lng(addr)}); st.rerun()
                if c2.button("🏁", type="primary" if st.session_state['meta_name']==sel_b else "secondary"):
                    st.session_state.update({'meta_name': sel_b, 'meta_coords': get_lat_lng(addr)}); st.rerun()
                if c3.button("🗑️"): del st.session_state['saved_locations'][sel_b]; save_to_disk(); st.rerun()
        with st.form("new_b", clear_on_submit=True):
            n, a = st.text_input("Nazwa:"), st.text_input("Adres:")
            if st.form_submit_button("Dodaj"): st.session_state['saved_locations'][n] = a; save_to_disk(); st.rerun()

    st.button("🔓 WYLOGUJ", on_click=lambda: st.session_state.update({'authenticated': False}))

# --- 4. PANEL GŁÓWNY ---
st.title("🗺️ Optymalizator")
sc, mc = st.session_state['start_coords'], st.session_state['meta_coords']

if not filtered_df.empty or sc:
    mode = st.radio("Tryb pracy:", ["Jedna trasa (wszystkie widoczne)", "Oddzielne trasy dla każdego widocznego pliku"], horizontal=True)
    
    col1, col2 = st.columns([3, 1])
    with col1:
        if st.button("🚀 OBLICZ TRASY", type="primary", use_container_width=True):
            if not (sc and mc): st.error("Wybierz Start i Metę!")
            else:
                with st.spinner("Przeliczanie..."):
                    st.session_state['optimized_list'] = []
                    st.session_state['geometries'] = []
                    st.session_state['total_dist'], st.session_state['total_time'] = 0, 0
                    
                    groups = [filtered_df] if mode == "Jedna trasa (wszystkie widoczne)" else [filtered_df[filtered_df['source_file'] == f] for f in filtered_df['source_file'].unique()]
                    
                    for i, group in enumerate(groups):
                        if group.empty: continue
                        curr = {"lat": sc['lat'], "lng": sc['lng'], "display_name": "START", "source_file": "Baza"}
                        route, unv = [curr], group.to_dict('records')
                        while unv:
                            nxt = min(unv, key=lambda x: get_math_dist(curr['lat'], curr['lng'], x['lat'], x['lng']))
                            route.append(nxt); curr = nxt; unv.remove(nxt)
                        route.append({"lat": mc['lat'], "lng": mc['lng'], "display_name": "META", "source_file": "Baza"})
                        
                        geom, d, t = get_route_chunked([[r['lat'], r['lng']] for r in route])
                        st.session_state['optimized_list'].append(pd.DataFrame(route))
                        st.session_state['geometries'].append({"geom": geom, "color": get_color(i), "name": group['source_file'].iloc[0] if mode != "Jedna trasa (wszystkie widoczne)" else "Trasa Zbiorcza"})
                        st.session_state['total_dist'] += d
                        st.session_state['total_time'] += t
                    st.rerun()

    with col2:
        if st.button("🔄 RESET", use_container_width=True):
            for k in ['data', 'optimized_list', 'geometries', 'total_dist', 'total_time', 'start_coords', 'meta_coords']:
                st.session_state[k] = pd.DataFrame() if k == 'data' else ([] if k in ['optimized_list', 'geometries'] else None)
            st.session_state.update({'start_name': "Nie wybrano", 'meta_name': "Nie wybrano"}); st.rerun()

    if st.session_state['total_dist']:
        m1, m2, m3 = st.columns(3)
        m1.metric("Widoczny Dystans", f"{st.session_state['total_dist']/1000:.2f} km")
        m2.metric("Widoczny Czas", f"{int(st.session_state['total_time']//3600)}h {int((st.session_state['total_time']%3600)//60)}min")
        m3.metric("Aktywne Trasy", len(st.session_state['optimized_list']))

    # Mapa
    m = folium.Map(location=[52.2, 19.2], zoom_start=6)
    if sc: folium.Marker([sc['lat'], sc['lng']], icon=folium.Icon(color='green', icon='home')).add_to(m)
    if mc: folium.Marker([mc['lat'], mc['lng']], icon=folium.Icon(color='red', icon='flag')).add_to(m)
    
    for g_data in st.session_state['geometries']:
        folium.PolyLine([[c[1], c[0]] for c in g_data['geom']], color=g_data['color'], weight=5, opacity=0.8, tooltip=g_data['name']).add_to(m)
    
    # Wyświetlamy markery tylko dla widocznych plików
    for opt_df in st.session_state['optimized_list']:
        for _, r in opt_df.iterrows():
            if r['source_file'] != "Baza":
                folium.CircleMarker([r['lat'], r['lng']], radius=5, color='black', fill=True, tooltip=f"{r['display_name']} ({r['source_file']})").add_to(m)
    
    st_folium(m, width="100%", height=550, key="map_v59")
else:
    st.info("👈 Wgraj pliki i upewnij się, że są zaznaczone jako widoczne.")
