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

# --- 1. FUNKCJE ZAPISU TRWAŁEGO ---
STORAGE_FILE = "data_storage.json"

def save_to_disk():
    data = {"saved_locations": st.session_state['saved_locations'], "projects": {k: {**v, "data": v["data"].to_dict()} for k, v in st.session_state['projects'].items()}}
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
    st.title("🔐 Dostęp chroniony")
    with st.form("login"):
        p = st.text_input("Hasło:", type="password")
        if st.form_submit_button("Zaloguj"):
            if "password" in st.secrets and p == st.secrets["password"]:
                st.session_state['authenticated'] = True
                load_from_disk(); st.rerun()
            else: st.error("❌ Błędne hasło")
    return False

# Inicjalizacja sesji
for key in ['data', 'saved_locations', 'projects', 'start_coords', 'meta_coords']:
    if key not in st.session_state: st.session_state[key] = pd.DataFrame() if 'data' in key else (None if 'coords' in key else {})
if 'start_name' not in st.session_state: st.session_state.update({'start_name': "Nie wybrano", 'meta_name': "Nie wybrano"})
if 'delete_mode' not in st.session_state: st.session_state['delete_mode'] = False

if not check_password(): st.stop()

# --- 3. LOGIKA ROUTINGU ---
def get_lat_lng(address):
    try:
        gl = Nominatim(user_agent="v55_geo")
        loc = gl.geocode(address, timeout=10)
        return {"lat": loc.latitude, "lng": loc.longitude} if loc else None
    except: return None

def get_math_dist(lat1, lon1, lat2, lon2):
    return math.sqrt((lat1-lat2)**2 + (lon1-lon2)**2)

def get_chunked_route_info(coords_list):
    combined_geom, total_dist, total_time = [], 0, 0
    chunk_size = 40
    for i in range(0, len(coords_list) - 1, chunk_size - 1):
        chunk = coords_list[i : i + chunk_size]
        if len(chunk) < 2: break
        url = f"http://router.project-osrm.org/route/v1/driving/{';'.join([f'{c[1]},{c[0]}' for c in chunk])}?overview=full&geometries=geojson"
        try:
            r = requests.get(url, timeout=10).json()
            if r['code'] == 'Ok':
                combined_geom.extend(r['routes'][0]['geometry']['coordinates'])
                total_dist += r['routes'][0]['distance']
                total_time += r['routes'][0]['duration']
        except: pass
    return {'geometry': combined_geom, 'distance': total_dist, 'duration': total_time}

def parse_kml_robust(content, name):
    placemarks = re.findall(r'<Placemark>(.*?)</Placemark>', content, re.DOTALL)
    pts = []
    for pm in placemarks:
        n = re.search(r'<(?:name|display_name)>(.*?)</', pm)
        c = re.search(r'<coordinates>\s*([\d\.\-]+),\s*([\d\.\-]+)', pm)
        if c: pts.append({"display_name": n.group(1) if n else "Punkt", "lat": float(c.group(2)), "lng": float(c.group(1)), "source_file": name})
    return pd.DataFrame(pts)

# --- 4. STYLE CSS (NAPRAWA PRZYCISKÓW) ---
st.set_page_config(page_title="Optymalizator Drogowy", page_icon="🗺️", layout="wide")

st.markdown("""
<style>
    /* Stylizacja przycisków baz, aby były kwadratowe i wyśrodkowane */
    div.stButton > button {
        height: 50px;
        width: 100%;
        display: flex;
        justify-content: center;
        align-items: center;
        font-size: 24px !important;
        margin: 0 auto;
        padding: 0 !important;
    }
    /* Zielone tło dla aktywnych wyborów */
    .st-emotion-cache-162963g { background-color: #28a745 !important; color: white !important; }
    
    .selection-info { font-size: 13px; color: #1e1e1e; background-color: #e8f0fe; padding: 12px; border-radius: 8px; border-left: 6px solid #4285f4; margin-bottom: 15px; }
</style>
""", unsafe_allow_html=True)

# --- SIDEBAR ---
with st.sidebar:
    st.header("🗺️ Menu Główne")
    
    with st.expander("🚀 Wczytaj Dane (KML)", expanded=True):
        st.markdown(f'<div class="selection-info">🏠 Start: {st.session_state["start_name"]}<br>🏁 Meta: {st.session_state["meta_name"]}</div>', unsafe_allow_html=True)
        up_kmls = st.file_uploader("Wgraj pliki KML", type=['kml'], accept_multiple_files=True)
        if up_kmls and st.button("Wczytaj dane"):
            all_pts = [parse_kml_robust(f.read().decode('utf-8'), f.name) for f in up_kmls]
            if all_pts: st.session_state['data'] = pd.concat(all_pts, ignore_index=True); st.rerun()

    with st.expander("📍 Twoje Bazy", expanded=True):
        # 1. Wybór bazy
        if st.session_state['saved_locations']:
            sel_b = st.selectbox("Wybierz bazę:", ["--- Wybierz ---"] + list(st.session_state['saved_locations'].keys()))
            
            if sel_b != "--- Wybierz ---":
                addr = st.session_state['saved_locations'][sel_b]
                st.caption(f"Adres: {addr}")
                
                c1, c2, c3 = st.columns(3)
                
                # Dynamiczna zmiana typu przycisku na 'primary' (zielony), jeśli wybrany
                type_s = "primary" if st.session_state['start_name'] == sel_b else "secondary"
                type_m = "primary" if st.session_state['meta_name'] == sel_b else "secondary"

                if c1.button("🏠", key="btn_start", type=type_s, help="Ustaw jako Start"):
                    st.session_state.update({'start_name': sel_b, 'start_coords': get_lat_lng(addr)})
                    st.rerun()
                
                if c2.button("🏁", key="btn_meta", type=type_m, help="Ustaw jako Metę"):
                    st.session_state.update({'meta_name': sel_b, 'meta_coords': get_lat_lng(addr)})
                    st.rerun()
                
                if c3.button("🗑️", key="btn_del", help="Usuń bazę"):
                    st.session_state['delete_mode'] = True

                # Potwierdzenie usunięcia
                if st.session_state['delete_mode']:
                    st.error(f"Na pewno usunąć {sel_b}?")
                    cc1, cc2 = st.columns(2)
                    if cc1.button("TAK", type="primary", use_container_width=True):
                        del st.session_state['saved_locations'][sel_b]
                        st.session_state['delete_mode'] = False
                        save_to_disk(); st.rerun()
                    if cc2.button("NIE", use_container_width=True):
                        st.session_state['delete_mode'] = False
                        st.rerun()
        else:
            st.write("Brak baz.")

        st.divider()
        st.markdown("**Dodaj nową:**")
        with st.form("new_base", clear_on_submit=True):
            n_n, n_a = st.text_input("Nazwa:"), st.text_input("Adres:")
            if st.form_submit_button("Dodaj bazę") and n_n and n_a:
                st.session_state['saved_locations'][n_n] = n_a; save_to_disk(); st.rerun()

    with st.expander("📁 Projekty"):
        p_n = st.text_input("Nazwa projektu:")
        if st.button("Zapisz projekt") and p_n:
            st.session_state['projects'][p_n] = {'data': st.session_state['data'].copy(), 'start_name': st.session_state['start_name'], 'meta_name': st.session_state['meta_name'], 'start_coords': st.session_state['start_coords'], 'meta_coords': st.session_state['meta_coords']}
            save_to_disk(); st.toast("Zapisano!")
        if st.session_state['projects']:
            sel_p = st.selectbox("Wczytaj projekt:", list(st.session_state['projects'].keys()))
            if st.button("Wczytaj"): st.session_state.update(st.session_state['projects'][sel_p]); st.rerun()

    st.button("🔓 WYLOGUJ", on_click=lambda: st.session_state.update({'authenticated': False}), use_container_width=True)

# --- 5. PANEL GŁÓWNY ---
st.title("🗺️ Optymalizator Drogowy")

df = st.session_state['data']
sc, mc = st.session_state['start_coords'], st.session_state['meta_coords']

if not df.empty or sc or mc:
    col_run, col_reset = st.columns([3, 1])
    with col_run:
        if st.button("🚀 OBLICZ OPTYMALNĄ TRASĘ", type="primary", use_container_width=True):
            if not (sc and mc): st.error("⚠️ Wybierz Start i Metę!")
            else:
                with st.spinner("Liczenie..."):
                    curr = {"lat": sc['lat'], "lng": sc['lng'], "display_name": f"START: {st.session_state['start_name']}", "source_file": "START"}
                    route, unvisited = [curr], df.to_dict('records')
                    while unvisited:
                        nxt = min(unvisited, key=lambda x: get_math_dist(curr['lat'], curr['lng'], x['lat'], x['lng']))
                        route.append(nxt); curr = nxt; unvisited.remove(nxt)
                    route.append({"lat": mc['lat'], "lng": mc['lng'], "display_name": f"META: {st.session_state['meta_name']}", "source_file": "META"})
                    st.session_state['optimized'] = pd.DataFrame(route)
                    res = get_chunked_route_info([[r['lat'], r['lng']] for r in route])
                    st.session_state.update({'geometry': res['geometry'], 'dist': res['distance'], 'time': res['duration']})
                    st.rerun()
    with col_reset:
        if st.button("🔄 RESET", use_container_width=True):
            for k in ['data', 'optimized', 'geometry', 'dist', 'time', 'start_coords', 'meta_coords']:
                if k in st.session_state: st.session_state[k] = pd.DataFrame() if 'data' in k else None
            st.session_state.update({'start_name': "Nie wybrano", 'meta_name': "Nie wybrano"})
            st.rerun()

    if 'dist' in st.session_state:
        m1, m2, m3 = st.columns(3)
        m1.metric("Dystans", f"{st.session_state['dist']/1000:.2f} km")
        m2.metric("Czas", f"{int(st.session_state['time']//3600)}h {int((st.session_state['time']%3600)//60)}min")
        m3.metric("Punkty", len(st.session_state.get('optimized', [])))

    # Mapa i tabela
    v_df = st.session_state.get('optimized', df)
    m = folium.Map(location=[52.2, 19.2], zoom_start=6)
    if sc: folium.Marker([sc['lat'], sc['lng']], tooltip="START", icon=folium.Icon(color='green', icon='home')).add_to(m)
    if mc: folium.Marker([mc['lat'], mc['lng']], tooltip="META", icon=folium.Icon(color='red', icon='flag')).add_to(m)
    
    if 'geometry' in st.session_state and st.session_state['geometry']:
        folium.PolyLine([[c[1], c[0]] for c in st.session_state['geometry']], color="#4285f4", weight=5).add_to(m)
        m.fit_bounds([[sc['lat'], sc['lng']], [mc['lat'], mc['lng']]])

    st_folium(m, width="100%", height=500, key=f"map_{len(v_df)}")
    st.dataframe(v_df[['display_name', 'source_file']], use_container_width=True)
else:
    st.info("👈 Wgraj KML i wybierz bazy (🏠/🏁).")import streamlit as st
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

# --- 1. FUNKCJE ZAPISU TRWAŁEGO (Autosave) ---
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
                st.session_state['projects'] = {
                    k: {**v, "data": pd.DataFrame(v["data"])} 
                    for k, v in stored.get("projects", {}).items()
                }
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

# Inicjalizacja kluczy sesji
for key in ['data', 'saved_locations', 'projects', 'start_coords', 'meta_coords']:
    if key not in st.session_state: 
        st.session_state[key] = pd.DataFrame() if 'data' in key else (None if 'coords' in key else {})
if 'start_name' not in st.session_state: 
    st.session_state.update({'start_name': "Nie wybrano", 'meta_name': "Nie wybrano", 'start_addr': "", 'meta_addr': ""})

if not check_password(): st.stop()

# --- 3. FUNKCJE POMOCNICZE ---
def get_lat_lng(address):
    try:
        gl = Nominatim(user_agent="v54_geocoder")
        loc = gl.geocode(address, timeout=10)
        return {"lat": loc.latitude, "lng": loc.longitude} if loc else None
    except: return None

def get_math_dist(lat1, lon1, lat2, lon2):
    return math.sqrt((lat1-lat2)**2 + (lon1-lon2)**2)

def get_chunked_route_info(coords_list):
    combined_geometry, total_dist, total_time = [], 0, 0
    chunk_size = 40
    for i in range(0, len(coords_list) - 1, chunk_size - 1):
        chunk = coords_list[i : i + chunk_size]
        if len(chunk) < 2: break
        url = f"http://router.project-osrm.org/route/v1/driving/{';'.join([f'{c[1]},{c[0]}' for c in chunk])}?overview=full&geometries=geojson"
        try:
            r = requests.get(url, timeout=10).json()
            if r['code'] == 'Ok':
                combined_geometry.extend(r['routes'][0]['geometry']['coordinates'])
                total_dist += r['routes'][0]['distance']
                total_time += r['routes'][0]['duration']
        except: pass
    return {'geometry': combined_geometry, 'distance': total_dist, 'duration': total_time}

def parse_kml_robust(file_content, file_name):
    placemarks = re.findall(r'<Placemark>(.*?)</Placemark>', file_content, re.DOTALL)
    pts = []
    for pm in placemarks:
        name = re.search(r'<(?:name|display_name)>(.*?)</', pm)
        coords = re.search(r'<coordinates>\s*([\d\.\-]+),\s*([\d\.\-]+)', pm)
        if coords:
            pts.append({"display_name": name.group(1) if name else "Punkt", "lat": float(coords.group(2)), "lng": float(coords.group(1)), "source_file": file_name})
    return pd.DataFrame(pts)

def get_color_for_file(file_name):
    fol_colors = ['blue', 'purple', 'orange', 'cadetblue', 'pink', 'lightblue', 'lightgreen', 'gray']
    hash_idx = int(hashlib.md5(file_name.encode()).hexdigest(), 16) % len(fol_colors)
    return fol_colors[hash_idx]

# --- 4. KONFIGURACJA UI ---
st.set_page_config(page_title="Optymalizator Drogowy", page_icon="🗺️", layout="wide")
st.markdown("""<style>
    .centered-trash { display: flex; align-items: center; justify-content: center; height: 100%; padding-top: 5px; }
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
            if all_pts: st.session_state['data'] = pd.concat(all_pts, ignore_index=True); st.rerun()

    # --- SEKCJA TWOJE BAZY (NOWA KOLEJNOŚĆ) ---
    with st.expander("📍 Twoje Bazy", expanded=True):
        # 1. NAJPIERW LISTA WYBORU
        if st.session_state['saved_locations']:
            selected_base_name = st.selectbox("Wybierz bazę:", ["--- Wybierz ---"] + list(st.session_state['saved_locations'].keys()))
            
            if selected_base_name != "--- Wybierz ---":
                addr = st.session_state['saved_locations'][selected_base_name]
                st.info(f"Adres: {addr}")
                
                c1, c2, c3 = st.columns([1, 1, 0.5])
                if c1.button("Ustaw Start", use_container_width=True):
                    st.session_state.update({'start_addr': addr, 'start_name': selected_base_name, 'start_coords': get_lat_lng(addr)})
                    st.rerun()
                if c2.button("Ustaw Metę", use_container_width=True):
                    st.session_state.update({'meta_addr': addr, 'meta_name': selected_base_name, 'meta_coords': get_lat_lng(addr)})
                    st.rerun()
                with c3:
                    st.markdown('<div class="centered-trash">', unsafe_allow_html=True)
                    if st.button("🗑️", help="Usuń bazę"):
                        del st.session_state['saved_locations'][selected_base_name]
                        save_to_disk(); st.rerun()
                    st.markdown('</div>', unsafe_allow_html=True)
        else:
            st.write("Brak zapisanych baz.")

        st.divider()
        
        # 2. POTEM FORMULARZ DODAWANIA
        st.markdown("**Dodaj nową bazę:**")
        with st.form("add_base_form", clear_on_submit=True):
            n_n, n_a = st.text_input("Nazwa bazy:"), st.text_input("Adres bazy:")
            if st.form_submit_button("Dodaj bazę") and n_n and n_a:
                st.session_state['saved_locations'][n_n] = n_a; save_to_disk(); st.rerun()

    with st.expander("📁 Projekty"):
        p_name = st.text_input("Nazwa projektu:")
        if st.button("Zapisz projekt") and p_name:
            st.session_state['projects'][p_name] = {
                'data': st.session_state['data'].copy(), 'start_addr': st.session_state['start_addr'], 'start_name': st.session_state['start_name'],
                'meta_addr': st.session_state['meta_addr'], 'meta_name': st.session_state['meta_name'], 'start_coords': st.session_state['start_coords'], 'meta_coords': st.session_state['meta_coords']
            }
            save_to_disk(); st.toast("Projekt zapisany!")
        if st.session_state['projects']:
            sel_p = st.selectbox("Wczytaj projekt:", list(st.session_state['projects'].keys()))
            if st.button("Wczytaj"): st.session_state.update(st.session_state['projects'][sel_p]); st.rerun()

    st.button("🔓 WYLOGUJ", on_click=lambda: st.session_state.update({'authenticated': False}), use_container_width=True)

# --- PANEL GŁÓWNY ---
st.title("🗺️ Optymalizator Drogowy")

df = st.session_state['data']
sc, mc = st.session_state['start_coords'], st.session_state['meta_coords']

if not df.empty or sc or mc:
    col_run, col_reset = st.columns([3, 1])
    
    with col_run:
        if st.button("🚀 OBLICZ TRASĘ (DLA WIELU PUNKTÓW)", type="primary", use_container_width=True):
            if not (sc and mc): st.error("⚠️ Wybierz Start i Metę w panelu bocznym!")
            else:
                with st.spinner(f"Optymalizacja {len(df)} punktów..."):
                    curr = {"lat": sc['lat'], "lng": sc['lng'], "display_name": f"START: {st.session_state['start_name']}", "source_file": "START"}
                    route, unvisited = [curr], df.to_dict('records')
                    while unvisited:
                        nxt = min(unvisited, key=lambda x: get_math_dist(curr['lat'], curr['lng'], x['lat'], x['lng']))
                        route.append(nxt); curr = nxt; unvisited.remove(nxt)
                    route.append({"lat": mc['lat'], "lng": mc['lng'], "display_name": f"META: {st.session_state['meta_name']}", "source_file": "META"})
                    st.session_state['optimized'] = pd.DataFrame(route)
                    res = get_chunked_route_info([[r['lat'], r['lng']] for r in route])
                    st.session_state.update({'geometry': res['geometry'], 'dist': res['distance'], 'time': res['duration']})
                    st.rerun()

    with col_reset:
        if st.button("🔄 WYCZYŚĆ AKTUALNĄ TRASĘ", use_container_width=True):
            for k in ['data', 'optimized', 'geometry', 'dist', 'time', 'start_coords', 'meta_coords']:
                if k in st.session_state: st.session_state[k] = pd.DataFrame() if 'data' in k else None
            st.session_state.update({'start_name': "Nie wybrano", 'meta_name': "Nie wybrano", 'start_addr': "", 'meta_addr': ""})
            st.rerun()

    if 'dist' in st.session_state:
        m1, m2, m3 = st.columns(3)
        m1.metric("Dystans", f"{st.session_state['dist']/1000:.2f} km")
        m2.metric("Czas", f"{int(st.session_state['time']//3600)}h {int((st.session_state['time']%3600)//60)}min")
        m3.metric("Punkty", len(st.session_state.get('optimized', [])))

    view_df = st.session_state.get('optimized', df)
    m = folium.Map(location=[52.2, 19.2], zoom_start=6)
    
    disp_mc = mc.copy() if mc else None
    if sc and mc and sc['lat'] == mc['lat']: disp_mc['lat'] += 0.00015; disp_mc['lng'] += 0.00015

    if sc: folium.Marker([sc['lat'], sc['lng']], tooltip="START", icon=folium.Icon(color='green', icon='play')).add_to(m)
    if disp_mc: folium.Marker([disp_mc['lat'], disp_mc['lng']], tooltip="META", icon=folium.Icon(color='red', icon='stop')).add_to(m)

    for i, r in view_df.iterrows():
        if r['source_file'] not in ["START", "META"]:
            folium.Marker([r['lat'], r['lng']], tooltip=r['display_name'], icon=folium.Icon(color=get_color_for_file(r['source_file']))).add_to(m)
    
    if 'geometry' in st.session_state and st.session_state['geometry']:
        folium.PolyLine([[c[1], c[0]] for c in st.session_state['geometry']], color="#4285f4", weight=5).add_to(m)
        m.fit_bounds([[sc['lat'], sc['lng']], [mc['lat'], mc['lng']]])

    st_folium(m, width="100%", height=550, key=f"map_{len(view_df)}")
    st.markdown("### 📋 Kolejność przystanków")
    if not view_df.empty:
        table_df = view_df[['display_name', 'source_file']].copy()
        table_df.index = range(1, len(table_df) + 1)
        st.dataframe(table_df, use_container_width=True)
else:
    st.info("👈 Wczytaj KML i wybierz bazy z listy powyżej.")
