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

# --- 1. FUNKCJE ZAPISU (BEZ ZMIAN) ---
STORAGE_FILE = "data_storage.json"

def save_to_disk():
    data = {"saved_locations": st.session_state['saved_locations'], 
            "projects": {k: {**v, "data": v["data"].to_dict()} for k, v in st.session_state['projects'].items()}}
    with open(STORAGE_FILE, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=4)

def load_from_disk():
    if os.path.exists(STORAGE_FILE):
        try:
            with open(STORAGE_FILE, "r", encoding="utf-8") as f:
                s = json.load(f)
                st.session_state['saved_locations'] = s.get("saved_locations", {})
                st.session_state['projects'] = {k: {**v, "data": pd.DataFrame(v["data"])} for k, v in s.get("projects", {}).items()}
        except: pass

# --- 2. LOGOWANIE ---
if 'authenticated' not in st.session_state: st.session_state['authenticated'] = False

def check_password():
    if st.session_state['authenticated']: return True
    st.set_page_config(page_title="Logowanie", page_icon="🗺️")
    st.title("🔐 Logowanie")
    with st.form("login"):
        p = st.text_input("Hasło:", type="password")
        if st.form_submit_button("Zaloguj"):
            if "password" in st.secrets and p == st.secrets["password"]:
                st.session_state['authenticated'] = True
                load_from_disk(); st.rerun()
            else: st.error("Błędne hasło")
    return False

for k in ['data', 'saved_locations', 'projects', 'start_coords', 'meta_coords']:
    if k not in st.session_state: st.session_state[k] = pd.DataFrame() if 'data' in k else (None if 'coords' in k else {})
if 'start_name' not in st.session_state: st.session_state.update({'start_name': "Nie wybrano", 'meta_name': "Nie wybrano"})

if not check_password(): st.stop()

# --- 3. ROZBUDOWANY ROUTING (OBSŁUGA SETEK PUNKTÓW) ---
def get_road_distance(lat1, lon1, lat2, lon2):
    # Prosty dystans euklidesowy do szybkiego sortowania (nie obciąża serwera)
    return math.sqrt((lat1-lat2)**2 + (lon1-lon2)**2)

def get_chunked_route_info(full_coords):
    """Dzieli trasę na kawałki po 40 punktów, aby ominąć limity serwera OSRM."""
    combined_geometry = []
    total_dist = 0
    total_time = 0
    chunk_size = 40 
    
    for i in range(0, len(full_coords) - 1, chunk_size - 1):
        chunk = full_coords[i : i + chunk_size]
        if len(chunk) < 2: break
        
        coords_str = ";".join([f"{c[1]},{c[0]}" for c in chunk])
        url = f"http://router.project-osrm.org/route/v1/driving/{coords_str}?overview=full&geometries=geojson"
        try:
            r = requests.get(url, timeout=10); res = r.json()
            if res['code'] == 'Ok':
                combined_geometry.extend(res['routes'][0]['geometry']['coordinates'])
                total_dist += res['routes'][0]['distance']
                total_time += res['routes'][0]['duration']
        except: pass
    return {'geometry': combined_geometry, 'distance': total_dist, 'duration': total_time}

def get_lat_lng(address):
    try:
        gl = Nominatim(user_agent="v50_geo")
        loc = gl.geocode(address, timeout=10)
        return {"lat": loc.latitude, "lng": loc.longitude} if loc else None
    except: return None

def parse_kml_robust(content, name):
    pts = []
    for pm in re.findall(r'<Placemark>(.*?)</Placemark>', content, re.DOTALL):
        n = re.search(r'<(?:name|display_name)>(.*?)</', pm)
        c = re.search(r'<coordinates>\s*([\d\.\-]+),\s*([\d\.\-]+)', pm)
        if c: pts.append({"display_name": n.group(1) if n else "Punkt", "lat": float(c.group(2)), "lng": float(c.group(1)), "source_file": name})
    return pd.DataFrame(pts)

def get_color(name):
    h = int(hashlib.md5(name.encode()).hexdigest(), 16)
    return ['blue', 'purple', 'orange', 'cadetblue', 'pink', 'lightblue', 'lightgreen', 'gray'][h % 8]

# --- 4. UI ---
st.set_page_config(page_title="Optymalizator 500+", page_icon="🗺️", layout="wide")
st.markdown("<style>.centered-trash { display: flex; justify-content: center; padding-top: 10px; }</style>", unsafe_allow_html=True)

with st.sidebar:
    st.header("🗺️ Menu")
    with st.expander("🚀 KML", expanded=True):
        up = st.file_uploader("Pliki KML", accept_multiple_files=True)
        if up and st.button("Wczytaj"):
            st.session_state['data'] = pd.concat([parse_kml_robust(f.read().decode('utf-8'), f.name) for f in up], ignore_index=True)
            st.rerun()
        if st.button("🗑️ Wyczyść wszystko"):
            for k in ['data', 'optimized', 'geometry', 'dist', 'time', 'start_coords', 'meta_coords']:
                if k in st.session_state: st.session_state[k] = pd.DataFrame() if 'data' in k else None
            st.rerun()

    with st.expander("📍 Bazy"):
        with st.form("new_b"):
            n, a = st.text_input("Nazwa:"), st.text_input("Adres:")
            if st.form_submit_button("Dodaj") and n and a:
                st.session_state['saved_locations'][n] = a; save_to_disk(); st.rerun()
        for n, a in st.session_state['saved_locations'].items():
            st.write(f"**{n}**")
            c1, c2, c3 = st.columns([1,1,0.5])
            if c1.button("START", key=f"s_{n}"):
                st.session_state.update({'start_coords': get_lat_lng(a), 'start_name': n}); st.rerun()
            if c2.button("META", key=f"m_{n}"):
                st.session_state.update({'meta_coords': get_lat_lng(a), 'meta_name': n}); st.rerun()
            with c3:
                if st.button("🗑️", key=f"d_{n}"): del st.session_state['saved_locations'][n]; save_to_disk(); st.rerun()

# --- PANEL GŁÓWNY ---
df = st.session_state['data']
sc, mc = st.session_state['start_coords'], st.session_state['meta_coords']

if not df.empty or sc or mc:
    if st.button("🚀 OBLICZ TRASĘ (DLA WIELU PUNKTÓW)", type="primary", use_container_width=True):
        if not (sc and mc): st.error("Wybierz START i METĘ!")
        else:
            with st.spinner(f"Optymalizacja {len(df)} punktów..."):
                curr = {"lat": sc['lat'], "lng": sc['lng'], "display_name": f"START: {st.session_state['start_name']}", "source_file": "START"}
                route = [curr]
                unvisited = df.to_dict('records')
                
                # Algorytm najbliższego sąsiada
                while unvisited:
                    nxt = min(unvisited, key=lambda x: get_road_distance(curr['lat'], curr['lng'], x['lat'], x['lng']))
                    route.append(nxt); curr = nxt; unvisited.remove(nxt)
                
                route.append({"lat": mc['lat'], "lng": mc['lng'], "display_name": f"META: {st.session_state['meta_name']}", "source_file": "META"})
                
                # Zapisujemy trasę do tabeli (TO ZMIENIA KOLEJNOŚĆ W TABELI)
                st.session_state['optimized'] = pd.DataFrame(route)
                
                # Pobieramy linię drogi w kawałkach
                res = get_chunked_route_info([[r['lat'], r['lng']] for r in route])
                st.session_state.update({'geometry': res['geometry'], 'dist': res['distance'], 'time': res['duration']})
                st.rerun()

    if 'dist' in st.session_state:
        m1, m2, m3 = st.columns(3)
        m1.metric("Dystans", f"{st.session_state['dist']/1000:.2f} km")
        m2.metric("Czas", f"{int(st.session_state['time']//3600)}h {int((st.session_state['time']%3600)//60)}min")
        m3.metric("Punkty", len(st.session_state.get('optimized', [])))

    # MAPA
    view_df = st.session_state.get('optimized', df)
    m = folium.Map(location=[52.2, 19.2], zoom_start=6)
    
    # Rysowanie punktów (ograniczamy ikony dla wydajności przy 500+, używamy CircleMarker jeśli trzeba, ale tu zostawiam Icon)
    for i, r in view_df.iterrows():
        color = 'green' if r['source_file'] == "START" else ('red' if r['source_file'] == "META" else get_color(r['source_file']))
        folium.Marker([r['lat'], r['lng']], tooltip=r['display_name'], icon=folium.Icon(color=color)).add_to(m)
    
    if 'geometry' in st.session_state and st.session_state['geometry']:
        folium.PolyLine([[c[1], c[0]] for c in st.session_state['geometry']], color="#4285f4", weight=5).add_to(m)
        m.fit_bounds([[sc['lat'], sc['lng']], [mc['lat'], mc['lng']]])

    st_folium(m, width="100%", height=600, key=f"map_{len(view_df)}")

    # TABELA Z NUMERACJĄ
    st.markdown("### 📋 Kolejność trasy")
    if not view_df.empty:
        # Dodanie numeru przystanku dla czytelności
        table_df = view_df[['display_name', 'source_file']].copy()
        table_df.index = range(1, len(table_df) + 1)
        st.dataframe(table_df, use_container_width=True)
else:
    st.info("👈 Wgraj pliki KML i ustaw bazy.")
