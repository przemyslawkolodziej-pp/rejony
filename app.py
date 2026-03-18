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

# --- 2. INTEGRACJA GOOGLE SHEETS ---
def get_gspread_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_dict = dict(st.secrets["gcp_service_account"])
    raw_key = creds_dict["private_key"].strip().strip('"').strip("'")
    if "\\n" in raw_key: raw_key = raw_key.replace("\\n", "\n")
    creds_dict["private_key"] = raw_key
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds)

def compress_data(data_dict):
    json_str = json.dumps(data_dict, ensure_ascii=False, separators=(',', ':'))
    return base64.b64encode(zlib.compress(json_str.encode('utf-8'))).decode('utf-8')

def decompress_data(compressed_str):
    try: return json.loads(zlib.decompress(base64.b64decode(compressed_str)).decode('utf-8'))
    except: return json.loads(compressed_str)

def sync_save():
    if not SHEET_ID: return
    try:
        client = get_gspread_client()
        sheet = client.open_by_key(SHEET_ID)
        loc_rows = [["Nazwa", "Adres"]] + [[n, a] for n, a in st.session_state['saved_locations'].items()]
        sheet.worksheet("SavedLocations").update(values=loc_rows, range_name='A1')
        p_rows = [["Nazwa Projektu", "Dane JSON"]]
        for p_name, p_data in st.session_state['projects'].items():
            s = p_data.copy()
            if isinstance(s.get('data'), pd.DataFrame): s['data'] = s['data'].to_dict()
            if 'optimized_list' in s: s['optimized_list'] = [df.to_dict() if isinstance(df, pd.DataFrame) else df for df in s['optimized_list']]
            p_rows.append([p_name, compress_data(s)])
        sheet.worksheet("Projects").update(values=p_rows, range_name='A1')
        st.toast("Zsynchronizowano! ✅")
    except Exception as e: st.error(f"Błąd sync: {e}")

def sync_load():
    if not SHEET_ID: return
    try:
        client = get_gspread_client()
        sheet = client.open_by_key(SHEET_ID)
        st.session_state['saved_locations'] = {r['Nazwa']: r['Adres'] for r in sheet.worksheet("SavedLocations").get_all_records()}
        projs = {}
        for r in sheet.worksheet("Projects").get_all_records():
            c = decompress_data(r['Dane JSON'])
            if 'data' in c: c['data'] = pd.DataFrame(c['data'])
            if 'optimized_list' in c: c['optimized_list'] = [pd.DataFrame(df) for df in c['optimized_list']]
            projs[r['Nazwa Projektu']] = c
        st.session_state['projects'] = projs
    except: pass

# --- 3. SESJA ---
for key in ['authenticated', 'data', 'optimized_list', 'saved_locations', 'projects', 'start_coords', 'meta_coords', 'geometries', 'reset_counter']:
    if key not in st.session_state:
        st.session_state[key] = False if key=='authenticated' else (pd.DataFrame() if key=='data' else (0 if key=='reset_counter' else ([] if key in ['optimized_list', 'geometries'] else ({} if key in ['saved_locations', 'projects'] else None))))
if 'start_name' not in st.session_state: st.session_state.update({'start_name': "Nie wybrano", 'meta_name': "Nie wybrano"})

if not st.session_state['authenticated']:
    st.title("🔐 Logowanie")
    with st.form("login"):
        if st.form_submit_button("Zaloguj") and st.text_input("Hasło:", type="password") == st.secrets.get("password"):
            st.session_state['authenticated'] = True; sync_load(); st.rerun()
        else: st.stop()

# --- 4. CSS - MAGIA WYRÓWNANIA ---
st.markdown("""
<style>
    /* Kontener paska */
    .pill-box {
        background-color: #f0f2f6;
        border-left: 5px solid #28a745;
        border-radius: 8px;
        height: 45px;
        display: flex;
        align-items: center;
        padding-left: 15px;
        position: relative;
        margin-bottom: 20px;
    }
    .pill-text { font-size: 14px; color: #31333F; font-weight: normal; }

    /* Przycisk X - Wymuszenie pozycji wewnątrz kontenera */
    div[data-testid="stVerticalBlock"] > div:has(button[key*="btn_clr_"]) {
        position: absolute !important;
        right: 5px !important;
        top: 0px !important;
        z-index: 100;
    }
    
    button[key*="btn_clr_"] {
        background: transparent !important;
        border: none !important;
        color: #ff4b4b !important;
        font-weight: bold !important;
        font-size: 20px !important;
        height: 45px !important;
        width: 40px !important;
        padding: 0 !important;
    }
    button[key*="btn_clr_"]:hover { color: #b91d1d !important; background: rgba(255,75,75,0.1) !important; }
    button[kind="primary"] { background-color: #28a745 !important; color: white !important; }
</style>
""", unsafe_allow_html=True)

# --- 5. POMOCNICZE ---
def get_lat_lng(addr):
    try:
        loc = Nominatim(user_agent="v133").geocode(addr, timeout=10)
        return {"lat": loc.latitude, "lng": loc.longitude} if loc else None
    except: return None

def get_math_dist(la1, lo1, la2, lo2): return math.sqrt((la1-la2)**2 + (lo1-lo2)**2)

def get_route_chunked(coords):
    geom, dist, time = [], 0, 0
    for i in range(0, len(coords)-1, 39):
        chunk = coords[i:i+40]
        try:
            r = requests.get(f"http://router.project-osrm.org/route/v1/driving/{';'.join([f'{c[1]},{c[0]}' for c in chunk])}?overview=full&geometries=geojson").json()
            if r['code']=='Ok':
                geom.extend(r['routes'][0]['geometry']['coordinates'])
                dist += r['routes'][0]['distance']; time += r['routes'][0]['duration']
        except: pass
    return geom, dist, time

# --- 6. SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Zarządzanie")
    with st.expander("☁️ KML", expanded=False):
        up = st.file_uploader("Pliki rejonów", type=['kml'], accept_multiple_files=True)
        if up and st.button("Wczytaj"):
            pts = []
            for f in up:
                content = f.read().decode('utf-8')
                for pm in re.findall(r'<Placemark>(.*?)</Placemark>', content, re.DOTALL):
                    n = re.search(r'<(?:name|display_name)>(.*?)</', pm)
                    c = re.search(r'<coordinates>\s*([\d\.\-]+),\s*([\d\.\-]+)', pm)
                    if c: pts.append({"display_name": n.group(1) if n else "Punkt", "lat": float(c.group(2)), "lng": float(c.group(1)), "source_file": f.name})
            if pts: st.session_state['data'] = pd.concat([st.session_state['data'], pd.DataFrame(pts)], ignore_index=True).drop_duplicates(); st.rerun()

    if not st.session_state['data'].empty:
        with st.expander("📂 Rejony", expanded=True):
            for f in sorted(st.session_state['data']['source_file'].unique()):
                c1, c2 = st.columns([4,1])
                c1.write(f"📄 {f}")
                if c2.button("🗑️", key=f"del_{f}"):
                    st.session_state['data'] = st.session_state['data'][st.session_state['data']['source_file']!=f]; st.rerun()

    with st.expander("🏠 Bazy", expanded=True):
        if st.session_state['saved_locations']:
            sel_b = st.selectbox("Wybierz:", ["---"] + sorted(st.session_state['saved_locations'].keys()))
            if sel_b != "---":
                addr = st.session_state['saved_locations'][sel_b]
                c1, c2, c3 = st.columns(3)
                if c1.button("🏠", key=f"sb_{sel_b}"): st.session_state.update({'start_name': sel_b, 'start_coords': get_lat_lng(addr)}); st.rerun()
                if c2.button("🏁", key=f"mb_{sel_b}"): st.session_state.update({'meta_name': sel_b, 'meta_coords': get_lat_lng(addr)}); st.rerun()
                if c3.button("🗑️", key=f"db_{sel_b}"): del st.session_state['saved_locations'][sel_b]; sync_save(); st.rerun()
        with st.form("new_b", clear_on_submit=True):
            n, a = st.text_input("Nazwa:"), st.text_input("Adres:")
            if st.form_submit_button("➕"): 
                if n and a: st.session_state['saved_locations'][n]=a; sync_save(); st.rerun()

    st.button("🔓 WYLOGUJ", on_click=lambda: st.session_state.update({'authenticated': False}))

# --- 7. PANEL GŁÓWNY ---
st.title("🗺️ Optymalizator Tras")

col1, col2 = st.columns(2)

with col1:
    st.markdown(f'<div class="pill-box"><span class="pill-text">🏠 <b>START:</b> {st.session_state["start_name"]}</span></div>', unsafe_allow_html=True)
    if st.session_state["start_name"] != "Nie wybrano":
        if st.button("×", key="btn_clr_start"):
            st.session_state.update({'start_name': "Nie wybrano", 'start_coords': None}); st.rerun()

with col2:
    st.markdown(f'<div class="pill-box"><span class="pill-text">🏁 <b>META:</b> {st.session_state["meta_name"]}</span></div>', unsafe_allow_html=True)
    if st.session_state["meta_name"] != "Nie wybrano":
        if st.button("×", key="btn_clr_meta"):
            st.session_state.update({'meta_name': "Nie wybrano", 'meta_coords': None}); st.rerun()

# --- MAPA I LOGIKA ---
sc, mc = st.session_state['start_coords'], st.session_state['meta_coords']
if not st.session_state['data'].empty:
    u_files = sorted(st.session_state['data']['source_file'].unique().tolist())
    v_files = st.multiselect("Rejony:", u_files, default=u_files)
    filtered_df = st.session_state['data'][st.session_state['data']['source_file'].isin(v_files)]
    
    col_v1, col_v2 = st.columns(2)
    show_pins = col_v1.checkbox("Pokaż punkty", value=True)
    mode = col_v2.radio("Tryb:", ["Jedna trasa", "Oddzielne"], horizontal=True)

    c_calc, c_res = st.columns([4,1])
    if c_calc.button("OBLICZ TRASY", type="primary", use_container_width=True):
        if not (sc and mc): st.error("Ustaw Start i Metę!")
        else:
            with st.spinner("Liczenie..."):
                st.session_state.update({'optimized_list': [], 'geometries': []})
                groups = [filtered_df] if mode == "Jedna trasa" else [filtered_df[filtered_df['source_file']==f] for f in filtered_df['source_file'].unique()]
                for group in groups:
                    if group.empty: continue
                    curr = {"lat": sc['lat'], "lng": sc['lng']}
                    route, unv = [curr], group.to_dict('records')
                    while unv:
                        nxt = min(unv, key=lambda x: get_math_dist(curr['lat'], curr['lng'], x['lat'], x['lng']))
                        route.append(nxt); curr = nxt; unv.remove(nxt)
                    route.append({"lat": mc['lat'], "lng": mc['lng']})
                    geom, d, t = get_route_chunked([[r['lat'], r['lng']] for r in route])
                    st.session_state['geometries'].append({"geom": geom, "dist": d, "time": t, "color": "green" if mode=="Jedna trasa" else "blue"})
                st.rerun()
    
    if c_res.button("WYCZYŚĆ", use_container_width=True):
        st.session_state.update({'optimized_list': [], 'geometries': [], 'data': pd.DataFrame(), 'start_name': "Nie wybrano", 'meta_name': "Nie wybrano", 'start_coords': None, 'meta_coords': None})
        st.rerun()

    m = folium.Map()
    bounds = []
    if sc: folium.Marker([sc['lat'], sc['lng']], icon=folium.Icon(color='green', icon='home')).add_to(m); bounds.append([sc['lat'], sc['lng']])
    if mc: folium.Marker([mc['lat'], mc['lng']], icon=folium.Icon(color='red', icon='flag')).add_to(m); bounds.append([mc['lat'], mc['lng']])
    
    for g in st.session_state['geometries']:
        folium.PolyLine([[c[1], c[0]] for c in g['geom']], color=g['color'], weight=5).add_to(m)
    
    if show_pins:
        for _, r in filtered_df.iterrows():
            folium.Marker([r['lat'], r['lng']], tooltip=r['display_name']).add_to(m); bounds.append([r['lat'], r['lng']])
    
    if bounds: m.fit_bounds(bounds)
    st_folium(m, width="100%", height=500)
