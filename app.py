import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
import re, math, json, requests, os, time, zlib, base64, hashlib
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# --- 1. KONFIGURACJA ---
SHEET_ID = "1mTMjUKoHNw-okxpYSAeLsVD7vdxYR1P-ZjelWt9IHAE" 
st.set_page_config(page_title="Optymalizator Tras", page_icon="🗺️", layout="wide")

COLORS = ['#007bff', '#28a745', '#6f42c1', '#fd7e14', '#20c997', '#e83e8c', '#dc3545', '#ffc107']

st.markdown("""
    <style>
        .stButton>button { border-radius: 8px; }
        .metric-card { background-color: #f8f9fa; padding: 15px; border-radius: 10px; box-shadow: 2px 2px 5px rgba(0,0,0,0.05); margin-bottom: 10px; border-left: 8px solid; }
        .metric-title { font-weight: bold; color: #495057; margin-bottom: 8px; font-size: 1.1rem; }
        .metric-row { display: flex; align-items: center; gap: 10px; margin-bottom: 4px; color: #333; font-weight: 500; }
        .metric-icon { width: 20px; text-align: center; }
    </style>
""", unsafe_allow_html=True)

# --- 2. FUNKCJE LOGIKI ---
def get_lat_lng(addr):
    try:
        loc = Nominatim(user_agent="v199_opt").geocode(addr, timeout=10)
        return {"lat": loc.latitude, "lng": loc.longitude} if loc else None
    except: return None

def optimize_route(df_points, start_coords, meta_coords, color_idx):
    curr_p = {"lat": start_coords['lat'], "lng": start_coords['lng']}
    route, unv = [curr_p], df_points.to_dict('records')
    while unv:
        nxt = min(unv, key=lambda x: math.sqrt((curr_p['lat']-x['lat'])**2 + (curr_p['lng']-x['lng'])**2))
        route.append(nxt); curr_p = nxt; unv.remove(nxt)
    route.append({"display_name": "META", "lat": meta_coords['lat'], "lng": meta_coords['lng']})
    coords = [[r['lat'], r['lng']] for r in route]
    geom, dist, dur = [], 0, 0
    for j in range(0, len(coords)-1, 39):
        chunk = coords[j:j+40]
        try:
            r = requests.get(f"http://router.project-osrm.org/route/v1/driving/{';'.join([f'{c[1]},{c[0]}' for c in chunk])}?overview=full&geometries=geojson").json()
            if r['code']=='Ok':
                geom.extend(r['routes'][0]['geometry']['coordinates'])
                dist += r['routes'][0]['distance']; dur += r['routes'][0]['duration']
        except: pass
    return {"geom": geom, "color": COLORS[color_idx % len(COLORS)], "dist": dist, "time": dur, "pts_count": len(df_points), "df": pd.DataFrame(route)}

# --- FUNKCJE SYNC ---
def check_auth():
    if st.session_state.get('authenticated'): return True
    params = st.query_params
    if "token" in params and params["token"] == hashlib.sha256(st.secrets.get("password", "").encode()).hexdigest():
        st.session_state['authenticated'] = True
        return True
    return False

def get_gspread_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds)

def sync_save():
    try:
        client = get_gspread_client()
        sheet = client.open_by_key(SHEET_ID)
        l_sh = sheet.worksheet("SavedLocations")
        l_sh.clear()
        l_sh.update(values=[["Nazwa", "Adres"]] + [[n, a] for n, a in st.session_state['saved_locations'].items()], range_name='A1')
        p_sh = sheet.worksheet("Projects")
        p_sh.clear()
        p_rows = [["Nazwa Projektu", "Dane JSON"]]
        for p_n, p_d in st.session_state['projects'].items():
            s = p_d.copy()
            if isinstance(s.get('data'), pd.DataFrame): s['data'] = s['data'].to_dict()
            if 'optimized_cache' in s:
                s['optimized_cache'] = {k: {**v, 'df': v['df'].to_dict()} for k, v in s['optimized_cache'].items()}
            p_rows.append([str(p_n), base64.b64encode(zlib.compress(json.dumps(s).encode())).decode()])
        p_sh.update(values=p_rows, range_name='A1')
        st.toast("Zsynchronizowano! ✅")
    except Exception as e: st.error(f"Błąd sync: {e}")

def sync_load():
    try:
        client = get_gspread_client()
        sheet = client.open_by_key(SHEET_ID)
        loc_data = sheet.worksheet("SavedLocations").get_all_records()
        st.session_state['saved_locations'] = {r['Nazwa']: r['Adres'] for r in loc_data if 'Nazwa' in r}
        proj_data = sheet.worksheet("Projects").get_all_records()
        loaded = {}
        for r in proj_data:
            p_n, p_j = r.get('Nazwa Projektu'), r.get('Dane JSON')
            if p_n and p_j:
                try:
                    c = json.loads(zlib.decompress(base64.b64decode(p_j)))
                    if 'data' in c: c['data'] = pd.DataFrame(c['data'])
                    if 'optimized_cache' in c:
                        c['optimized_cache'] = {k: {**v, 'df': pd.DataFrame(v['df'])} for k, v in c['optimized_cache'].items()}
                    loaded[p_n] = c
                except: pass
        st.session_state['projects'] = loaded
    except: pass

# --- 3. MODALE ---
@st.dialog("Otwórz projekt")
def modal_open_project():
    if not st.session_state['projects']:
        st.write("Brak projektów."); return
    sel = st.selectbox("Wybierz projekt:", sorted(st.session_state['projects'].keys()))
    if st.button("Wczytaj"):
        st.session_state.update(st.session_state['projects'][sel]); st.rerun()

@st.dialog("Zapisz projekt")
def modal_save_project():
    n = st.text_input("Nazwa projektu:", value=f"Projekt {time.strftime('%H:%M:%S')}")
    if st.button("Zapisz") and n:
        st.session_state['projects'][n] = {
            'data': st.session_state['data'].copy(), 'start_name': st.session_state['start_name'], 'meta_name': st.session_state['meta_name'],
            'start_coords': st.session_state['start_coords'], 'meta_coords': st.session_state['meta_coords'],
            'optimized_cache': st.session_state['optimized_cache'].copy()
        }
        sync_save(); st.rerun()

@st.dialog("Wczytaj i przelicz optymalne trasy")
def modal_add_kml():
    if st.session_state['start_name'] == "---" or st.session_state['meta_name'] == "---":
        st.error("⚠️ Wybierz START i METĘ!"); return
    up = st.file_uploader("Wybierz pliki KML", type=['kml'], accept_multiple_files=True)
    if st.button("Wczytaj i Oblicz") and up:
        with st.spinner("Przeliczanie..."):
            for f in up:
                content = f.read().decode('utf-8')
                pts = []
                for pm in re.findall(r'<Placemark>(.*?)</Placemark>', content, re.DOTALL):
                    n = re.search(r'<(?:name|display_name)>(.*?)</', pm)
                    c = re.search(r'<coordinates>\s*([\d\.\-]+),\s*([\d\.\-]+)', pm)
                    if c: pts.append({"display_name": n.group(1) if n else "Punkt", "lat": float(c.group(2)), "lng": float(c.group(1)), "source_file": f.name})
                if pts:
                    df_new = pd.DataFrame(pts)
                    st.session_state['data'] = pd.concat([st.session_state['data'], df_new], ignore_index=True).drop_duplicates()
                    all_files = sorted(st.session_state['data']['source_file'].unique().tolist())
                    st.session_state['optimized_cache'][f.name] = optimize_route(df_new, st.session_state['start_coords'], st.session_state['meta_coords'], all_files.index(f.name))
        st.rerun()

@st.dialog("Bazy")
def modal_bases():
    tab1, tab2 = st.tabs(["Dodaj bazę", "Usuń bazę"])
    with tab1:
        n, a = st.text_input("Nazwa:"), st.text_input("Adres:")
        if st.button("Dodaj bazę"):
            if n and a: 
                st.session_state['saved_locations'][n]=a; sync_save(); st.rerun()
    with tab2:
        if not st.session_state['saved_locations']: st.write("Brak baz."); return
        sel = st.selectbox("Wybierz bazę do usunięcia:", sorted(st.session_state['saved_locations'].keys()))
        if st.button("Usuń wybraną"):
            del st.session_state['saved_locations'][sel]; sync_save(); st.rerun()

@st.dialog("Usuń KML")
def modal_remove_kml():
    if st.session_state['data'].empty: st.write("Brak plików."); return
    u_f = sorted(st.session_state['data']['source_file'].unique().tolist())
    to_del = st.multiselect("Pliki do usunięcia:", u_f)
    if st.button("Usuń zaznaczone"):
        st.session_state['data'] = st.session_state['data'][~st.session_state['data']['source_file'].isin(to_del)]
        for f in to_del:
            if f in st.session_state['optimized_cache']: del st.session_state['optimized_cache'][f]
        st.rerun()

# --- 4. INICJALIZACJA ---
if 'initialized' not in st.session_state:
    st.session_state.update({'initialized': True, 'authenticated': False, 'data': pd.DataFrame(), 'optimized_cache': {}, 'saved_locations': {}, 'projects': {}, 'start_coords': None, 'meta_coords': None, 'start_name': "---", 'meta_name': "---"})
if check_auth() and not st.session_state['projects']: sync_load()
if not check_auth():
    st.title("🔐 Logowanie")
    with st.form("l"):
        p = st.text_input("Hasło:", type="password")
        if st.form_submit_button("Zaloguj"):
            if p == st.secrets.get("password"):
                st.query_params["token"] = hashlib.sha256(p.encode()).hexdigest()
                st.session_state['authenticated'] = True; sync_load(); st.rerun()
    st.stop()

# --- 5. NAWIGACJA ---
with st.container():
    c = st.columns([1, 1, 1.8, 1.2, 1.2, 1.2, 1.2, 1])
    if c[0].button("📂 Otwórz", use_container_width=True): modal_open_project()
    if c[1].button("💾 Zapisz", use_container_width=True): modal_save_project()
    if c[2].button("➕ Zapisz jako Nowy", use_container_width=True): modal_save_project()
    if c[3].button("📎 Dodaj KML", use_container_width=True): modal_add_kml()
    if c[4].button("❌ Usuń KML", use_container_width=True): modal_remove_kml()
    if c[5].button("🏠 Bazy", use_container_width=True): modal_bases()
    if c[6].button("🗑️ Wyczyść", use_container_width=True):
        st.session_state.update({'data': pd.DataFrame(), 'optimized_cache': {}, 'start_name': "---", 'meta_name': "---", 'start_coords': None, 'meta_coords': None})
        st.rerun()
    if c[7].button("🔓 Wyloguj", use_container_width=True):
        st.query_params.clear(); st.session_state.clear(); st.rerun()

st.markdown("---")

# --- 6. GŁÓWNY UKŁAD ---
bases = sorted(list(st.session_state['saved_locations'].keys()))
c1, c2 = st.columns(2)
with c1:
    s_sel = st.selectbox("🏠 WYBIERZ START:", ["---"] + bases, index=0)
    if s_sel != st.session_state['start_name']:
        st.session_state['start_name'] = s_sel
        st.session_state['start_coords'] = get_lat_lng(st.session_state['saved_locations'][s_sel]) if s_sel != "---" else None
        st.session_state['optimized_cache'] = {}; st.rerun()
with c2:
    m_sel = st.selectbox("🏁 WYBIERZ METĘ:", ["---"] + bases, index=0)
    if m_sel != st.session_state['meta_name']:
        st.session_state['meta_name'] = m_sel
        st.session_state['meta_coords'] = get_lat_lng(st.session_state['saved_locations'][m_sel]) if m_sel != "---" else None
        st.session_state['optimized_cache'] = {}; st.rerun()

if not st.session_state['data'].empty:
    all_rejs = sorted(st.session_state['data']['source_file'].unique().tolist())
    col_list, col_main = st.columns([1, 3.5])
    
    with col_list:
        st.write("### 📍 Wybierz Rejony")
        v_f = []
        with st.container(height=500):
            for rej_name in all_rejs:
                if st.checkbox(rej_name, value=True, key=f"chk_{rej_name}"):
                    v_f.append(rej_name)
                st.divider()

    with col_main:
        # Przeniesienie opcji NAD mapkę
        ctrl1, ctrl2 = st.columns([1, 2])
        show_pins = ctrl1.checkbox("Pokaż pinezki punktów", value=True)
        mode = ctrl2.radio("Sposób wyświetlania:", 
                           ["Jedna trasa (dla wszystkich rejonów)", "Oddzielne trasy (dla każdego rejonu)"], 
                           horizontal=True, index=1)
        
        m = folium.Map()
        bounds = []
        if st.session_state['start_coords']:
            bounds.append([st.session_state['start_coords']['lat'], st.session_state['start_coords']['lng']])
            folium.Marker(bounds[-1], icon=folium.Icon(color='green', icon='play', prefix='fa')).add_to(m)
        if st.session_state['meta_coords']:
            bounds.append([st.session_state['meta_coords']['lat'], st.session_state['meta_coords']['lng']])
            folium.Marker(bounds[-1], icon=folium.Icon(color='red', icon='stop', prefix='fa')).add_to(m)
        
        active_routes = {k: v for k, v in st.session_state['optimized_cache'].items() if k in v_f}
        for name, data in active_routes.items():
            folium.PolyLine([[c[1], c[0]] for c in data['geom']], color=data['color'], weight=5, opacity=0.8).add_to(m)
            if show_pins:
                pts = st.session_state['data'][st.session_state['data']['source_file'] == name]
                for _, r in pts.iterrows():
                    folium.CircleMarker([r['lat'], r['lng']], radius=6, color=data['color'], fill=True, fill_color=data['color'], fill_opacity=0.7, tooltip=r['display_name']).add_to(m)
                    bounds.append([r['lat'], r['lng']])
        
        if bounds: m.fit_bounds(bounds)
        st_folium(m, width="100%", height=550)

    if active_routes:
        st.markdown("### 📊 Szczegóły tras")
        cols = st.columns(min(len(active_routes), 3))
        for idx, (name, data) in enumerate(active_routes.items()):
            with cols[idx % 3]:
                st.markdown(f"""
                <div class="metric-card" style="border-left-color: {data['color']};">
                    <div class="metric-title">📍 {name}</div>
                    <div class="metric-row"><span class="metric-icon">🛣️</span><span>Dystans: <b>{data['dist']/1000:.2f} km</b></span></div>
                    <div class="metric-row"><span class="metric-icon">📍</span><span>Punkty: <b>{data['pts_count']} szt.</b></span></div>
                    <div class="metric-row" style="color: #6c757d;"><span class="metric-icon">⏱️</span><span>Czas: <b>{int(data['time']//60)} min</b></span></div>
                </div>
                """, unsafe_allow_html=True)
                with st.expander("Lista punktów"):
                    st.dataframe(data['df'][['display_name']], use_container_width=True)
else:
    st.info("Wgraj KML (pamiętaj o wyborze STARTU i METY).")
