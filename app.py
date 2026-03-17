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
    st.info("👈 Wgraj KML i wybierz bazy (🏠/🏁).")
