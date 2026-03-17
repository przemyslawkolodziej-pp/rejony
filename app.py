import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
import re, math, json, requests, os

# --- 1. KONFIGURACJA STRONY ---
st.set_page_config(page_title="Optymalizator Tras", page_icon="🗺️", layout="wide")

STORAGE_FILE = "data_storage.json"

def save_to_disk():
    def serialize_project(obj):
        if isinstance(obj, pd.DataFrame): return obj.to_dict()
        if isinstance(obj, dict): return {k: serialize_project(v) for k, v in obj.items()}
        if isinstance(obj, list): return [serialize_project(i) for i in obj]
        return obj
    try:
        data = {
            "saved_locations": st.session_state['saved_locations'], 
            "projects": {k: serialize_project(v) for k, v in st.session_state['projects'].items()}
        }
        with open(STORAGE_FILE, "w", encoding="utf-8") as f: 
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e: st.error(f"Błąd zapisu: {e}")

def load_from_disk():
    if os.path.exists(STORAGE_FILE):
        try:
            with open(STORAGE_FILE, "r", encoding="utf-8") as f:
                s = json.load(f)
                st.session_state['saved_locations'] = s.get("saved_locations", {})
                raw_projects = s.get("projects", {})
                loaded_projects = {}
                for k, v in raw_projects.items():
                    proj = v.copy()
                    if 'data' in proj: proj['data'] = pd.DataFrame(proj['data'])
                    if 'optimized_list' in proj: proj['optimized_list'] = [pd.DataFrame(df) for df in proj['optimized_list']]
                    loaded_projects[k] = proj
                st.session_state['projects'] = loaded_projects
        except: pass

# Inicjalizacja sesji
for key in ['authenticated', 'data', 'optimized_list', 'saved_locations', 'projects', 'start_coords', 'meta_coords', 'geometries', 'reset_counter']:
    if key not in st.session_state: 
        if key == 'authenticated': st.session_state[key] = False
        elif key == 'data': st.session_state[key] = pd.DataFrame()
        elif key == 'reset_counter': st.session_state[key] = 0
        elif key in ['optimized_list', 'geometries']: st.session_state[key] = []
        elif key in ['saved_locations', 'projects']: st.session_state[key] = {}
        else: st.session_state[key] = None

if 'start_name' not in st.session_state: st.session_state.update({'start_name': "Nie wybrano", 'meta_name': "Nie wybrano"})

def check_password():
    if st.session_state['authenticated']: return True
    st.title("🔐 Logowanie")
    with st.form("login"):
        p = st.text_input("Hasło:", type="password")
        if st.form_submit_button("Zaloguj"):
            if "password" in st.secrets and p == st.secrets["password"]:
                st.session_state['authenticated'] = True; load_from_disk(); st.rerun()
            else: st.error("❌ Błędne hasło")
    return False

if not check_password(): st.stop()

# --- 2. STYLE CSS ---
st.markdown("""
<style>
    div.stButton > button { height: 40px; width: 100%; font-size: 20px !important; border-radius: 8px; margin-bottom: 5px; }
    .base-info-box { background-color: #f0f2f6; padding: 15px; border-radius: 10px; border-left: 5px solid #28a745; margin-bottom: 10px; font-size: 15px; }
    .stats-card { background-color: rgba(0,0,0,0.03); padding: 15px; border-radius: 10px; border: 1px solid rgba(0,0,0,0.1); margin-bottom: 20px; }
    .route-sum { font-weight: bold; font-size: 18px; border-top: 3px solid #28a745; padding-top: 10px; margin-top: 20px; }
    button[kind="primary"] { background-color: #28a745 !important; color: white !important; }
</style>
""", unsafe_allow_html=True)

# --- 3. LOGIKA POMOCNICZA ---
def get_folium_color(idx):
    # Paleta standardowych kolorów Folium/Leaflet
    colors = ['blue', 'red', 'green', 'orange', 'purple', 'cadetblue', 'darkred', 'darkblue', 'darkgreen', 'pink', 'lightblue', 'lightgreen']
    return colors[idx % len(colors)]

file_color_map = {}
if not st.session_state['data'].empty:
    u_files = sorted(st.session_state['data']['source_file'].unique().tolist())
    for i, f in enumerate(u_files): file_color_map[f] = get_folium_color(i)

def get_lat_lng(address):
    try:
        gl = Nominatim(user_agent="v99_geo")
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
    
    with st.expander("☁️ Wgrywanie KML", expanded=False):
        up = st.file_uploader("Dodaj pliki rejonów", type=['kml'], accept_multiple_files=True)
        if up and st.button("Wczytaj"):
            all_pts = [parse_kml(f.read().decode('utf-8'), f.name) for f in up]
            if all_pts: st.session_state['data'] = pd.concat(all_pts, ignore_index=True); st.rerun()

    with st.expander("🏠 Bazy", expanded=True):
        if st.session_state['saved_locations']:
            sorted_locs = sorted(st.session_state['saved_locations'].keys())
            sel_b = st.selectbox("Wybierz bazę:", ["---"] + sorted_locs)
            if sel_b != "---":
                addr = st.session_state['saved_locations'][sel_b]
                c1, c2, c3 = st.columns([1, 1, 1])
                with c1:
                    if st.button("🏠", key=f"s_{sel_b}"):
                        st.session_state.update({'start_name': sel_b, 'start_coords': get_lat_lng(addr)}); st.rerun()
                with c2:
                    if st.button("🏁", key=f"m_{sel_b}"):
                        st.session_state.update({'meta_name': sel_b, 'meta_coords': get_lat_lng(addr)}); st.rerun()
                with c3:
                    if st.button("🗑️", key=f"d_{sel_b}"):
                        del st.session_state['saved_locations'][sel_b]; save_to_disk(); st.rerun()
        st.markdown("---")
        with st.form("new_b", clear_on_submit=True):
            n, a = st.text_input("Nazwa:"), st.text_input("Adres:")
            if st.form_submit_button("➕ Dodaj"):
                if n and a: st.session_state['saved_locations'][n] = a; save_to_disk(); st.rerun()

    with st.expander("📁 Projekty", expanded=True):
        p_name = st.text_input("Zapisz projekt jako:")
        if st.button("💾 Zapisz") and p_name:
            st.session_state['projects'][p_name] = {
                'data': st.session_state['data'].copy(), 'start_name': st.session_state['start_name'], 'meta_name': st.session_state['meta_name'],
                'start_coords': st.session_state['start_coords'], 'meta_coords': st.session_state['meta_coords'],
                'optimized_list': [df.copy() for df in st.session_state['optimized_list']], 'geometries': st.session_state['geometries']
            }
            save_to_disk(); st.success("Zapisano!"); st.rerun()
        if st.session_state['projects']:
            st.markdown("---")
            sorted_projs = sorted(st.session_state['projects'].keys())
            sel_p = st.selectbox("Wybierz projekt:", ["---"] + sorted_projs)
            if sel_p != "---":
                col_open, col_del = st.columns([3, 1])
                with col_open:
                    if st.button("📂 Otwórz"):
                        st.session_state.update(st.session_state['projects'][sel_p]); st.rerun()
                with col_del:
                    if st.button("🗑️", key=f"del_proj_{sel_p}"):
                        del st.session_state['projects'][sel_p]; save_to_disk(); st.rerun()

    st.button("🔓 WYLOGUJ", on_click=lambda: st.session_state.update({'authenticated': False}))

# --- 5. PANEL GŁÓWNY ---
st.title("🗺️ Optymalizator Tras")

c_start_box, c_meta_box = st.columns(2)
with c_start_box:
    st.markdown(f'<div class="base-info-box">🏠 <b>START:</b> {st.session_state["start_name"]}</div>', unsafe_allow_html=True)
    if st.session_state['start_name'] != "Nie wybrano":
        if st.button("✖", key="clear_start"):
            st.session_state.update({'start_name': "Nie wybrano", 'start_coords': None, 'geometries': [], 'optimized_list': []})
            st.rerun()

with c_meta_box:
    st.markdown(f'<div class="base-info-box">🏁 <b>META:</b> {st.session_state["meta_name"]}</div>', unsafe_allow_html=True)
    if st.session_state['meta_name'] != "Nie wybrano":
        if st.button("✖", key="clear_meta"):
            st.session_state.update({'meta_name': "Nie wybrano", 'meta_coords': None, 'geometries': [], 'optimized_list': []})
            st.rerun()

sc, mc = st.session_state['start_coords'], st.session_state['meta_coords']

if not st.session_state['data'].empty or sc:
    col_filters, col_view = st.columns([2, 1])
    with col_filters:
        u_files = sorted(st.session_state['data']['source_file'].unique().tolist())
        v_files = st.multiselect("Rejony:", u_files, key=f"ms_{st.session_state['reset_counter']}")
        filtered_df = st.session_state['data'][st.session_state['data']['source_file'].isin(v_files)]

    with col_view:
        show_pins = st.checkbox("Pokaż pinezki", value=True)
        mode = st.radio("Tryb:", ["Jedna trasa", "Oddzielne"], horizontal=True)

    col_calc, col_clear = st.columns([3, 1])
    with col_calc:
        if st.button("OBLICZ TRASY", type="primary", use_container_width=True):
            if not (sc and mc): st.error("Ustaw Start i Metę!")
            else:
                with st.spinner("Obliczanie..."):
                    st.session_state.update({'optimized_list': [], 'geometries': []})
                    groups = [filtered_df] if mode == "Jedna trasa" else [filtered_df[filtered_df['source_file'] == f] for f in filtered_df['source_file'].unique()]
                    
                    for group in groups:
                        if group.empty: continue
                        # Ustalenie koloru dla tej konkretnej trasy na podstawie pliku źródłowego
                        source_name = group['source_file'].iloc[0] if mode != "Jedna trasa" else "Całość"
                        route_color = file_color_map.get(group['source_file'].iloc[0], 'blue') if mode != "Jedna trasa" else 'green'
                        
                        curr = {"lat": sc['lat'], "lng": sc['lng'], "display_name": "START", "source_file": "Baza"}
                        route, unv = [curr], group.to_dict('records')
                        while unv:
                            nxt = min(unv, key=lambda x: get_math_dist(curr['lat'], curr['lng'], x['lat'], x['lng']))
                            route.append(nxt); curr = nxt; unv.remove(nxt)
                        route.append({"lat": mc['lat'], "lng": mc['lng'], "display_name": "META", "source_file": "Baza"})
                        
                        geom, d, t = get_route_chunked([[r['lat'], r['lng']] for r in route])
                        st.session_state['optimized_list'].append(pd.DataFrame(route))
                        st.session_state['geometries'].append({
                            "geom": geom, 
                            "color": route_color, 
                            "dist": d, "time": t, 
                            "pts_count": len(group), 
                            "name": source_name, 
                            "source_file": group['source_file'].iloc[0] if mode != "Jedna trasa" else "ALL"
                        })
                    st.rerun()

    with col_clear:
        if st.button("🗑️ WYCZYŚĆ", key="main_reset_btn", use_container_width=True):
            st.session_state['optimized_list'] = []
            st.session_state['geometries'] = []
            st.session_state['reset_counter'] += 1 
            st.rerun()

    visible_geoms = [g for g in st.session_state['geometries'] if mode == "Jedna trasa" or g.get('source_file') in v_files]
    m = folium.Map()
    all_coords = [[sc['lat'], sc['lng']]] if sc else []
    if mc: all_coords.append([mc['lat'], mc['lng']])
    for _, r in filtered_df.iterrows(): all_coords.append([r['lat'], r['lng']])
    if all_coords: m.fit_bounds(all_coords)

    if sc: folium.Marker([sc['lat'], sc['lng']], icon=folium.Icon(color='green', icon='home', prefix='fa')).add_to(m)
    if mc: folium.Marker([mc['lat'], mc['lng']], icon=folium.Icon(color='red', icon='flag', prefix='fa')).add_to(m)
    
    # Rysowanie linii trasy w przypisanym kolorze
    for g in visible_geoms: 
        folium.PolyLine([[c[1], c[0]] for c in g['geom']], color=g['color'], weight=5, opacity=0.8).add_to(m)
        
    if show_pins:
        for idx, r in filtered_df.iterrows():
            folium.Marker([r['lat'], r['lng']], icon=folium.Icon(color=file_color_map.get(r['source_file'], 'gray'), icon='circle', prefix='fa'), tooltip=r['display_name']).add_to(m)
    
    map_data = st_folium(m, width="100%", height=550, key=f"map_{st.session_state['reset_counter']}")

    if show_pins and map_data.get("last_object_clicked"):
        clat, clng = map_data["last_object_clicked"]["lat"], map_data["last_object_clicked"]["lng"]
        match = st.session_state['data'][(abs(st.session_state['data']['lat'] - clat) < 0.0001) & (abs(st.session_state['data']['lng'] - clng) < 0.0001)]
        if not match.empty:
            t_idx, t_name = match.index[0], match.iloc[0]['display_name']
            st.warning(f"Zaznaczono punkt: {t_name}")
            if st.button(f"🗑️ USUŃ TEN PUNKT"):
                st.session_state['data'] = st.session_state['data'].drop(t_idx).reset_index(drop=True)
                st.session_state.update({'optimized_list': [], 'geometries': []})
                st.rerun()

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
            if i < len(st.session_state['geometries']):
                source = st.session_state['geometries'][i]['name']
                if mode == "Jedna trasa" or st.session_state['geometries'][i]['source_file'] in v_files:
                    with st.expander(f"📋 Tabela: {source}"):
                        st.table(opt_df[['display_name', 'source_file']].reset_index(drop=True))
else:
    st.info("👈 Wgraj KML i wybierz bazy.")
