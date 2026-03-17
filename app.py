import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
import re, math, json, requests, os

# --- 1. ZAPIS I LOGOWANIE ---
STORAGE_FILE = "data_storage.json"
def save_to_disk():
    data = {
        "saved_locations": st.session_state['saved_locations'], 
        "projects": {k: {**v, "data": v["data"].to_dict()} for k, v in st.session_state['projects'].items()}
    }
    with open(STORAGE_FILE, "w", encoding="utf-8") as f: 
        json.dump(data, f, ensure_ascii=False, indent=4)

def load_from_disk():
    if os.path.exists(STORAGE_FILE):
        try:
            with open(STORAGE_FILE, "r", encoding="utf-8") as f:
                s = json.load(f)
                st.session_state['saved_locations'] = s.get("saved_locations", {})
                st.session_state['projects'] = {
                    k: {**v, "data": pd.DataFrame(v["data"])} for k, v in s.get("projects", {}).items()
                }
        except: pass

if 'authenticated' not in st.session_state: st.session_state['authenticated'] = False
def check_password():
    if st.session_state['authenticated']: return True
    st.set_page_config(page_title="Optymalizator v73", page_icon="📍", layout="wide")
    st.title("🔐 Logowanie")
    with st.form("login"):
        p = st.text_input("Hasło:", type="password")
        if st.form_submit_button("Zaloguj"):
            if "password" in st.secrets and p == st.secrets["password"]:
                st.session_state['authenticated'] = True; load_from_disk(); st.rerun()
            else: st.error("❌ Błędne hasło")
    return False

# Inicjalizacja sesji
for key in ['data', 'optimized_list', 'saved_locations', 'projects', 'start_coords', 'meta_coords', 'total_dist', 'total_time', 'geometries']:
    if key not in st.session_state: 
        st.session_state[key] = pd.DataFrame() if key == 'data' else ([] if key in ['optimized_list', 'geometries'] else ({} if key in ['saved_locations', 'projects'] else None))
if 'start_name' not in st.session_state: st.session_state.update({'start_name': "Nie wybrano", 'meta_name': "Nie wybrano"})

if not check_password(): st.stop()

# --- 2. STYLE CSS ---
st.markdown("""
<style>
    div.stButton > button { height: 50px; width: 100%; font-size: 16px !important; border-radius: 10px; }
    .selection-info { background-color: rgba(0,0,0,0.05); padding: 12px; border-radius: 8px; border-left: 5px solid #4285f4; margin-bottom: 15px; font-size: 14px; }
    .stats-card { background-color: rgba(0,0,0,0.03); padding: 15px; border-radius: 10px; border: 1px solid rgba(0,0,0,0.1); margin-bottom: 20px; color: inherit; }
    .route-sum { font-weight: bold; font-size: 18px; border-top: 2px solid #28a745; padding-top: 10px; margin-top: 10px; }
    button[kind="primary"] { background-color: #28a745 !important; color: white !important; }
</style>
""", unsafe_allow_html=True)

# --- 3. LOGIKA I POMOCNICZE ---
def get_folium_color(idx):
    colors = ['blue', 'red', 'green', 'orange', 'purple', 'cadetblue', 'darkred', 'darkblue', 'darkgreen']
    return colors[idx % len(colors)]

file_color_map = {}
if not st.session_state['data'].empty:
    unique_files = sorted(st.session_state['data']['source_file'].unique().tolist())
    for i, f in enumerate(unique_files):
        file_color_map[f] = get_folium_color(i)

def get_lat_lng(address):
    try:
        gl = Nominatim(user_agent="v73_geo")
        loc = gl.geocode(address, timeout=10)
        return {"lat": loc.latitude, "lng": loc.longitude} if loc else None
    except: return None

def get_math_dist(lat1, lon1, lat2, lon2): return math.sqrt((lat1-lat2)**2 + (lon1-lon2)**2)

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
                dist += r['routes'][0]['distance']; time += r['routes'][0]['duration']
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

# --- 4. SIDEBAR ---
with st.sidebar:
    st.header("🗺️ Menu")
    
    with st.expander("🚀 Pliki i Widoczność", expanded=True):
        st.markdown(f'<div class="selection-info">🏠 <b>Start:</b> {st.session_state["start_name"]}<br>🏁 <b>Meta:</b> {st.session_state["meta_name"]}</div>', unsafe_allow_html=True)
        up = st.file_uploader("Wgraj KML", type=['kml'], accept_multiple_files=True)
        if up and st.button("Wczytaj"):
            all_pts = [parse_kml(f.read().decode('utf-8'), f.name) for f in up]
            if all_pts: st.session_state['data'] = pd.concat(all_pts, ignore_index=True); st.rerun()
        
        filtered_df = st.session_state['data']
        if not st.session_state['data'].empty:
            u_files = sorted(st.session_state['data']['source_file'].unique().tolist())
            v_files = st.multiselect("Widoczne rejony:", u_files, default=u_files)
            filtered_df = st.session_state['data'][st.session_state['data']['source_file'].isin(v_files)]

    with st.expander("📍 Bazy", expanded=True):
        if st.session_state['saved_locations']:
            sel_b = st.selectbox("Wybierz bazę:", ["---"] + list(st.session_state['saved_locations'].keys()))
            if sel_b != "---":
                addr = st.session_state['saved_locations'][sel_b]
                c1, c2, c3 = st.columns([1, 1, 0.5])
                with c1:
                    if st.button("Ustaw\nStart", key="s_btn", type="primary" if st.session_state['start_name']==sel_b else "secondary"):
                        st.session_state.update({'start_name': sel_b, 'start_coords': get_lat_lng(addr)}); st.rerun()
                with c2:
                    if st.button("Ustaw\nMetę", key="m_btn", type="primary" if st.session_state['meta_name']==sel_b else "secondary"):
                        st.session_state.update({'meta_name': sel_b, 'meta_coords': get_lat_lng(addr)}); st.rerun()
                with c3:
                    if st.button("🗑️", key="del_loc"): del st.session_state['saved_locations'][sel_b]; save_to_disk(); st.rerun()
        with st.form("new_b", clear_on_submit=True):
            n, a = st.text_input("Nazwa:"), st.text_input("Adres:")
            if st.form_submit_button("Dodaj bazę"): st.session_state['saved_locations'][n] = a; save_to_disk(); st.rerun()

    # --- PRZYWRÓCONA SEKCJA PROJEKTÓW ---
    with st.expander("📁 Projekty", expanded=False):
        p_name = st.text_input("Nazwa projektu:")
        if st.button("💾 Zapisz Projekt") and p_name:
            st.session_state['projects'][p_name] = {
                'data': st.session_state['data'].copy(), 'start_name': st.session_state['start_name'], 'meta_name': st.session_state['meta_name'],
                'start_coords': st.session_state['start_coords'], 'meta_coords': st.session_state['meta_coords'],
                'optimized_list': st.session_state['optimized_list'], 'geometries': st.session_state['geometries'],
                'total_dist': st.session_state['total_dist'], 'total_time': st.session_state['total_time']
            }
            save_to_disk(); st.toast("Zapisano projekt!")
        
        if st.session_state['projects']:
            st.divider()
            sel_p = st.selectbox("Wczytaj projekt:", ["---"] + list(st.session_state['projects'].keys()))
            if sel_p != "---":
                col_load, col_del = st.columns([2, 1])
                if col_load.button("Otwórz"): st.session_state.update(st.session_state['projects'][sel_p]); st.rerun()
                if col_del.button("🗑️", key="del_proj"): del st.session_state['projects'][sel_p]; save_to_disk(); st.rerun()

    st.button("🔓 WYLOGUJ", on_click=lambda: st.session_state.update({'authenticated': False}))

# --- 5. PANEL GŁÓWNY ---
st.title("🗺️ Optymalizator")
sc, mc = st.session_state['start_coords'], st.session_state['meta_coords']

if not filtered_df.empty or sc:
    mode = st.radio("Tryb pracy:", ["Jedna trasa zbiorcza", "Oddzielne trasy dla plików"], horizontal=True)
    
    if st.button("🚀 OBLICZ TRASY", type="primary", use_container_width=True):
        if not (sc and mc): st.error("Wybierz Start i Metę!")
        else:
            with st.spinner("Przeliczanie..."):
                st.session_state.update({'optimized_list': [], 'geometries': [], 'total_dist': 0, 'total_time': 0})
                groups = [filtered_df] if mode == "Jedna trasa zbiorcza" else [filtered_df[filtered_df['source_file'] == f] for f in filtered_df['source_file'].unique()]
                for i, group in enumerate(groups):
                    curr = {"lat": sc['lat'], "lng": sc['lng'], "display_name": "START", "source_file": "Baza"}
                    route, unv = [curr], group.to_dict('records')
                    while unv:
                        nxt = min(unv, key=lambda x: get_math_dist(curr['lat'], curr['lng'], x['lat'], x['lng']))
                        route.append(nxt); curr = nxt; unv.remove(nxt)
                    route.append({"lat": mc['lat'], "lng": mc['lng'], "display_name": "META", "source_file": "Baza"})
                    geom, d, t = get_route_chunked([[r['lat'], r['lng']] for r in route])
                    st.session_state['optimized_list'].append(pd.DataFrame(route))
                    st.session_state['geometries'].append({
                        "geom": geom, "color": file_color_map.get(group['source_file'].iloc[0], 'blue') if mode != "Jedna trasa zbiorcza" else 'blue', 
                        "dist": d, "time": t, "pts_count": len(group), "name": group['source_file'].iloc[0] if mode != "Jedna trasa zbiorcza" else "Całość"
                    })
                    st.session_state['total_dist'] += d; st.session_state['total_time'] += t
                st.rerun()

    # MAPA
    all_pts_coords = [[sc['lat'], sc['lng']]] if sc else []
    if mc: all_pts_coords.append([mc['lat'], mc['lng']])
    for _, r in filtered_df.iterrows(): all_pts_coords.append([r['lat'], r['lng']])

    m = folium.Map()
    if all_pts_coords: m.fit_bounds(all_pts_coords)
    else: m.location = [52.2, 19.2]; m.zoom_start = 6

    if sc: folium.Marker([sc['lat'], sc['lng']], icon=folium.Icon(color='green', icon='home', prefix='fa')).add_to(m)
    if mc: folium.Marker([mc['lat'], mc['lng']], icon=folium.Icon(color='red', icon='flag', prefix='fa')).add_to(m)
    for g in st.session_state['geometries']:
        folium.PolyLine([[c[1], c[0]] for c in g['geom']], color=g['color'], weight=5, opacity=0.7).add_to(m)
    for _, r in filtered_df.iterrows():
        color = file_color_map.get(r['source_file'], 'gray')
        folium.Marker([r['lat'], r['lng']], icon=folium.Icon(color=color, icon='circle', prefix='fa'), tooltip=r['display_name']).add_to(m)
    
    st_folium(m, width="100%", height=550, key="map_v73")

    # SEKCJA WYNIKÓW
    if st.session_state['geometries']:
        st.markdown("### 📊 Wyniki Trasy")
        cols = st.columns(min(len(st.session_state['geometries']), 4))
        for idx, g in enumerate(st.session_state['geometries']):
            with cols[idx % 4]:
                st.markdown(f"""
                <div class="stats-card">
                    <span style="color:{g['color']}; font-size: 20px;">📍</span> <b>Trasa {idx+1}</b><br>
                    <small>{g['name']}</small><br>
                    <b>Dystans: {g['dist']/1000:.2f} km</b><br>
                    Czas: {int(g['time']//3600)}h {int((g['time']%3600)//60)}min<br>
                    Punkty: {g['pts_count']}
                </div>
                """, unsafe_allow_html=True)
        
        st.markdown(f"""
        <div class="stats-card route-sum">
            🌍 ŁĄCZNIE: {st.session_state['total_dist']/1000:.2f} km | {int(st.session_state['total_time']//3600)}h {int((st.session_state['total_time']%3600)//60)}min
        </div>
        """, unsafe_allow_html=True)

    # TABELE
    if st.session_state['optimized_list']:
        st.markdown("### 📋 Szczegółowy Plan")
        for i, opt_df in enumerate(st.session_state['optimized_list']):
            with st.expander(f"Tabela przystanków - Trasa {i+1}", expanded=False):
                st.table(opt_df[['display_name', 'source_file']])
else:
    st.info("👈 Wczytaj KML i wybierz bazy.")import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
import re, math, json, requests, os

# --- 1. ZAPIS I LOGOWANIE ---
STORAGE_FILE = "data_storage.json"
def save_to_disk():
    data = {
        "saved_locations": st.session_state['saved_locations'], 
        "projects": {k: {**v, "data": v["data"].to_dict()} for k, v in st.session_state['projects'].items()}
    }
    with open(STORAGE_FILE, "w", encoding="utf-8") as f: 
        json.dump(data, f, ensure_ascii=False, indent=4)

def load_from_disk():
    if os.path.exists(STORAGE_FILE):
        try:
            with open(STORAGE_FILE, "r", encoding="utf-8") as f:
                s = json.load(f)
                st.session_state['saved_locations'] = s.get("saved_locations", {})
                st.session_state['projects'] = {
                    k: {**v, "data": pd.DataFrame(v["data"])} for k, v in s.get("projects", {}).items()
                }
        except: pass

if 'authenticated' not in st.session_state: st.session_state['authenticated'] = False
def check_password():
    if st.session_state['authenticated']: return True
    st.set_page_config(page_title="Optymalizator v73", page_icon="📍", layout="wide")
    st.title("🔐 Logowanie")
    with st.form("login"):
        p = st.text_input("Hasło:", type="password")
        if st.form_submit_button("Zaloguj"):
            if "password" in st.secrets and p == st.secrets["password"]:
                st.session_state['authenticated'] = True; load_from_disk(); st.rerun()
            else: st.error("❌ Błędne hasło")
    return False

# Inicjalizacja sesji
for key in ['data', 'optimized_list', 'saved_locations', 'projects', 'start_coords', 'meta_coords', 'total_dist', 'total_time', 'geometries']:
    if key not in st.session_state: 
        st.session_state[key] = pd.DataFrame() if key == 'data' else ([] if key in ['optimized_list', 'geometries'] else ({} if key in ['saved_locations', 'projects'] else None))
if 'start_name' not in st.session_state: st.session_state.update({'start_name': "Nie wybrano", 'meta_name': "Nie wybrano"})

if not check_password(): st.stop()

# --- 2. STYLE CSS ---
st.markdown("""
<style>
    div.stButton > button { height: 50px; width: 100%; font-size: 16px !important; border-radius: 10px; }
    .selection-info { background-color: rgba(0,0,0,0.05); padding: 12px; border-radius: 8px; border-left: 5px solid #4285f4; margin-bottom: 15px; font-size: 14px; }
    .stats-card { background-color: rgba(0,0,0,0.03); padding: 15px; border-radius: 10px; border: 1px solid rgba(0,0,0,0.1); margin-bottom: 20px; color: inherit; }
    .route-sum { font-weight: bold; font-size: 18px; border-top: 2px solid #28a745; padding-top: 10px; margin-top: 10px; }
    button[kind="primary"] { background-color: #28a745 !important; color: white !important; }
</style>
""", unsafe_allow_html=True)

# --- 3. LOGIKA I POMOCNICZE ---
def get_folium_color(idx):
    colors = ['blue', 'red', 'green', 'orange', 'purple', 'cadetblue', 'darkred', 'darkblue', 'darkgreen']
    return colors[idx % len(colors)]

file_color_map = {}
if not st.session_state['data'].empty:
    unique_files = sorted(st.session_state['data']['source_file'].unique().tolist())
    for i, f in enumerate(unique_files):
        file_color_map[f] = get_folium_color(i)

def get_lat_lng(address):
    try:
        gl = Nominatim(user_agent="v73_geo")
        loc = gl.geocode(address, timeout=10)
        return {"lat": loc.latitude, "lng": loc.longitude} if loc else None
    except: return None

def get_math_dist(lat1, lon1, lat2, lon2): return math.sqrt((lat1-lat2)**2 + (lon1-lon2)**2)

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
                dist += r['routes'][0]['distance']; time += r['routes'][0]['duration']
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

# --- 4. SIDEBAR ---
with st.sidebar:
    st.header("🗺️ Menu")
    
    with st.expander("🚀 Pliki i Widoczność", expanded=True):
        st.markdown(f'<div class="selection-info">🏠 <b>Start:</b> {st.session_state["start_name"]}<br>🏁 <b>Meta:</b> {st.session_state["meta_name"]}</div>', unsafe_allow_html=True)
        up = st.file_uploader("Wgraj KML", type=['kml'], accept_multiple_files=True)
        if up and st.button("Wczytaj"):
            all_pts = [parse_kml(f.read().decode('utf-8'), f.name) for f in up]
            if all_pts: st.session_state['data'] = pd.concat(all_pts, ignore_index=True); st.rerun()
        
        filtered_df = st.session_state['data']
        if not st.session_state['data'].empty:
            u_files = sorted(st.session_state['data']['source_file'].unique().tolist())
            v_files = st.multiselect("Widoczne rejony:", u_files, default=u_files)
            filtered_df = st.session_state['data'][st.session_state['data']['source_file'].isin(v_files)]

    with st.expander("📍 Bazy", expanded=True):
        if st.session_state['saved_locations']:
            sel_b = st.selectbox("Wybierz bazę:", ["---"] + list(st.session_state['saved_locations'].keys()))
            if sel_b != "---":
                addr = st.session_state['saved_locations'][sel_b]
                c1, c2, c3 = st.columns([1, 1, 0.5])
                with c1:
                    if st.button("Ustaw\nStart", key="s_btn", type="primary" if st.session_state['start_name']==sel_b else "secondary"):
                        st.session_state.update({'start_name': sel_b, 'start_coords': get_lat_lng(addr)}); st.rerun()
                with c2:
                    if st.button("Ustaw\nMetę", key="m_btn", type="primary" if st.session_state['meta_name']==sel_b else "secondary"):
                        st.session_state.update({'meta_name': sel_b, 'meta_coords': get_lat_lng(addr)}); st.rerun()
                with c3:
                    if st.button("🗑️", key="del_loc"): del st.session_state['saved_locations'][sel_b]; save_to_disk(); st.rerun()
        with st.form("new_b", clear_on_submit=True):
            n, a = st.text_input("Nazwa:"), st.text_input("Adres:")
            if st.form_submit_button("Dodaj bazę"): st.session_state['saved_locations'][n] = a; save_to_disk(); st.rerun()

    # --- PRZYWRÓCONA SEKCJA PROJEKTÓW ---
    with st.expander("📁 Projekty", expanded=False):
        p_name = st.text_input("Nazwa projektu:")
        if st.button("💾 Zapisz Projekt") and p_name:
            st.session_state['projects'][p_name] = {
                'data': st.session_state['data'].copy(), 'start_name': st.session_state['start_name'], 'meta_name': st.session_state['meta_name'],
                'start_coords': st.session_state['start_coords'], 'meta_coords': st.session_state['meta_coords'],
                'optimized_list': st.session_state['optimized_list'], 'geometries': st.session_state['geometries'],
                'total_dist': st.session_state['total_dist'], 'total_time': st.session_state['total_time']
            }
            save_to_disk(); st.toast("Zapisano projekt!")
        
        if st.session_state['projects']:
            st.divider()
            sel_p = st.selectbox("Wczytaj projekt:", ["---"] + list(st.session_state['projects'].keys()))
            if sel_p != "---":
                col_load, col_del = st.columns([2, 1])
                if col_load.button("Otwórz"): st.session_state.update(st.session_state['projects'][sel_p]); st.rerun()
                if col_del.button("🗑️", key="del_proj"): del st.session_state['projects'][sel_p]; save_to_disk(); st.rerun()

    st.button("🔓 WYLOGUJ", on_click=lambda: st.session_state.update({'authenticated': False}))

# --- 5. PANEL GŁÓWNY ---
st.title("🗺️ Optymalizator")
sc, mc = st.session_state['start_coords'], st.session_state['meta_coords']

if not filtered_df.empty or sc:
    mode = st.radio("Tryb pracy:", ["Jedna trasa zbiorcza", "Oddzielne trasy dla plików"], horizontal=True)
    
    if st.button("🚀 OBLICZ TRASY", type="primary", use_container_width=True):
        if not (sc and mc): st.error("Wybierz Start i Metę!")
        else:
            with st.spinner("Przeliczanie..."):
                st.session_state.update({'optimized_list': [], 'geometries': [], 'total_dist': 0, 'total_time': 0})
                groups = [filtered_df] if mode == "Jedna trasa zbiorcza" else [filtered_df[filtered_df['source_file'] == f] for f in filtered_df['source_file'].unique()]
                for i, group in enumerate(groups):
                    curr = {"lat": sc['lat'], "lng": sc['lng'], "display_name": "START", "source_file": "Baza"}
                    route, unv = [curr], group.to_dict('records')
                    while unv:
                        nxt = min(unv, key=lambda x: get_math_dist(curr['lat'], curr['lng'], x['lat'], x['lng']))
                        route.append(nxt); curr = nxt; unv.remove(nxt)
                    route.append({"lat": mc['lat'], "lng": mc['lng'], "display_name": "META", "source_file": "Baza"})
                    geom, d, t = get_route_chunked([[r['lat'], r['lng']] for r in route])
                    st.session_state['optimized_list'].append(pd.DataFrame(route))
                    st.session_state['geometries'].append({
                        "geom": geom, "color": file_color_map.get(group['source_file'].iloc[0], 'blue') if mode != "Jedna trasa zbiorcza" else 'blue', 
                        "dist": d, "time": t, "pts_count": len(group), "name": group['source_file'].iloc[0] if mode != "Jedna trasa zbiorcza" else "Całość"
                    })
                    st.session_state['total_dist'] += d; st.session_state['total_time'] += t
                st.rerun()

    # MAPA
    all_pts_coords = [[sc['lat'], sc['lng']]] if sc else []
    if mc: all_pts_coords.append([mc['lat'], mc['lng']])
    for _, r in filtered_df.iterrows(): all_pts_coords.append([r['lat'], r['lng']])

    m = folium.Map()
    if all_pts_coords: m.fit_bounds(all_pts_coords)
    else: m.location = [52.2, 19.2]; m.zoom_start = 6

    if sc: folium.Marker([sc['lat'], sc['lng']], icon=folium.Icon(color='green', icon='home', prefix='fa')).add_to(m)
    if mc: folium.Marker([mc['lat'], mc['lng']], icon=folium.Icon(color='red', icon='flag', prefix='fa')).add_to(m)
    for g in st.session_state['geometries']:
        folium.PolyLine([[c[1], c[0]] for c in g['geom']], color=g['color'], weight=5, opacity=0.7).add_to(m)
    for _, r in filtered_df.iterrows():
        color = file_color_map.get(r['source_file'], 'gray')
        folium.Marker([r['lat'], r['lng']], icon=folium.Icon(color=color, icon='circle', prefix='fa'), tooltip=r['display_name']).add_to(m)
    
    st_folium(m, width="100%", height=550, key="map_v73")

    # SEKCJA WYNIKÓW
    if st.session_state['geometries']:
        st.markdown("### 📊 Wyniki Trasy")
        cols = st.columns(min(len(st.session_state['geometries']), 4))
        for idx, g in enumerate(st.session_state['geometries']):
            with cols[idx % 4]:
                st.markdown(f"""
                <div class="stats-card">
                    <span style="color:{g['color']}; font-size: 20px;">📍</span> <b>Trasa {idx+1}</b><br>
                    <small>{g['name']}</small><br>
                    <b>Dystans: {g['dist']/1000:.2f} km</b><br>
                    Czas: {int(g['time']//3600)}h {int((g['time']%3600)//60)}min<br>
                    Punkty: {g['pts_count']}
                </div>
                """, unsafe_allow_html=True)
        
        st.markdown(f"""
        <div class="stats-card route-sum">
            🌍 ŁĄCZNIE: {st.session_state['total_dist']/1000:.2f} km | {int(st.session_state['total_time']//3600)}h {int((st.session_state['total_time']%3600)//60)}min
        </div>
        """, unsafe_allow_html=True)

    # TABELE
    if st.session_state['optimized_list']:
        st.markdown("### 📋 Szczegółowy Plan")
        for i, opt_df in enumerate(st.session_state['optimized_list']):
            with st.expander(f"Tabela przystanków - Trasa {i+1}", expanded=False):
                st.table(opt_df[['display_name', 'source_file']])
else:
    st.info("👈 Wczytaj KML i wybierz bazy.")import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
import re, math, json, requests, os

# --- 1. ZAPIS I LOGOWANIE ---
STORAGE_FILE = "data_storage.json"
def save_to_disk():
    data = {
        "saved_locations": st.session_state['saved_locations'], 
        "projects": {k: {**v, "data": v["data"].to_dict()} for k, v in st.session_state['projects'].items()}
    }
    with open(STORAGE_FILE, "w", encoding="utf-8") as f: 
        json.dump(data, f, ensure_ascii=False, indent=4)

def load_from_disk():
    if os.path.exists(STORAGE_FILE):
        try:
            with open(STORAGE_FILE, "r", encoding="utf-8") as f:
                s = json.load(f)
                st.session_state['saved_locations'] = s.get("saved_locations", {})
                st.session_state['projects'] = {
                    k: {**v, "data": pd.DataFrame(v["data"])} for k, v in s.get("projects", {}).items()
                }
        except: pass

if 'authenticated' not in st.session_state: st.session_state['authenticated'] = False
def check_password():
    if st.session_state['authenticated']: return True
    st.set_page_config(page_title="Optymalizator v73", page_icon="📍", layout="wide")
    st.title("🔐 Logowanie")
    with st.form("login"):
        p = st.text_input("Hasło:", type="password")
        if st.form_submit_button("Zaloguj"):
            if "password" in st.secrets and p == st.secrets["password"]:
                st.session_state['authenticated'] = True; load_from_disk(); st.rerun()
            else: st.error("❌ Błędne hasło")
    return False

# Inicjalizacja sesji
for key in ['data', 'optimized_list', 'saved_locations', 'projects', 'start_coords', 'meta_coords', 'total_dist', 'total_time', 'geometries']:
    if key not in st.session_state: 
        st.session_state[key] = pd.DataFrame() if key == 'data' else ([] if key in ['optimized_list', 'geometries'] else ({} if key in ['saved_locations', 'projects'] else None))
if 'start_name' not in st.session_state: st.session_state.update({'start_name': "Nie wybrano", 'meta_name': "Nie wybrano"})

if not check_password(): st.stop()

# --- 2. STYLE CSS ---
st.markdown("""
<style>
    div.stButton > button { height: 50px; width: 100%; font-size: 16px !important; border-radius: 10px; }
    .selection-info { background-color: rgba(0,0,0,0.05); padding: 12px; border-radius: 8px; border-left: 5px solid #4285f4; margin-bottom: 15px; font-size: 14px; }
    .stats-card { background-color: rgba(0,0,0,0.03); padding: 15px; border-radius: 10px; border: 1px solid rgba(0,0,0,0.1); margin-bottom: 20px; color: inherit; }
    .route-sum { font-weight: bold; font-size: 18px; border-top: 2px solid #28a745; padding-top: 10px; margin-top: 10px; }
    button[kind="primary"] { background-color: #28a745 !important; color: white !important; }
</style>
""", unsafe_allow_html=True)

# --- 3. LOGIKA I POMOCNICZE ---
def get_folium_color(idx):
    colors = ['blue', 'red', 'green', 'orange', 'purple', 'cadetblue', 'darkred', 'darkblue', 'darkgreen']
    return colors[idx % len(colors)]

file_color_map = {}
if not st.session_state['data'].empty:
    unique_files = sorted(st.session_state['data']['source_file'].unique().tolist())
    for i, f in enumerate(unique_files):
        file_color_map[f] = get_folium_color(i)

def get_lat_lng(address):
    try:
        gl = Nominatim(user_agent="v73_geo")
        loc = gl.geocode(address, timeout=10)
        return {"lat": loc.latitude, "lng": loc.longitude} if loc else None
    except: return None

def get_math_dist(lat1, lon1, lat2, lon2): return math.sqrt((lat1-lat2)**2 + (lon1-lon2)**2)

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
                dist += r['routes'][0]['distance']; time += r['routes'][0]['duration']
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

# --- 4. SIDEBAR ---
with st.sidebar:
    st.header("🗺️ Menu")
    
    with st.expander("🚀 Pliki i Widoczność", expanded=True):
        st.markdown(f'<div class="selection-info">🏠 <b>Start:</b> {st.session_state["start_name"]}<br>🏁 <b>Meta:</b> {st.session_state["meta_name"]}</div>', unsafe_allow_html=True)
        up = st.file_uploader("Wgraj KML", type=['kml'], accept_multiple_files=True)
        if up and st.button("Wczytaj"):
            all_pts = [parse_kml(f.read().decode('utf-8'), f.name) for f in up]
            if all_pts: st.session_state['data'] = pd.concat(all_pts, ignore_index=True); st.rerun()
        
        filtered_df = st.session_state['data']
        if not st.session_state['data'].empty:
            u_files = sorted(st.session_state['data']['source_file'].unique().tolist())
            v_files = st.multiselect("Widoczne rejony:", u_files, default=u_files)
            filtered_df = st.session_state['data'][st.session_state['data']['source_file'].isin(v_files)]

    with st.expander("📍 Bazy", expanded=True):
        if st.session_state['saved_locations']:
            sel_b = st.selectbox("Wybierz bazę:", ["---"] + list(st.session_state['saved_locations'].keys()))
            if sel_b != "---":
                addr = st.session_state['saved_locations'][sel_b]
                c1, c2, c3 = st.columns([1, 1, 0.5])
                with c1:
                    if st.button("Ustaw\nStart", key="s_btn", type="primary" if st.session_state['start_name']==sel_b else "secondary"):
                        st.session_state.update({'start_name': sel_b, 'start_coords': get_lat_lng(addr)}); st.rerun()
                with c2:
                    if st.button("Ustaw\nMetę", key="m_btn", type="primary" if st.session_state['meta_name']==sel_b else "secondary"):
                        st.session_state.update({'meta_name': sel_b, 'meta_coords': get_lat_lng(addr)}); st.rerun()
                with c3:
                    if st.button("🗑️", key="del_loc"): del st.session_state['saved_locations'][sel_b]; save_to_disk(); st.rerun()
        with st.form("new_b", clear_on_submit=True):
            n, a = st.text_input("Nazwa:"), st.text_input("Adres:")
            if st.form_submit_button("Dodaj bazę"): st.session_state['saved_locations'][n] = a; save_to_disk(); st.rerun()

    # --- PRZYWRÓCONA SEKCJA PROJEKTÓW ---
    with st.expander("📁 Projekty", expanded=False):
        p_name = st.text_input("Nazwa projektu:")
        if st.button("💾 Zapisz Projekt") and p_name:
            st.session_state['projects'][p_name] = {
                'data': st.session_state['data'].copy(), 'start_name': st.session_state['start_name'], 'meta_name': st.session_state['meta_name'],
                'start_coords': st.session_state['start_coords'], 'meta_coords': st.session_state['meta_coords'],
                'optimized_list': st.session_state['optimized_list'], 'geometries': st.session_state['geometries'],
                'total_dist': st.session_state['total_dist'], 'total_time': st.session_state['total_time']
            }
            save_to_disk(); st.toast("Zapisano projekt!")
        
        if st.session_state['projects']:
            st.divider()
            sel_p = st.selectbox("Wczytaj projekt:", ["---"] + list(st.session_state['projects'].keys()))
            if sel_p != "---":
                col_load, col_del = st.columns([2, 1])
                if col_load.button("Otwórz"): st.session_state.update(st.session_state['projects'][sel_p]); st.rerun()
                if col_del.button("🗑️", key="del_proj"): del st.session_state['projects'][sel_p]; save_to_disk(); st.rerun()

    st.button("🔓 WYLOGUJ", on_click=lambda: st.session_state.update({'authenticated': False}))

# --- 5. PANEL GŁÓWNY ---
st.title("🗺️ Optymalizator")
sc, mc = st.session_state['start_coords'], st.session_state['meta_coords']

if not filtered_df.empty or sc:
    mode = st.radio("Tryb pracy:", ["Jedna trasa zbiorcza", "Oddzielne trasy dla plików"], horizontal=True)
    
    if st.button("🚀 OBLICZ TRASY", type="primary", use_container_width=True):
        if not (sc and mc): st.error("Wybierz Start i Metę!")
        else:
            with st.spinner("Przeliczanie..."):
                st.session_state.update({'optimized_list': [], 'geometries': [], 'total_dist': 0, 'total_time': 0})
                groups = [filtered_df] if mode == "Jedna trasa zbiorcza" else [filtered_df[filtered_df['source_file'] == f] for f in filtered_df['source_file'].unique()]
                for i, group in enumerate(groups):
                    curr = {"lat": sc['lat'], "lng": sc['lng'], "display_name": "START", "source_file": "Baza"}
                    route, unv = [curr], group.to_dict('records')
                    while unv:
                        nxt = min(unv, key=lambda x: get_math_dist(curr['lat'], curr['lng'], x['lat'], x['lng']))
                        route.append(nxt); curr = nxt; unv.remove(nxt)
                    route.append({"lat": mc['lat'], "lng": mc['lng'], "display_name": "META", "source_file": "Baza"})
                    geom, d, t = get_route_chunked([[r['lat'], r['lng']] for r in route])
                    st.session_state['optimized_list'].append(pd.DataFrame(route))
                    st.session_state['geometries'].append({
                        "geom": geom, "color": file_color_map.get(group['source_file'].iloc[0], 'blue') if mode != "Jedna trasa zbiorcza" else 'blue', 
                        "dist": d, "time": t, "pts_count": len(group), "name": group['source_file'].iloc[0] if mode != "Jedna trasa zbiorcza" else "Całość"
                    })
                    st.session_state['total_dist'] += d; st.session_state['total_time'] += t
                st.rerun()

    # MAPA
    all_pts_coords = [[sc['lat'], sc['lng']]] if sc else []
    if mc: all_pts_coords.append([mc['lat'], mc['lng']])
    for _, r in filtered_df.iterrows(): all_pts_coords.append([r['lat'], r['lng']])

    m = folium.Map()
    if all_pts_coords: m.fit_bounds(all_pts_coords)
    else: m.location = [52.2, 19.2]; m.zoom_start = 6

    if sc: folium.Marker([sc['lat'], sc['lng']], icon=folium.Icon(color='green', icon='home', prefix='fa')).add_to(m)
    if mc: folium.Marker([mc['lat'], mc['lng']], icon=folium.Icon(color='red', icon='flag', prefix='fa')).add_to(m)
    for g in st.session_state['geometries']:
        folium.PolyLine([[c[1], c[0]] for c in g['geom']], color=g['color'], weight=5, opacity=0.7).add_to(m)
    for _, r in filtered_df.iterrows():
        color = file_color_map.get(r['source_file'], 'gray')
        folium.Marker([r['lat'], r['lng']], icon=folium.Icon(color=color, icon='circle', prefix='fa'), tooltip=r['display_name']).add_to(m)
    
    st_folium(m, width="100%", height=550, key="map_v73")

    # SEKCJA WYNIKÓW
    if st.session_state['geometries']:
        st.markdown("### 📊 Wyniki Trasy")
        cols = st.columns(min(len(st.session_state['geometries']), 4))
        for idx, g in enumerate(st.session_state['geometries']):
            with cols[idx % 4]:
                st.markdown(f"""
                <div class="stats-card">
                    <span style="color:{g['color']}; font-size: 20px;">📍</span> <b>Trasa {idx+1}</b><br>
                    <small>{g['name']}</small><br>
                    <b>Dystans: {g['dist']/1000:.2f} km</b><br>
                    Czas: {int(g['time']//3600)}h {int((g['time']%3600)//60)}min<br>
                    Punkty: {g['pts_count']}
                </div>
                """, unsafe_allow_html=True)
        
        st.markdown(f"""
        <div class="stats-card route-sum">
            🌍 ŁĄCZNIE: {st.session_state['total_dist']/1000:.2f} km | {int(st.session_state['total_time']//3600)}h {int((st.session_state['total_time']%3600)//60)}min
        </div>
        """, unsafe_allow_html=True)

    # TABELE
    if st.session_state['optimized_list']:
        st.markdown("### 📋 Szczegółowy Plan")
        for i, opt_df in enumerate(st.session_state['optimized_list']):
            with st.expander(f"Tabela przystanków - Trasa {i+1}", expanded=False):
                st.table(opt_df[['display_name', 'source_file']])
else:
    st.info("👈 Wczytaj KML i wybierz bazy.")import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
import re, math, json, requests, os

# --- 1. ZAPIS I LOGOWANIE ---
STORAGE_FILE = "data_storage.json"
def save_to_disk():
    data = {
        "saved_locations": st.session_state['saved_locations'], 
        "projects": {k: {**v, "data": v["data"].to_dict()} for k, v in st.session_state['projects'].items()}
    }
    with open(STORAGE_FILE, "w", encoding="utf-8") as f: 
        json.dump(data, f, ensure_ascii=False, indent=4)

def load_from_disk():
    if os.path.exists(STORAGE_FILE):
        try:
            with open(STORAGE_FILE, "r", encoding="utf-8") as f:
                s = json.load(f)
                st.session_state['saved_locations'] = s.get("saved_locations", {})
                st.session_state['projects'] = {
                    k: {**v, "data": pd.DataFrame(v["data"])} for k, v in s.get("projects", {}).items()
                }
        except: pass

if 'authenticated' not in st.session_state: st.session_state['authenticated'] = False
def check_password():
    if st.session_state['authenticated']: return True
    st.set_page_config(page_title="Optymalizator v73", page_icon="📍", layout="wide")
    st.title("🔐 Logowanie")
    with st.form("login"):
        p = st.text_input("Hasło:", type="password")
        if st.form_submit_button("Zaloguj"):
            if "password" in st.secrets and p == st.secrets["password"]:
                st.session_state['authenticated'] = True; load_from_disk(); st.rerun()
            else: st.error("❌ Błędne hasło")
    return False

# Inicjalizacja sesji
for key in ['data', 'optimized_list', 'saved_locations', 'projects', 'start_coords', 'meta_coords', 'total_dist', 'total_time', 'geometries']:
    if key not in st.session_state: 
        st.session_state[key] = pd.DataFrame() if key == 'data' else ([] if key in ['optimized_list', 'geometries'] else ({} if key in ['saved_locations', 'projects'] else None))
if 'start_name' not in st.session_state: st.session_state.update({'start_name': "Nie wybrano", 'meta_name': "Nie wybrano"})

if not check_password(): st.stop()

# --- 2. STYLE CSS ---
st.markdown("""
<style>
    div.stButton > button { height: 50px; width: 100%; font-size: 16px !important; border-radius: 10px; }
    .selection-info { background-color: rgba(0,0,0,0.05); padding: 12px; border-radius: 8px; border-left: 5px solid #4285f4; margin-bottom: 15px; font-size: 14px; }
    .stats-card { background-color: rgba(0,0,0,0.03); padding: 15px; border-radius: 10px; border: 1px solid rgba(0,0,0,0.1); margin-bottom: 20px; color: inherit; }
    .route-sum { font-weight: bold; font-size: 18px; border-top: 2px solid #28a745; padding-top: 10px; margin-top: 10px; }
    button[kind="primary"] { background-color: #28a745 !important; color: white !important; }
</style>
""", unsafe_allow_html=True)

# --- 3. LOGIKA I POMOCNICZE ---
def get_folium_color(idx):
    colors = ['blue', 'red', 'green', 'orange', 'purple', 'cadetblue', 'darkred', 'darkblue', 'darkgreen']
    return colors[idx % len(colors)]

file_color_map = {}
if not st.session_state['data'].empty:
    unique_files = sorted(st.session_state['data']['source_file'].unique().tolist())
    for i, f in enumerate(unique_files):
        file_color_map[f] = get_folium_color(i)

def get_lat_lng(address):
    try:
        gl = Nominatim(user_agent="v73_geo")
        loc = gl.geocode(address, timeout=10)
        return {"lat": loc.latitude, "lng": loc.longitude} if loc else None
    except: return None

def get_math_dist(lat1, lon1, lat2, lon2): return math.sqrt((lat1-lat2)**2 + (lon1-lon2)**2)

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
                dist += r['routes'][0]['distance']; time += r['routes'][0]['duration']
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

# --- 4. SIDEBAR ---
with st.sidebar:
    st.header("🗺️ Menu")
    
    with st.expander("🚀 Pliki i Widoczność", expanded=True):
        st.markdown(f'<div class="selection-info">🏠 <b>Start:</b> {st.session_state["start_name"]}<br>🏁 <b>Meta:</b> {st.session_state["meta_name"]}</div>', unsafe_allow_html=True)
        up = st.file_uploader("Wgraj KML", type=['kml'], accept_multiple_files=True)
        if up and st.button("Wczytaj"):
            all_pts = [parse_kml(f.read().decode('utf-8'), f.name) for f in up]
            if all_pts: st.session_state['data'] = pd.concat(all_pts, ignore_index=True); st.rerun()
        
        filtered_df = st.session_state['data']
        if not st.session_state['data'].empty:
            u_files = sorted(st.session_state['data']['source_file'].unique().tolist())
            v_files = st.multiselect("Widoczne rejony:", u_files, default=u_files)
            filtered_df = st.session_state['data'][st.session_state['data']['source_file'].isin(v_files)]

    with st.expander("📍 Bazy", expanded=True):
        if st.session_state['saved_locations']:
            sel_b = st.selectbox("Wybierz bazę:", ["---"] + list(st.session_state['saved_locations'].keys()))
            if sel_b != "---":
                addr = st.session_state['saved_locations'][sel_b]
                c1, c2, c3 = st.columns([1, 1, 0.5])
                with c1:
                    if st.button("Ustaw\nStart", key="s_btn", type="primary" if st.session_state['start_name']==sel_b else "secondary"):
                        st.session_state.update({'start_name': sel_b, 'start_coords': get_lat_lng(addr)}); st.rerun()
                with c2:
                    if st.button("Ustaw\nMetę", key="m_btn", type="primary" if st.session_state['meta_name']==sel_b else "secondary"):
                        st.session_state.update({'meta_name': sel_b, 'meta_coords': get_lat_lng(addr)}); st.rerun()
                with c3:
                    if st.button("🗑️", key="del_loc"): del st.session_state['saved_locations'][sel_b]; save_to_disk(); st.rerun()
        with st.form("new_b", clear_on_submit=True):
            n, a = st.text_input("Nazwa:"), st.text_input("Adres:")
            if st.form_submit_button("Dodaj bazę"): st.session_state['saved_locations'][n] = a; save_to_disk(); st.rerun()

    # --- PRZYWRÓCONA SEKCJA PROJEKTÓW ---
    with st.expander("📁 Projekty", expanded=False):
        p_name = st.text_input("Nazwa projektu:")
        if st.button("💾 Zapisz Projekt") and p_name:
            st.session_state['projects'][p_name] = {
                'data': st.session_state['data'].copy(), 'start_name': st.session_state['start_name'], 'meta_name': st.session_state['meta_name'],
                'start_coords': st.session_state['start_coords'], 'meta_coords': st.session_state['meta_coords'],
                'optimized_list': st.session_state['optimized_list'], 'geometries': st.session_state['geometries'],
                'total_dist': st.session_state['total_dist'], 'total_time': st.session_state['total_time']
            }
            save_to_disk(); st.toast("Zapisano projekt!")
        
        if st.session_state['projects']:
            st.divider()
            sel_p = st.selectbox("Wczytaj projekt:", ["---"] + list(st.session_state['projects'].keys()))
            if sel_p != "---":
                col_load, col_del = st.columns([2, 1])
                if col_load.button("Otwórz"): st.session_state.update(st.session_state['projects'][sel_p]); st.rerun()
                if col_del.button("🗑️", key="del_proj"): del st.session_state['projects'][sel_p]; save_to_disk(); st.rerun()

    st.button("🔓 WYLOGUJ", on_click=lambda: st.session_state.update({'authenticated': False}))

# --- 5. PANEL GŁÓWNY ---
st.title("🗺️ Optymalizator")
sc, mc = st.session_state['start_coords'], st.session_state['meta_coords']

if not filtered_df.empty or sc:
    mode = st.radio("Tryb pracy:", ["Jedna trasa zbiorcza", "Oddzielne trasy dla plików"], horizontal=True)
    
    if st.button("🚀 OBLICZ TRASY", type="primary", use_container_width=True):
        if not (sc and mc): st.error("Wybierz Start i Metę!")
        else:
            with st.spinner("Przeliczanie..."):
                st.session_state.update({'optimized_list': [], 'geometries': [], 'total_dist': 0, 'total_time': 0})
                groups = [filtered_df] if mode == "Jedna trasa zbiorcza" else [filtered_df[filtered_df['source_file'] == f] for f in filtered_df['source_file'].unique()]
                for i, group in enumerate(groups):
                    curr = {"lat": sc['lat'], "lng": sc['lng'], "display_name": "START", "source_file": "Baza"}
                    route, unv = [curr], group.to_dict('records')
                    while unv:
                        nxt = min(unv, key=lambda x: get_math_dist(curr['lat'], curr['lng'], x['lat'], x['lng']))
                        route.append(nxt); curr = nxt; unv.remove(nxt)
                    route.append({"lat": mc['lat'], "lng": mc['lng'], "display_name": "META", "source_file": "Baza"})
                    geom, d, t = get_route_chunked([[r['lat'], r['lng']] for r in route])
                    st.session_state['optimized_list'].append(pd.DataFrame(route))
                    st.session_state['geometries'].append({
                        "geom": geom, "color": file_color_map.get(group['source_file'].iloc[0], 'blue') if mode != "Jedna trasa zbiorcza" else 'blue', 
                        "dist": d, "time": t, "pts_count": len(group), "name": group['source_file'].iloc[0] if mode != "Jedna trasa zbiorcza" else "Całość"
                    })
                    st.session_state['total_dist'] += d; st.session_state['total_time'] += t
                st.rerun()

    # MAPA
    all_pts_coords = [[sc['lat'], sc['lng']]] if sc else []
    if mc: all_pts_coords.append([mc['lat'], mc['lng']])
    for _, r in filtered_df.iterrows(): all_pts_coords.append([r['lat'], r['lng']])

    m = folium.Map()
    if all_pts_coords: m.fit_bounds(all_pts_coords)
    else: m.location = [52.2, 19.2]; m.zoom_start = 6

    if sc: folium.Marker([sc['lat'], sc['lng']], icon=folium.Icon(color='green', icon='home', prefix='fa')).add_to(m)
    if mc: folium.Marker([mc['lat'], mc['lng']], icon=folium.Icon(color='red', icon='flag', prefix='fa')).add_to(m)
    for g in st.session_state['geometries']:
        folium.PolyLine([[c[1], c[0]] for c in g['geom']], color=g['color'], weight=5, opacity=0.7).add_to(m)
    for _, r in filtered_df.iterrows():
        color = file_color_map.get(r['source_file'], 'gray')
        folium.Marker([r['lat'], r['lng']], icon=folium.Icon(color=color, icon='circle', prefix='fa'), tooltip=r['display_name']).add_to(m)
    
    st_folium(m, width="100%", height=550, key="map_v73")

    # SEKCJA WYNIKÓW
    if st.session_state['geometries']:
        st.markdown("### 📊 Wyniki Trasy")
        cols = st.columns(min(len(st.session_state['geometries']), 4))
        for idx, g in enumerate(st.session_state['geometries']):
            with cols[idx % 4]:
                st.markdown(f"""
                <div class="stats-card">
                    <span style="color:{g['color']}; font-size: 20px;">📍</span> <b>Trasa {idx+1}</b><br>
                    <small>{g['name']}</small><br>
                    <b>Dystans: {g['dist']/1000:.2f} km</b><br>
                    Czas: {int(g['time']//3600)}h {int((g['time']%3600)//60)}min<br>
                    Punkty: {g['pts_count']}
                </div>
                """, unsafe_allow_html=True)
        
        st.markdown(f"""
        <div class="stats-card route-sum">
            🌍 ŁĄCZNIE: {st.session_state['total_dist']/1000:.2f} km | {int(st.session_state['total_time']//3600)}h {int((st.session_state['total_time']%3600)//60)}min
        </div>
        """, unsafe_allow_html=True)

    # TABELE
    if st.session_state['optimized_list']:
        st.markdown("### 📋 Szczegółowy Plan")
        for i, opt_df in enumerate(st.session_state['optimized_list']):
            with st.expander(f"Tabela przystanków - Trasa {i+1}", expanded=False):
                st.table(opt_df[['display_name', 'source_file']])
else:
    st.info("👈 Wczytaj KML i wybierz bazy.")import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
import re, math, json, requests, os

# --- 1. ZAPIS I LOGOWANIE ---
STORAGE_FILE = "data_storage.json"
def save_to_disk():
    data = {
        "saved_locations": st.session_state['saved_locations'], 
        "projects": {k: {**v, "data": v["data"].to_dict()} for k, v in st.session_state['projects'].items()}
    }
    with open(STORAGE_FILE, "w", encoding="utf-8") as f: 
        json.dump(data, f, ensure_ascii=False, indent=4)

def load_from_disk():
    if os.path.exists(STORAGE_FILE):
        try:
            with open(STORAGE_FILE, "r", encoding="utf-8") as f:
                s = json.load(f)
                st.session_state['saved_locations'] = s.get("saved_locations", {})
                st.session_state['projects'] = {
                    k: {**v, "data": pd.DataFrame(v["data"])} for k, v in s.get("projects", {}).items()
                }
        except: pass

if 'authenticated' not in st.session_state: st.session_state['authenticated'] = False
def check_password():
    if st.session_state['authenticated']: return True
    st.set_page_config(page_title="Optymalizator v73", page_icon="📍", layout="wide")
    st.title("🔐 Logowanie")
    with st.form("login"):
        p = st.text_input("Hasło:", type="password")
        if st.form_submit_button("Zaloguj"):
            if "password" in st.secrets and p == st.secrets["password"]:
                st.session_state['authenticated'] = True; load_from_disk(); st.rerun()
            else: st.error("❌ Błędne hasło")
    return False

# Inicjalizacja sesji
for key in ['data', 'optimized_list', 'saved_locations', 'projects', 'start_coords', 'meta_coords', 'total_dist', 'total_time', 'geometries']:
    if key not in st.session_state: 
        st.session_state[key] = pd.DataFrame() if key == 'data' else ([] if key in ['optimized_list', 'geometries'] else ({} if key in ['saved_locations', 'projects'] else None))
if 'start_name' not in st.session_state: st.session_state.update({'start_name': "Nie wybrano", 'meta_name': "Nie wybrano"})

if not check_password(): st.stop()

# --- 2. STYLE CSS ---
st.markdown("""
<style>
    div.stButton > button { height: 50px; width: 100%; font-size: 16px !important; border-radius: 10px; }
    .selection-info { background-color: rgba(0,0,0,0.05); padding: 12px; border-radius: 8px; border-left: 5px solid #4285f4; margin-bottom: 15px; font-size: 14px; }
    .stats-card { background-color: rgba(0,0,0,0.03); padding: 15px; border-radius: 10px; border: 1px solid rgba(0,0,0,0.1); margin-bottom: 20px; color: inherit; }
    .route-sum { font-weight: bold; font-size: 18px; border-top: 2px solid #28a745; padding-top: 10px; margin-top: 10px; }
    button[kind="primary"] { background-color: #28a745 !important; color: white !important; }
</style>
""", unsafe_allow_html=True)

# --- 3. LOGIKA I POMOCNICZE ---
def get_folium_color(idx):
    colors = ['blue', 'red', 'green', 'orange', 'purple', 'cadetblue', 'darkred', 'darkblue', 'darkgreen']
    return colors[idx % len(colors)]

file_color_map = {}
if not st.session_state['data'].empty:
    unique_files = sorted(st.session_state['data']['source_file'].unique().tolist())
    for i, f in enumerate(unique_files):
        file_color_map[f] = get_folium_color(i)

def get_lat_lng(address):
    try:
        gl = Nominatim(user_agent="v73_geo")
        loc = gl.geocode(address, timeout=10)
        return {"lat": loc.latitude, "lng": loc.longitude} if loc else None
    except: return None

def get_math_dist(lat1, lon1, lat2, lon2): return math.sqrt((lat1-lat2)**2 + (lon1-lon2)**2)

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
                dist += r['routes'][0]['distance']; time += r['routes'][0]['duration']
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

# --- 4. SIDEBAR ---
with st.sidebar:
    st.header("🗺️ Menu")
    
    with st.expander("🚀 Pliki i Widoczność", expanded=True):
        st.markdown(f'<div class="selection-info">🏠 <b>Start:</b> {st.session_state["start_name"]}<br>🏁 <b>Meta:</b> {st.session_state["meta_name"]}</div>', unsafe_allow_html=True)
        up = st.file_uploader("Wgraj KML", type=['kml'], accept_multiple_files=True)
        if up and st.button("Wczytaj"):
            all_pts = [parse_kml(f.read().decode('utf-8'), f.name) for f in up]
            if all_pts: st.session_state['data'] = pd.concat(all_pts, ignore_index=True); st.rerun()
        
        filtered_df = st.session_state['data']
        if not st.session_state['data'].empty:
            u_files = sorted(st.session_state['data']['source_file'].unique().tolist())
            v_files = st.multiselect("Widoczne rejony:", u_files, default=u_files)
            filtered_df = st.session_state['data'][st.session_state['data']['source_file'].isin(v_files)]

    with st.expander("📍 Bazy", expanded=True):
        if st.session_state['saved_locations']:
            sel_b = st.selectbox("Wybierz bazę:", ["---"] + list(st.session_state['saved_locations'].keys()))
            if sel_b != "---":
                addr = st.session_state['saved_locations'][sel_b]
                c1, c2, c3 = st.columns([1, 1, 0.5])
                with c1:
                    if st.button("Ustaw\nStart", key="s_btn", type="primary" if st.session_state['start_name']==sel_b else "secondary"):
                        st.session_state.update({'start_name': sel_b, 'start_coords': get_lat_lng(addr)}); st.rerun()
                with c2:
                    if st.button("Ustaw\nMetę", key="m_btn", type="primary" if st.session_state['meta_name']==sel_b else "secondary"):
                        st.session_state.update({'meta_name': sel_b, 'meta_coords': get_lat_lng(addr)}); st.rerun()
                with c3:
                    if st.button("🗑️", key="del_loc"): del st.session_state['saved_locations'][sel_b]; save_to_disk(); st.rerun()
        with st.form("new_b", clear_on_submit=True):
            n, a = st.text_input("Nazwa:"), st.text_input("Adres:")
            if st.form_submit_button("Dodaj bazę"): st.session_state['saved_locations'][n] = a; save_to_disk(); st.rerun()

    # --- PRZYWRÓCONA SEKCJA PROJEKTÓW ---
    with st.expander("📁 Projekty", expanded=False):
        p_name = st.text_input("Nazwa projektu:")
        if st.button("💾 Zapisz Projekt") and p_name:
            st.session_state['projects'][p_name] = {
                'data': st.session_state['data'].copy(), 'start_name': st.session_state['start_name'], 'meta_name': st.session_state['meta_name'],
                'start_coords': st.session_state['start_coords'], 'meta_coords': st.session_state['meta_coords'],
                'optimized_list': st.session_state['optimized_list'], 'geometries': st.session_state['geometries'],
                'total_dist': st.session_state['total_dist'], 'total_time': st.session_state['total_time']
            }
            save_to_disk(); st.toast("Zapisano projekt!")
        
        if st.session_state['projects']:
            st.divider()
            sel_p = st.selectbox("Wczytaj projekt:", ["---"] + list(st.session_state['projects'].keys()))
            if sel_p != "---":
                col_load, col_del = st.columns([2, 1])
                if col_load.button("Otwórz"): st.session_state.update(st.session_state['projects'][sel_p]); st.rerun()
                if col_del.button("🗑️", key="del_proj"): del st.session_state['projects'][sel_p]; save_to_disk(); st.rerun()

    st.button("🔓 WYLOGUJ", on_click=lambda: st.session_state.update({'authenticated': False}))

# --- 5. PANEL GŁÓWNY ---
st.title("🗺️ Optymalizator")
sc, mc = st.session_state['start_coords'], st.session_state['meta_coords']

if not filtered_df.empty or sc:
    mode = st.radio("Tryb pracy:", ["Jedna trasa zbiorcza", "Oddzielne trasy dla plików"], horizontal=True)
    
    if st.button("🚀 OBLICZ TRASY", type="primary", use_container_width=True):
        if not (sc and mc): st.error("Wybierz Start i Metę!")
        else:
            with st.spinner("Przeliczanie..."):
                st.session_state.update({'optimized_list': [], 'geometries': [], 'total_dist': 0, 'total_time': 0})
                groups = [filtered_df] if mode == "Jedna trasa zbiorcza" else [filtered_df[filtered_df['source_file'] == f] for f in filtered_df['source_file'].unique()]
                for i, group in enumerate(groups):
                    curr = {"lat": sc['lat'], "lng": sc['lng'], "display_name": "START", "source_file": "Baza"}
                    route, unv = [curr], group.to_dict('records')
                    while unv:
                        nxt = min(unv, key=lambda x: get_math_dist(curr['lat'], curr['lng'], x['lat'], x['lng']))
                        route.append(nxt); curr = nxt; unv.remove(nxt)
                    route.append({"lat": mc['lat'], "lng": mc['lng'], "display_name": "META", "source_file": "Baza"})
                    geom, d, t = get_route_chunked([[r['lat'], r['lng']] for r in route])
                    st.session_state['optimized_list'].append(pd.DataFrame(route))
                    st.session_state['geometries'].append({
                        "geom": geom, "color": file_color_map.get(group['source_file'].iloc[0], 'blue') if mode != "Jedna trasa zbiorcza" else 'blue', 
                        "dist": d, "time": t, "pts_count": len(group), "name": group['source_file'].iloc[0] if mode != "Jedna trasa zbiorcza" else "Całość"
                    })
                    st.session_state['total_dist'] += d; st.session_state['total_time'] += t
                st.rerun()

    # MAPA
    all_pts_coords = [[sc['lat'], sc['lng']]] if sc else []
    if mc: all_pts_coords.append([mc['lat'], mc['lng']])
    for _, r in filtered_df.iterrows(): all_pts_coords.append([r['lat'], r['lng']])

    m = folium.Map()
    if all_pts_coords: m.fit_bounds(all_pts_coords)
    else: m.location = [52.2, 19.2]; m.zoom_start = 6

    if sc: folium.Marker([sc['lat'], sc['lng']], icon=folium.Icon(color='green', icon='home', prefix='fa')).add_to(m)
    if mc: folium.Marker([mc['lat'], mc['lng']], icon=folium.Icon(color='red', icon='flag', prefix='fa')).add_to(m)
    for g in st.session_state['geometries']:
        folium.PolyLine([[c[1], c[0]] for c in g['geom']], color=g['color'], weight=5, opacity=0.7).add_to(m)
    for _, r in filtered_df.iterrows():
        color = file_color_map.get(r['source_file'], 'gray')
        folium.Marker([r['lat'], r['lng']], icon=folium.Icon(color=color, icon='circle', prefix='fa'), tooltip=r['display_name']).add_to(m)
    
    st_folium(m, width="100%", height=550, key="map_v73")

    # SEKCJA WYNIKÓW
    if st.session_state['geometries']:
        st.markdown("### 📊 Wyniki Trasy")
        cols = st.columns(min(len(st.session_state['geometries']), 4))
        for idx, g in enumerate(st.session_state['geometries']):
            with cols[idx % 4]:
                st.markdown(f"""
                <div class="stats-card">
                    <span style="color:{g['color']}; font-size: 20px;">📍</span> <b>Trasa {idx+1}</b><br>
                    <small>{g['name']}</small><br>
                    <b>Dystans: {g['dist']/1000:.2f} km</b><br>
                    Czas: {int(g['time']//3600)}h {int((g['time']%3600)//60)}min<br>
                    Punkty: {g['pts_count']}
                </div>
                """, unsafe_allow_html=True)
        
        st.markdown(f"""
        <div class="stats-card route-sum">
            🌍 ŁĄCZNIE: {st.session_state['total_dist']/1000:.2f} km | {int(st.session_state['total_time']//3600)}h {int((st.session_state['total_time']%3600)//60)}min
        </div>
        """, unsafe_allow_html=True)

    # TABELE
    if st.session_state['optimized_list']:
        st.markdown("### 📋 Szczegółowy Plan")
        for i, opt_df in enumerate(st.session_state['optimized_list']):
            with st.expander(f"Tabela przystanków - Trasa {i+1}", expanded=False):
                st.table(opt_df[['display_name', 'source_file']])
else:
    st.info("👈 Wczytaj KML i wybierz bazy.")
