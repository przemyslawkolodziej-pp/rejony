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

# --- 1. FUNKCJE ZAPISU TRWAŁEGO (DYSK SERWERA) ---
STORAGE_FILE = "data_storage.json"

def save_to_disk():
    """Zapisuje bazy i projekty do pliku JSON na serwerze."""
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
    """Wczytuje dane z pliku JSON przy starcie."""
    if os.path.exists(STORAGE_FILE):
        try:
            with open(STORAGE_FILE, "r", encoding="utf-8") as f:
                stored = json.load(f)
                st.session_state['saved_locations'] = stored.get("saved_locations", {})
                
                # Konwersja projektów z dict z powrotem na DataFrame
                raw_projects = stored.get("projects", {})
                processed_projects = {}
                for k, v in raw_projects.items():
                    v["data"] = pd.DataFrame(v["data"])
                    processed_projects[k] = v
                st.session_state['projects'] = processed_projects
        except Exception as e:
            st.error(f"Błąd wczytywania bazy z dysku: {e}")

# --- 2. SYSTEM LOGOWANIA ---
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
                # Po zalogowaniu wczytujemy dane z dysku
                load_from_disk()
                st.rerun()
            else:
                st.error("❌ Błędne hasło")
    return False

# Inicjalizacja kluczy sesji zanim sprawdzimy hasło (żeby load_from_disk miało gdzie pisać)
for key in ['data', 'saved_locations', 'projects', 'start_coords', 'meta_coords']:
    if key not in st.session_state: 
        st.session_state[key] = pd.DataFrame() if 'data' in key else (None if 'coords' in key else {})

if not check_password():
    st.stop()

# --- 3. FUNKCJE POMOCNICZE (BEZ ZMIAN) ---
@st.cache_data(show_spinner=False)
def get_lat_lng(address):
    if not address: return None
    try:
        gl = Nominatim(user_agent="v48_geocoder")
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
        name = name_match.group(1) if name_match else "Punkt"
        coords = re.search(r'<coordinates>\s*([\d\.\-]+),\s*([\d\.\-]+)', pm)
        if coords:
            pts.append({"display_name": str(name), "lat": float(coords.group(2)), "lng": float(coords.group(1)), "source_file": file_name})
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

if 'start_name' not in st.session_state: 
    st.session_state.update({'start_name': "Nie wybrano", 'meta_name': "Nie wybrano", 'start_addr': "", 'meta_addr': ""})

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
        if st.button("🗑️ Wyczyść aktualne dane"):
            st.session_state['data'] = pd.DataFrame()
            st.session_state.update({'start_name': "Nie wybrano", 'meta_name': "Nie wybrano", 'start_addr': "", 'meta_addr': ""})
            st.session_state['start_coords'] = st.session_state['meta_coords'] = None
            st.rerun()

    with st.expander("📍 Twoje Bazy", expanded=True):
        with st.form("add_base_form", clear_on_submit=True):
            n_n, n_a = st.text_input("Nazwa bazy:"), st.text_input("Adres bazy:")
            if st.form_submit_button("Dodaj bazę") and n_n and n_a:
                st.session_state['saved_locations'][n_n] = n_a
                save_to_disk() # ZAPIS NA DYSK
                st.rerun()
        
        st.divider()
        for n, a in st.session_state['saved_locations'].items():
            st.markdown(f"**{n}**")
            c1, c2, c3 = st.columns([1.5, 1.5, 0.6])
            with c1:
                if st.button("Ustaw Start", key=f"s_{n}", use_container_width=True):
                    st.session_state.update({'start_addr': a, 'start_name': n})
                    st.session_state['start_coords'] = get_lat_lng(a); st.rerun()
            with c2:
                if st.button("Ustaw Metę", key=f"m_{n}", use_container_width=True):
                    st.session_state.update({'meta_addr': a, 'meta_name': n})
                    st.session_state['meta_coords'] = get_lat_lng(a); st.rerun()
            with c3:
                st.markdown('<div class="centered-trash">', unsafe_allow_html=True)
                if st.button("🗑️", key=f"d_{n}"):
                    del st.session_state['saved_locations'][n]
                    save_to_disk() # ZAPIS NA DYSK
                    st.rerun()
                st.markdown('</div>', unsafe_allow_html=True)
            st.divider()

    with st.expander("📁 Projekty", expanded=False):
        p_name = st.text_input("Nazwa projektu:")
        if st.button("Zapisz bieżący stan") and p_name:
            st.session_state['projects'][p_name] = {
                'data': st.session_state['data'].copy(), 'start_addr': st.session_state['start_addr'], 
                'meta_addr': st.session_state['meta_addr'], 'start_name': st.session_state['start_name'], 
                'meta_name': st.session_state['meta_name'], 'start_coords': st.session_state['start_coords'], 
                'meta_coords': st.session_state['meta_coords']
            }
            save_to_disk() # ZAPIS NA DYSK
            st.toast(f"Zapisano projekt: {p_name}")
        
        if st.session_state['projects']:
            sel_p = st.selectbox("Wczytaj projekt:", list(st.session_state['projects'].keys()))
            cp1, cp2 = st.columns(2)
            if cp1.button("Wczytaj"):
                st.session_state.update(st.session_state['projects'][sel_p])
                st.rerun()
            if cp2.button("Usuń projekt"):
                del st.session_state['projects'][sel_p]
                save_to_disk() # ZAPIS NA DYSK
                st.rerun()

    with st.expander("💾 Kopia zapasowa (Plik)"):
        export_data = {"saved_locations": st.session_state['saved_locations'], 
                       "projects": {k: {**v, "data": v["data"].to_dict()} for k, v in st.session_state['projects'].items()}}
        st.download_button("📥 Pobierz JSON", data=json.dumps(export_data), file_name="backup.json")

    if st.button("🔓 WYLOGUJ", use_container_width=True):
        st.session_state['authenticated'] = False
        st.rerun()

# --- PANEL GŁÓWNY ---
st.title("🗺️ Optymalizator Drogowy")

df = st.session_state['data']
sc = st.session_state['start_coords']
mc = st.session_state['meta_coords']

# Offset dla Mety jeśli adresy identyczne
display_mc = mc.copy() if mc else None
if sc and mc and sc['lat'] == mc['lat'] and sc['lng'] == mc['lng']:
    display_mc['lat'] += 0.00012; display_mc['lng'] += 0.00012

if not df.empty or sc or mc:
    if st.button("🚀 OBLICZ OPTYMALNĄ TRASĘ (OSRM)", type="primary", use_container_width=True):
        if sc and mc:
            with st.spinner("Szukanie najkrótszej drogi..."):
                curr = {"lat": sc['lat'], "
