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
    st.info("👈 Wgraj pliki KML i ustaw bazy.")import streamlit as st
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

# --- 1. FUNKCJE ZAPISU TRWAŁEGO ---
STORAGE_FILE = "data_storage.json"

def save_to_disk():
    data_to_save = {
        "saved_locations": st.session_state['saved_locations'],
        "projects": {
            k: {**v, "data": v["data"].to_dict()} 
            for k, v in st.session_state['projects'].items()
        }
    }
    with open(STORAGE_FILE, "w", encoding="utf-8") as f:
        json.dump(data_to_save, f, ensure_ascii=False, indent=4)

def load_from_disk():
    if os.path.exists(STORAGE_FILE):
        try:
            with open(STORAGE_FILE, "r", encoding="utf-8") as f:
                stored = json.load(f)
                st.session_state['saved_locations'] = stored.get("saved_locations", {})
                raw_projects = stored.get("projects", {})
                processed_projects = {}
                for k, v in raw_projects.items():
                    v["data"] = pd.DataFrame(v["data"])
                    processed_projects[k] = v
                st.session_state['projects'] = processed_projects
        except: pass

# --- 2. SYSTEM LOGOWANIA ---
if 'authenticated' not in st.session_state:
    st.session_state['authenticated'] = False

def check_password():
    if st.session_state['authenticated']: return True
    st.set_page_config(page_title="Logowanie", page_icon="🗺️")
    st.title("🔐 Dostęp chroniony")
    with st.form("login_form"):
        pwd_input = st.text_input("Hasło:", type="password")
        if st.form_submit_button("Zaloguj"):
            if "password" in st.secrets and pwd_input == st.secrets["password"]:
                st.session_state['authenticated'] = True
                load_from_disk()
                st.rerun()
            else: st.error("❌ Błędne hasło")
    return False

# Inicjalizacja kluczy
for key in ['data', 'saved_locations', 'projects', 'start_coords', 'meta_coords']:
    if key not in st.session_state: 
        st.session_state[key] = pd.DataFrame() if 'data' in key else (None if 'coords' in key else {})
if 'start_name' not in st.session_state: 
    st.session_state.update({'start_name': "Nie wybrano", 'meta_name': "Nie wybrano", 'start_addr': "", 'meta_addr': ""})

if not check_password(): st.stop()

# --- 3. FUNKCJE POMOCNICZE ---
def get_lat_lng(address):
    if not address: return None
    try:
        gl = Nominatim(user_agent="v49_geocoder")
        loc = gl.geocode(address, timeout=10)
        if loc: return {"lat": loc.latitude, "lng": loc.longitude}
    except: pass
    return None

def get_road_distance(lat1, lon1, lat2, lon2):
    try:
        url = f"http://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=false"
        r = requests.get(url, timeout=5)
        res = r.json()
        if res['code'] == 'Ok': return res['routes'][0]['distance'], res['routes'][0]['duration']
    except: pass
    return math.sqrt((lat1-lat2)**2 + (lon1-lon2)**2) * 111000, 0

def get_full_route_info(coords_list):
    coords_str = ";".join([f"{c[1]},{c[0]}" for c in coords_list])
    url = f"http://router.project-osrm.org/route/v1/driving/{coords_str}?overview=full&geometries=geojson"
    try:
        r = requests.get(url, timeout=10); res = r.json()
        if res['code'] == 'Ok':
            return {'geometry': res['routes'][0]['geometry']['coordinates'], 
                    'distance': res['routes'][0]['distance'], 'duration': res['routes'][0]['duration']}
    except: return None

def parse_kml_robust(file_content, file_name="unknown"):
    placemarks = re.findall(r'<Placemark>(.*?)</Placemark>', file_content, re.DOTALL)
    pts = []
    for pm in placemarks:
        name_match = re.search(r'<(?:name|display_name)>(.*?)</(?:name|display_name)>', pm)
        coords = re.search(r'<coordinates>\s*([\d\.\-]+),\s*([\d\.\-]+)', pm)
        if coords:
            pts.append({"display_name": str(name_match.group(1)) if name_match else "Punkt", 
                        "lat": float(coords.group(2)), "lng": float(coords.group(1)), "source_file": file_name})
    return pd.DataFrame(pts)

def get_color_for_file(file_name):
    folium_colors = ['blue', 'purple', 'orange', 'cadetblue', 'pink', 'lightblue', 'lightgreen', 'gray']
    hash_idx = int(hashlib.md5(file_name.encode()).hexdigest(), 16) % len(folium_colors)
    return folium_colors[hash_idx]

# --- 4. KONFIGURACJA UI ---
st.set_page_config(page_title="Optymalizator Drogowy", page_icon="🗺️", layout="wide")

st.markdown("""<style>
    .centered-trash { display: flex; align-items: center; justify-content: center; height: 100%; padding-top: 10px; }
    .selection-info { font-size: 13px; color: #1e1e1e; background-color: #e8f0fe; padding: 12px; border-radius: 8px; border-left: 6px solid #4285f4; margin-bottom: 15px; }
    </style>""", unsafe_allow_html=True)

# --- SIDEBAR ---
with st.sidebar:
    st.header("🗺️ Menu Główne")
    
    with st.expander("🚀 Wczytaj Dane (KML)", expanded=True):
        st.markdown(f'<div class="selection-info">📍 S: {st.session_state["start_name"]}<br>🏁 M: {st.session_state["meta_name"]}</div>', unsafe_allow_html=True)
        up_kmls = st.file_uploader("Wgraj pliki KML", type=['kml'], accept_multiple_files=True)
        if up_kmls and st.button("Wczytaj wszystkie pliki"):
            all_pts = [parse_kml_robust(f.read().decode('utf-8'), f.name) for f in up_kmls]
            if all_pts:
                st.session_state['data'] = pd.concat(all_pts, ignore_index=True)
                st.rerun()
        if st.button("🗑️ Wyczyść wszystko"):
            for k in ['data', 'optimized', 'geometry', 'dist', 'time', 'start_coords', 'meta_coords']:
                if k in st.session_state: st.session_state[k] = pd.DataFrame() if 'data' in k else None
            st.session_state.update({'start_name': "Nie wybrano", 'meta_name': "Nie wybrano"})
            st.rerun()

    with st.expander("📍 Twoje Bazy", expanded=True):
        with st.form("add_base_form", clear_on_submit=True):
            n_n, n_a = st.text_input("Nazwa bazy:"), st.text_input("Adres bazy:")
            if st.form_submit_button("Dodaj bazę") and n_n and n_a:
                st.session_state['saved_locations'][n_n] = n_a
                save_to_disk(); st.rerun()
        
        for n, a in st.session_state['saved_locations'].items():
            st.markdown(f"**{n}**")
            c1, c2, c3 = st.columns([1.5, 1.5, 0.6])
            if c1.button("Ustaw Start", key=f"s_{n}", use_container_width=True):
                coords = get_lat_lng(a)
                if coords:
                    st.session_state.update({'start_addr': a, 'start_name': n, 'start_coords': coords})
                    st.rerun()
                else: st.error("Nie znaleziono adresu!")
            if c2.button("Ustaw Metę", key=f"m_{n}", use_container_width=True):
                coords = get_lat_lng(a)
                if coords:
                    st.session_state.update({'meta_addr': a, 'meta_name': n, 'meta_coords': coords})
                    st.rerun()
                else: st.error("Nie znaleziono adresu!")
            with c3:
                st.markdown('<div class="centered-trash">', unsafe_allow_html=True)
                if st.button("🗑️", key=f"d_{n}"):
                    del st.session_state['saved_locations'][n]; save_to_disk(); st.rerun()
                st.markdown('</div>', unsafe_allow_html=True)
            st.divider()

    with st.expander("📁 Projekty"):
        p_name = st.text_input("Nazwa projektu:")
        if st.button("Zapisz bieżący stan") and p_name:
            st.session_state['projects'][p_name] = {
                'data': st.session_state['data'].copy(), 'start_addr': st.session_state['start_addr'], 
                'meta_addr': st.session_state['meta_addr'], 'start_name': st.session_state['start_name'], 
                'meta_name': st.session_state['meta_name'], 'start_coords': st.session_state['start_coords'], 
                'meta_coords': st.session_state['meta_coords']
            }
            save_to_disk(); st.toast("Zapisano!")
        if st.session_state['projects']:
            sel_p = st.selectbox("Wczytaj projekt:", list(st.session_state['projects'].keys()))
            if st.button("Wczytaj"):
                st.session_state.update(st.session_state['projects'][sel_p]); st.rerun()

    st.button("🔓 WYLOGUJ", on_click=lambda: st.session_state.update({'authenticated': False}))

# --- PANEL GŁÓWNY ---
st.title("🗺️ Optymalizator Drogowy")

df = st.session_state['data']
sc = st.session_state['start_coords']
mc = st.session_state['meta_coords']

if not df.empty or sc or mc:
    # --- PRZYCISK OBLICZANIA (NAPRAWIONY) ---
    if st.button("🚀 OBLICZ OPTYMALNĄ TRASĘ (OSRM)", type="primary", use_container_width=True):
        if sc is None or mc is None:
            st.error("⚠️ Musisz wybrać punkt STARTU i METĘ w panelu bocznym (przyciski 'Ustaw Start/Metę')!")
        elif df.empty:
            st.error("⚠️ Brak punktów z plików KML do optymalizacji!")
        else:
            with st.spinner("Szukanie trasy..."):
                try:
                    curr = {"lat": sc['lat'], "lng": sc['lng'], "display_name": f"START: {st.session_state['start_name']}", "source_file": "START"}
                    route = [curr]
                    unvisited = df.to_dict('records')
                    while unvisited:
                        nxt = min(unvisited, key=lambda x: get_road_distance(curr['lat'], curr['lng'], x['lat'], x['lng'])[0])
                        route.append(nxt); curr = nxt; unvisited.remove(nxt)
                    route.append({"lat": mc['lat'], "lng": mc['lng'], "display_name": f"META: {st.session_state['meta_name']}", "source_file": "META"})
                    
                    st.session_state['optimized'] = pd.DataFrame(route)
                    f_i = get_full_route_info([[r['lat'], r['lng']] for r in route])
                    if f_i: 
                        st.session_state.update({'geometry': f_i['geometry'], 'dist': f_i['distance'], 'time': f_i['duration']})
                        st.success("Trasa obliczona!")
                        st.rerun()
                except Exception as e:
                    st.error(f"Błąd podczas obliczeń: {e}")

    # Statystyki i Mapa (tylko jeśli dane istnieją)
    if 'dist' in st.session_state:
        m1, m2 = st.columns(2)
        m1.metric("Dystans", f"{st.session_state['dist']/1000:.2f} km")
        m2.metric("Czas", f"{int(st.session_state['time']//3600)}h {int((st.session_state['time']%3600)//60)}min")

    view_df = st.session_state.get('optimized', df)
    # Wyśrodkowanie mapy na punkcie startu lub średniej punktów
    map_center = [sc['lat'], sc['lng']] if sc else ([df['lat'].mean(), df['lng'].mean()] if not df.empty else [52.2, 19.2])
    
    m = folium.Map(location=map_center, zoom_start=10)
    
    if sc: folium.Marker([sc['lat'], sc['lng']], tooltip="START", icon=folium.Icon(color='green', icon='play')).add_to(m)
    if mc:
        d_mc = mc.copy()
        if sc and sc['lat'] == mc['lat']: d_mc['lat'] += 0.0001 # Offset
        folium.Marker([d_mc['lat'], d_mc['lng']], tooltip="META", icon=folium.Icon(color='red', icon='stop')).add_to(m)

    for i, r in view_df.iterrows():
        if r['source_file'] not in ["START", "META"]:
            folium.Marker([r['lat'], r['lng']], tooltip=f"{r['display_name']} ({r['source_file']})",
                          icon=folium.Icon(color=get_color_for_file(r['source_file']))).add_to(m)
    
    if 'geometry' in st.session_state:
        folium.PolyLine([[c[1], c[0]] for c in st.session_state['geometry']], color="#4285f4", weight=5).add_to(m)
        if sc and mc: m.fit_bounds([[sc['lat'], sc['lng']], [mc['lat'], mc['lng']]])

    st_folium(m, width="100%", height=550, key=f"map_{len(view_df)}")
    st.dataframe(view_df[['display_name', 'source_file']], use_container_width=True)
else:
    st.info("👈 Wgraj KML i ustaw Start/Metę (Ustaw Start / Ustaw Metę), aby rozpocząć.")
