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
    st.set_page_config(page_title="Optymalizator v85", page_icon="📍", layout="wide")
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
    div.stButton > button { height: 40px; width: 100%; font-size: 18px !important; border-radius: 8px; margin-bottom: 5px; }
    .base-info-box { background-color: #f0f2f6; padding: 15px; border-radius: 10px; border-left: 5px solid #28a745; margin-bottom: 10px; font-size: 15px; }
    .stats-card { background-color: rgba(0,0,0,0.03); padding: 15px; border-radius: 10px; border: 1px solid rgba(0,0,0,0.1); margin-bottom: 20px; }
    .route-sum { font-weight: bold; font-size: 18px; border-top: 3px solid #28a745; padding-top: 10px; margin-top: 20px; }
    button[kind="primary"] { background-color: #28a745 !important; color: white !important; }
</style>
""", unsafe_allow_html=True)

# --- 3. LOGIKA POMOCNICZA ---
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
        gl = Nominatim(user_agent="v85_geo")
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
    st.header("⚙️ Zarządzanie")
    
    with st.expander("🚀 Wgrywanie KML", expanded=False):
        up = st.file_uploader("Dodaj pliki rejonów", type=['kml'], accept_multiple_files=True)
        if up and st.button("Wczytaj"):
            all_pts = [parse_kml(f.read().decode('utf-8'), f.name) for f in up]
            if all_pts: st.session_state['data'] = pd.concat(all_pts, ignore_index=True); st.rerun()

    with st.expander("🏠 Baza Lokalizacji", expanded=True):
        if st.session_state['saved_locations']:
            sel_b = st.selectbox("Wybierz bazę:", ["---"] + list(st.session_state['saved_locations'].keys()))
            if sel_b != "---":
                addr = st.session_state['saved_locations'][sel_b]
                c1, c2, c3 = st.columns([1, 1, 1])
                with c1:
                    is_s = st.session_state['start_name'] == sel_b
                    if st.button("🟢" if is_s else "🏠", key=f"s_{sel_b}"):
                        st.session_state.update({'start_name': sel_b, 'start_coords': get_lat_lng(addr)}); st.rerun()
                with c2:
                    is_m = st.session_state['meta_name'] == sel_b
                    if st.button("🔴" if is_m else "🏁", key=f"m_{sel_b}"):
                        st.session_state.update({'meta_name': sel_b, 'meta_coords': get_lat_lng(addr)}); st.rerun()
                with c3:
                    if st.button("🗑️", key=f"d_{sel_b}"):
                        del st.session_state['saved_locations'][sel_b]; save_to_disk(); st.rerun()
        
        st.markdown("---")
        with st.form("new_b", clear_on_submit=True):
            n, a = st.text_input("Nazwa:"), st.text_input("Adres:")
            if st.form_submit_button("➕ Dodaj"):
                if n and a: st.session_state['saved_locations'][n] = a; save_to_disk(); st.rerun()

    with st.expander("📁 Projekty", expanded=False):
        p_name = st.text_input("Zapisz jako:")
        if st.button("💾 Zapisz") and p_name:
            st.session_state['projects'][p_name] = {
                'data': st.session_state['data'].copy(), 'start_name': st.session_state['start_name'], 'meta_name': st.session_state['meta_name'],
                'start_coords': st.session_state['start_coords'], 'meta_coords': st.session_state['meta_coords'],
                'optimized_list': [df.copy() for df in st.session_state['optimized_list']], 'geometries': st.session_state['geometries']
            }
            save_to_disk(); st.success("Zapisano!")
        if st.session_state['projects']:
            sel_p = st.selectbox("Wczytaj projekt:", ["---"] + list(st.session_state['projects'].keys()))
            if sel_p != "---" and st.button("📂 Otwórz"):
                st.session_state.update(st.session_state['projects'][sel_p]); st.rerun()

    st.button("🔓 WYLOGUJ", on_click=lambda: st.session_state.update({'authenticated': False}))

# --- 5. PANEL GŁÓWNY ---
st.title("🗺️ Optymalizator Tras")

c_start, c_meta = st.columns(2)
with c_start:
    st.markdown(f'<div class="base-info-box">🏠 <b>START:</b> {st.session_state["start_name"]}</div>', unsafe_allow_html=True)
with c_meta:
    st.markdown(f'<div class="base-info-box">🏁 <b>META:</b> {st.session_state["meta_name"]}</div>', unsafe_allow_html=True)

sc, mc = st.session_state['start_coords'], st.session_state['meta_coords']

if not st.session_state['data'].empty or sc:
    col_filters, col_view = st.columns([2, 1])
    with col_filters:
        u_files = sorted(st.session_state['data']['source_file'].unique().tolist())
        v_files = st.multiselect("Rejony:", u_files, default=u_files)
        filtered_df = st.session_state['data'][st.session_state['data']['source_file'].isin(v_files)]
    
    with col_view:
        show_pins = st.checkbox("Pokaż pinezki", value=True)
        mode = st.radio("Tryb:", ["Jedna trasa", "Oddzielne"], horizontal=True)

    col_calc, col_clear = st.columns([3, 1])
    with col_calc:
        if st.button("🚀 OBLICZ TRASY", type="primary", use_container_width=True):
            if not (sc and mc): st.error("Ustaw Start i Metę!")
            else:
                with st.spinner("Przeliczanie..."):
                    st.session_state.update({'optimized_list': [], 'geometries': []})
                    groups = [filtered_df] if mode == "Jedna trasa" else [filtered_df[filtered_df['source_file'] == f] for f in filtered_df['source_file'].unique()]
                    for group in groups:
                        curr = {"lat": sc['lat'], "lng": sc['lng'], "display_name": "START", "source_file": "Baza"}
                        route, unv = [curr], group.to_dict('records')
                        while unv:
                            nxt = min(unv, key=lambda x: get_math_dist(curr['lat'], curr['lng'], x['lat'], x['lng']))
                            route.append(nxt); curr = nxt; unv.remove(nxt)
                        route.append({"lat": mc['lat'], "lng": mc['lng'], "display_name": "META", "source_file": "Baza"})
                        geom, d, t = get_route_chunked([[r['lat'], r['lng']] for r in route])
                        st.session_state['optimized_list'].append(pd.DataFrame(route))
                        st.session_state['geometries'].append({
                            "geom": geom, "color": file_color_map.get(group['source_file'].iloc[0], 'blue'), 
                            "dist": d, "time": t, "pts_count": len(group), 
                            "name": group['source_file'].iloc[0] if mode != "Jedna trasa" else "Całość",
                            "source_file": group['source_file'].iloc[0] if mode != "Jedna trasa" else "ALL"
                        })
                    st.rerun()
    with col_clear:
        if st.button("🗑️ CZYŚĆ", use_container_width=True):
            st.session_state.update({'optimized_list': [], 'geometries': []}); st.rerun()

    visible_geoms = [g for g in st.session_state['geometries'] if mode == "Jedna trasa" or g.get('source_file') in v_files]

    m = folium.Map()
    all_coords = [[sc['lat'], sc['lng']]] if sc else []
    if mc: all_coords.append([mc['lat'], mc['lng']])
    for _, r in filtered_df.iterrows(): all_coords.append([r['lat'], r['lng']])
    if all_coords: m.fit_bounds(all_coords)

    if sc: folium.Marker([sc['lat'], sc['lng']], icon=folium.Icon(color='green', icon='home', prefix='fa')).add_to(m)
    if mc: folium.Marker([mc['lat'], mc['lng']], icon=folium.Icon(color='red', icon='flag', prefix='fa')).add_to(m)
    for g in visible_geoms: folium.PolyLine([[c[1], c[0]] for c in g['geom']], color=g['color'], weight=5, opacity=0.8).add_to(m)
    if show_pins:
        for idx, r in filtered_df.iterrows():
            folium.Marker([r['lat'], r['lng']], icon=folium.Icon(color=file_color_map.get(r['source_file'], 'gray'), icon='circle', prefix='fa'), tooltip=r['display_name']).add_to(m)
    
    map_data = st_folium(m, width="100%", height=550, key="map_v85")

    if show_pins and map_data.get("last_object_clicked"):
        clat, clng = map_data["last_object_clicked"]["lat"], map_data["last_object_clicked"]["lng"]
        match = st.session_state['data'][(abs(st.session_state['data']['lat'] - clat) < 0.0001) & (abs(st.session_state['data']['lng'] - clng) < 0.0001)]
        if not match.empty:
            t_idx, t_name = match.index[0], match.iloc[0]['display_name']
            st.warning(f"Zaznaczono: {t_name}")
            if st.button(f"🗑️ USUŃ PUNKT"):
                st.session_state['data'] = st.session_state['data'].drop(t_idx).reset_index(drop=True)
                st.session_state.update({'optimized_list': [], 'geometries': []}); st.rerun()

    if visible_geoms:
        st.markdown("### 📊 Wyniki i Plan")
        cols = st.columns(min(len(visible_geoms), 4))
        total_d, total_t = 0, 0
        for idx, g in enumerate(visible_geoms):
            total_d += g['dist']; total_t += g['time']
            with cols[idx % 4]:
                st.markdown(f'<div class="stats-card"><span style="color:{g["color"]}; font-size: 20px;">●</span> <b>{g["name"]}</b><br>📏 <b>{g["dist"]/1000:.2f} km</b><br>⏱️ {int(g["time"]//3600)}h {int((g["time"]%3600)//60)}min<br>📍 Punkty: {g["pts_count"]}</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="stats-card route-sum">🌍 ŁĄCZNIE: {total_d/1000:.2f} km | {int(total_t//3600)}h {int((total_t%3600)//60)}min</div>', unsafe_allow_html=True)

        for i, opt_df in enumerate(st.session_state['optimized_list']):
            source = opt_df['source_file'].iloc[1] if len(opt_df) > 1 else "Baza"
            if mode == "Jedna trasa" or source in v_files:
                with st.expander(f"📋 Tabela: {source if mode != 'Jedna trasa' else 'Trasa Zbiorcza'}"):
                    st.table(opt_df[['display_name', 'source_file']].reset_index(drop=True))
else:
    st.info("👈 Wgraj KML i wybierz bazy.")
