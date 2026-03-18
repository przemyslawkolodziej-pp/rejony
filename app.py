import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
import re, math, json, requests, os, time, zlib, base64
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# --- 1. KONFIGURACJA ---
SHEET_ID = "1mTMjUKoHNw-okxpYSAeLsVD7vdxYR1P-ZjelWt9IHAE" 

st.set_page_config(page_title="Optymalizator Tras", page_icon="🗺️", layout="wide")

# --- 2. INTEGRACJA Z GOOGLE SHEETS ---
def get_gspread_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_dict = dict(st.secrets["gcp_service_account"])
    raw_key = creds_dict["private_key"].strip().strip('"').strip("'")
    if "\\n" in raw_key:
        raw_key = raw_key.replace("\\n", "\n")
    creds_dict["private_key"] = raw_key
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds)

def compress_data(data_dict):
    json_str = json.dumps(data_dict, ensure_ascii=False, separators=(',', ':'))
    compressed = zlib.compress(json_str.encode('utf-8'))
    return base64.b64encode(compressed).decode('utf-8')

def decompress_data(compressed_str):
    try:
        decoded = base64.b64decode(compressed_str)
        decompressed = zlib.decompress(decoded)
        return json.loads(decompressed.decode('utf-8'))
    except:
        return json.loads(compressed_str)

def sync_save():
    if not SHEET_ID: return
    try:
        client = get_gspread_client()
        sheet = client.open_by_key(SHEET_ID)
        loc_sheet = sheet.worksheet("SavedLocations")
        loc_rows = [["Nazwa", "Adres"]]
        for name, addr in st.session_state['saved_locations'].items():
            loc_rows.append([str(name), str(addr)])
        loc_sheet.update(values=loc_rows, range_name='A1', value_input_option='RAW')
        p_rows = [["Nazwa Projektu", "Dane JSON"]]
        for p_name, p_data in st.session_state['projects'].items():
            serializable = p_data.copy()
            if isinstance(serializable.get('data'), pd.DataFrame):
                serializable['data'] = serializable['data'].to_dict()
            if 'optimized_list' in serializable:
                serializable['optimized_list'] = [df.to_dict() if isinstance(df, pd.DataFrame) else df for df in serializable['optimized_list']]
            compressed_payload = compress_data(serializable)
            p_rows.append([str(p_name), compressed_payload])
        proj_sheet = sheet.worksheet("Projects")
        proj_sheet.update(values=p_rows, range_name='A1', value_input_option='RAW')
        st.toast("Zsynchronizowano! ✅", icon="☁️")
    except Exception as e:
        st.error(f"⚠️ BŁĄD SYNCHRONIZACJI: {str(e)}")

def sync_load():
    if not SHEET_ID: return
    try:
        client = get_gspread_client()
        sheet = client.open_by_key(SHEET_ID)
        loc_data = sheet.worksheet("SavedLocations").get_all_records()
        st.session_state['saved_locations'] = {row['Nazwa']: row['Adres'] for row in loc_data if 'Nazwa' in row}
        proj_data = sheet.worksheet("Projects").get_all_records()
        loaded_projs = {}
        for row in proj_data:
            p_name, p_json = row.get('Nazwa Projektu'), row.get('Dane JSON')
            if p_name and p_json:
                p_content = decompress_data(p_json)
                if 'data' in p_content: p_content['data'] = pd.DataFrame(p_content['data'])
                if 'optimized_list' in p_content:
                    p_content['optimized_list'] = [pd.DataFrame(df) for df in p_content['optimized_list']]
                loaded_projs[p_name] = p_content
        st.session_state['projects'] = loaded_projs
    except: pass

# --- 3. INICJALIZACJA SESJI ---
for key in ['authenticated', 'data', 'optimized_list', 'saved_locations', 'projects', 'start_coords', 'meta_coords', 'geometries', 'reset_counter']:
    if key not in st.session_state:
        if key == 'authenticated': st.session_state[key] = False
        elif key == 'data': st.session_state[key] = pd.DataFrame()
        elif key == 'reset_counter': st.session_state[key] = 0
        elif key in ['optimized_list', 'geometries']: st.session_state[key] = []
        elif key in ['saved_locations', 'projects']: st.session_state[key] = {}
        else: st.session_state[key] = None

if 'start_name' not in st.session_state: st.session_state.update({'start_name': "Nie wybrano", 'meta_name': "Nie wybrano"})

# OBSŁUGA KLIKNIĘĆ "X" PRZEZ QUERY PARAMS (Stabilne usuwanie)
q = st.query_params
if "clear" in q:
    target = q["clear"]
    if target == "start":
        st.session_state.update({'start_name': "Nie wybrano", 'start_coords': None})
    elif target == "meta":
        st.session_state.update({'meta_name': "Nie wybrano", 'meta_coords': None})
    st.query_params.clear()
    st.rerun()

def check_password():
    if st.session_state['authenticated']: return True
    st.title("🔐 Logowanie")
    with st.form("login"):
        p = st.text_input("Hasło:", type="password")
        if st.form_submit_button("Zaloguj"):
            if "password" in st.secrets and p == st.secrets["password"]:
                st.session_state['authenticated'] = True
                sync_load()
                st.rerun()
            else: st.error("❌ Błędne hasło")
    return False

if not check_password(): st.stop()

# --- 4. STYLE CSS (Pigułki zintegrowane) ---
st.markdown("""
<style>
    .pill-container {
        display: flex;
        justify-content: space-between;
        align-items: center;
        background-color: #f0f2f6;
        border-left: 5px solid #28a745;
        border-radius: 8px;
        padding: 0 15px;
        height: 45px;
        box-sizing: border-box;
    }
    .pill-text {
        font-size: 14px;
        color: #31333F;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .close-btn {
        color: #ff4b4b;
        font-weight: bold;
        cursor: pointer;
        text-decoration: none;
        font-size: 20px;
        line-height: 45px;
        padding-left: 10px;
    }
    .close-btn:hover { color: #b91d1d; }
    button[kind="primary"] { background-color: #28a745 !important; color: white !important; }
</style>
""", unsafe_allow_html=True)

# --- 5. LOGIKA POMOCNICZA ---
def get_folium_color(idx):
    colors = ['blue', 'red', 'green', 'orange', 'purple', 'cadetblue', 'darkred', 'darkblue', 'darkgreen', 'pink', 'lightblue']
    return colors[idx % len(colors)]

file_color_map = {}
if not st.session_state['data'].empty:
    u_files = sorted(st.session_state['data']['source_file'].unique().tolist())
    for i, f in enumerate(u_files): file_color_map[f] = get_folium_color(i)

def get_lat_lng(address):
    try:
        gl = Nominatim(user_agent="v131_geo")
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

# --- 6. SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Zarządzanie")
    
    with st.expander("☁️ Wgrywanie KML", expanded=False):
        up = st.file_uploader("Dodaj pliki rejonów", type=['kml'], accept_multiple_files=True)
        if up and st.button("Wczytaj"):
            all_pts = [parse_kml(f.read().decode('utf-8'), f.name) for f in up]
            if all_pts: 
                new_data = pd.concat(all_pts, ignore_index=True)
                st.session_state['data'] = pd.concat([st.session_state['data'], new_data], ignore_index=True).drop_duplicates()
                st.rerun()

    if not st.session_state['data'].empty:
        with st.expander("📂 Zarządzaj rejonami", expanded=True):
            u_files = sorted(st.session_state['data']['source_file'].unique().tolist())
            for f_name in u_files:
                c1, c2 = st.columns([4, 1.2])
                c1.write(f"📄 {f_name}")
                if c2.button("🗑️", key=f"del_file_{f_name}"):
                    st.session_state['data'] = st.session_state['data'][st.session_state['data']['source_file'] != f_name].reset_index(drop=True)
                    st.rerun()

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
                        del st.session_state['saved_locations'][sel_b]
                        sync_save()
                        st.rerun()
        st.markdown("---")
        with st.form("new_b", clear_on_submit=True):
            n, a = st.text_input("Nazwa:"), st.text_input("Adres:")
            if st.form_submit_button("➕ Dodaj"):
                if n and a: 
                    st.session_state['saved_locations'][n] = a
                    sync_save()
                    st.rerun()

    with st.expander("📁 Projekty", expanded=True):
        p_name = st.text_input("Zapisz projekt jako:")
        if st.button("💾 Zapisz") and p_name:
            st.session_state['projects'][p_name] = {
                'data': st.session_state['data'].copy(), 'start_name': st.session_state['start_name'], 'meta_name': st.session_state['meta_name'],
                'start_coords': st.session_state['start_coords'], 'meta_coords': st.session_state['meta_coords'],
                'optimized_list': [df.copy() for df in st.session_state['optimized_list']], 'geometries': st.session_state['geometries']
            }
            sync_save()
            st.rerun()
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
                        del st.session_state['projects'][sel_p]
                        sync_save()
                        st.rerun()

    st.button("🔓 WYLOGUJ", on_click=lambda: st.session_state.update({'authenticated': False}))

# --- 7. PANEL GŁÓWNY ---
st.title("🗺️ Optymalizator Tras")

col_main_1, col_main_2 = st.columns(2)

with col_main_1:
    s_active = st.session_state['start_name'] != "Nie wybrano"
    x_s = f'<a href="/?clear=start" target="_self" class="close-btn">×</a>' if s_active else ""
    st.markdown(f'<div class="pill-container"><span class="pill-text">🏠 <b>START:</b> {st.session_state["start_name"]}</span>{x_s}</div>', unsafe_allow_html=True)

with col_main_2:
    m_active = st.session_state['meta_name'] != "Nie wybrano"
    x_m = f'<a href="/?clear=meta" target="_self" class="close-btn">×</a>' if m_active else ""
    st.markdown(f'<div class="pill-container"><span class="pill-text">🏁 <b>META:</b> {st.session_state["meta_name"]}</span>{x_m}</div>', unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

sc, mc = st.session_state['start_coords'], st.session_state['meta_coords']

if not st.session_state['data'].empty:
    col_filters, col_view = st.columns([2, 1])
    with col_filters:
        u_files = sorted(st.session_state['data']['source_file'].unique().tolist())
        v_files = st.multiselect("Rejony:", u_files, default=u_files, key=f"ms_{st.session_state['reset_counter']}")
        filtered_df = st.session_state['data'][st.session_state['data']['source_file'].isin(v_files)]
    
    with col_view:
        show_pins = st.checkbox("Pokaż pinezki", value=True)
        mode = st.radio("Tryb:", ["Jedna trasa", "Oddzielne"], horizontal=True)

    col_calc, col_reset = st.columns([4, 1])
    with col_calc:
        if st.button("OBLICZ TRASY", type="primary", use_container_width=True):
            if not (sc and mc): st.error("Ustaw Start i Metę!")
            else:
                with st.spinner("Obliczanie..."):
                    st.session_state.update({'optimized_list': [], 'geometries': []})
                    groups = [filtered_df] if mode == "Jedna trasa" else [filtered_df[filtered_df['source_file'] == f] for f in filtered_df['source_file'].unique()]
                    for group in groups:
                        if group.empty: continue
                        source_name = group['source_file'].iloc[0] if mode != "Jedna trasa" else "Całość"
                        route_color = file_color_map.get(group['source_file'].iloc[0], 'blue') if mode != "Jedna trasa" else 'green'
                        curr = {"lat": sc['lat'], "lng": sc['lng'], "display_name": "START"}
                        route, unv = [curr], group.to_dict('records')
                        while unv:
                            nxt = min(unv, key=lambda x: get_math_dist(curr['lat'], curr['lng'], x['lat'], x['lng']))
                            route.append(nxt); curr = nxt; unv.remove(nxt)
                        route.append({"lat": mc['lat'], "lng": mc['lng'], "display_name": "META"})
                        geom, d, t = get_route_chunked([[r['lat'], r['lng']] for r in route])
                        st.session_state['optimized_list'].append(pd.DataFrame(route))
                        st.session_state['geometries'].append({"geom": geom, "color": route_color, "dist": d, "time": t, "pts_count": len(group), "name": source_name, "source_file": group['source_file'].iloc[0] if mode != "Jedna trasa" else "ALL"})
                    st.rerun()
    with col_reset:
        if st.button("✖ WYCZYŚĆ WSZYSTKO", use_container_width=True):
            st.session_state.update({'optimized_list': [], 'geometries': [], 'data': pd.DataFrame(), 'start_name': "Nie wybrano", 'meta_name': "Nie wybrano", 'start_coords': None, 'meta_coords': None})
            st.rerun()

    m = folium.Map()
    all_coords = [[sc['lat'], sc['lng']]] if sc else []
    if mc: all_coords.append([mc['lat'], mc['lng']])
    for _, r in filtered_df.iterrows(): all_coords.append([r['lat'], r['lng']])
    if all_coords: m.fit_bounds(all_coords)

    if sc: folium.Marker([sc['lat'], sc['lng']], icon=folium.Icon(color='green', icon='home', prefix='fa')).add_to(m)
    if mc: folium.Marker([mc['lat'], mc['lng']], icon=folium.Icon(color='red', icon='flag', prefix='fa')).add_to(m)
    
    visible_geoms = [g for g in st.session_state['geometries'] if mode == "Jedna trasa" or g.get('source_file') in v_files]
    for g in visible_geoms: 
        folium.PolyLine([[c[1], c[0]] for c in g['geom']], color=g['color'], weight=5, opacity=0.8).add_to(m)
    
    if show_pins:
        for _, r in filtered_df.iterrows():
            folium.Marker([r['lat'], r['lng']], icon=folium.Icon(color=file_color_map.get(r['source_file'], 'gray'), icon='circle', prefix='fa'), tooltip=r['display_name']).add_to(m)
    
    st_folium(m, width="100%", height=550, key=f"map_{st.session_state['reset_counter']}")
    
    if st.session_state['geometries']:
        td = sum(g['dist'] for g in visible_geoms)
        tt = sum(g['time'] for g in visible_geoms)
        st.success(f"📊 RAZEM: {td/1000:.2f} km | Szacowany czas: {int(tt//3600)}h {int((tt%3600)//60)}min")
else:
    if sc or mc:
        st.info("📍 Wybrano bazę. Wgraj KML, aby zobaczyć mapę.")
        m = folium.Map()
        pts = []
        if sc: 
            folium.Marker([sc['lat'], sc['lng']], icon=folium.Icon(color='green')).add_to(m)
            pts.append([sc['lat'], sc['lng']])
        if mc: 
            folium.Marker([mc['lat'], mc['lng']], icon=folium.Icon(color='red')).add_to(m)
            pts.append([mc['lat'], mc['lng']])
        m.fit_bounds(pts)
        st_folium(m, width="100%", height=550)
    else:
        st.info("👈 Wgraj KML i wybierz bazy w pasku bocznym.")
