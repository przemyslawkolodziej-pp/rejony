import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
import re, math, json, requests, os, time, zlib, base64, hashlib, datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# --- 1. KONFIGURACJA ---
SHEET_ID = "1mTMjUKoHNw-okxpYSAeLsVD7vdxYR1P-ZjelWt9IHAE" 
st.set_page_config(page_title="Optymalizator Tras", page_icon="🗺️", layout="wide")

COLORS = ['#007bff', '#28a745', '#6f42c1', '#fd7e14', '#20c997', '#e83e8c', '#dc3545', '#ffc107']
COLOR_MAP = {
    '#007bff': 'blue', '#28a745': 'green', '#6f42c1': 'purple', '#fd7e14': 'orange',
    '#20c997': 'cadetblue', '#e83e8c': 'pink', '#dc3545': 'red', '#ffc107': 'lightgray'
}

st.markdown("""
    <style>
        .stButton>button { border-radius: 8px; }
        .metric-card { 
            background-color: #f8f9fa; padding: 12px; border-radius: 10px; 
            box-shadow: 2px 2px 5px rgba(0,0,0,0.05); margin-bottom: 15px; border-left: 8px solid;
        }
        .metric-title { font-weight: bold; color: #495057; margin-bottom: 5px; font-size: 1rem; }
        .metric-row { display: flex; align-items: center; gap: 8px; margin-bottom: 2px; color: #333; font-size: 0.9rem; font-weight: 500; }
    </style>
""", unsafe_allow_html=True)

# --- 2. FUNKCJE LOGIKI ---
def get_lat_lng(addr):
    try:
        loc = Nominatim(user_agent="v225_opt").geocode(addr, timeout=10)
        return {"lat": loc.latitude, "lng": loc.longitude} if loc else None
    except: return None

def optimize_route(df_points, start_coords, meta_coords, color_idx, start_label="START", meta_label="META"):
    if df_points.empty or not start_coords or not meta_coords: return None
    
    start_p = {"display_name": f"🏠 {start_label}", "lat": start_coords['lat'], "lng": start_coords['lng'], "NR_REJONU": "-", "PNA_DORECZ": "-"}
    meta_p = {"display_name": f"🏁 {meta_label}", "lat": meta_coords['lat'], "lng": meta_coords['lng'], "NR_REJONU": "-", "PNA_DORECZ": "-"}
    
    curr_p = start_p
    route = [curr_p]
    unv = df_points.to_dict('records')
    
    while unv:
        nxt = min(unv, key=lambda x: math.sqrt((curr_p['lat']-x['lat'])**2 + (curr_p['lng']-x['lng'])**2))
        route.append(nxt); curr_p = nxt; unv.remove(nxt)
        
    route.append(meta_p)
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
def get_gspread_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds)

def sync_save():
    try:
        client = get_gspread_client()
        sheet = client.open_by_key(SHEET_ID)
        l_sh = sheet.worksheet("SavedLocations"); l_sh.clear()
        l_sh.update(values=[["Nazwa", "Adres"]] + [[n, a] for n, a in st.session_state['saved_locations'].items()], range_name='A1')
        p_sh = sheet.worksheet("Projects"); p_sh.clear()
        p_rows = [["Nazwa Projektu", "Dane JSON"]]
        for p_n, p_d in st.session_state['projects'].items():
            s = p_d.copy()
            if isinstance(s.get('data'), pd.DataFrame): s['data'] = s['data'].to_dict()
            if 'optimized_cache' in s:
                clean_cache = {}
                for k, v in s['optimized_cache'].items():
                    c_v = v.copy()
                    if 'geom' in c_v: del c_v['geom']
                    if 'df' in c_v and isinstance(c_v['df'], pd.DataFrame): c_v['df'] = c_v['df'].to_dict()
                    clean_cache[k] = c_v
                s['optimized_cache'] = clean_cache
            compressed = base64.b64encode(zlib.compress(json.dumps(s).encode())).decode()
            if len(compressed) < 49000: p_rows.append([str(p_n), compressed])
        p_sh.update(values=p_rows, range_name='A1')
        st.toast("Zsynchronizowano! ✅")
    except Exception as e: st.error(f"Błąd zapisu: {str(e)}")

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
                    loaded[p_n] = c
                except: continue
        st.session_state['projects'] = loaded
    except: pass

# --- 3. MODALE ---
@st.dialog("Zarządzaj Projektami")
def modal_projects():
    tab_open, tab_save = st.tabs(["📂 Otwórz", "💾 Zapisz"])
    proj_list = sorted([{"name": k, "label": f"{k} ({v.get('last_modified','?')})"} for k,v in st.session_state['projects'].items()], key=lambda x: x['name'])
    with tab_open:
        if not proj_list: st.info("Brak projektów.")
        else:
            sel = st.selectbox("Otwórz:", options=range(len(proj_list)), format_func=lambda x: proj_list[x]['label'])
            if st.button("Wczytaj i przelicz", use_container_width=True):
                p_data = st.session_state['projects'][proj_list[sel]['name']]
                st.session_state.update(p_data)
                if not st.session_state['data'].empty and st.session_state['start_coords']:
                    new_cache = {}
                    all_files = sorted(st.session_state['data']['source_file'].unique().tolist())
                    for i, f_name in enumerate(all_files):
                        df_f = st.session_state['data'][st.session_state['data']['source_file'] == f_name]
                        new_cache[f_name] = optimize_route(df_f, st.session_state['start_coords'], st.session_state['meta_coords'], i, st.session_state['start_name'], st.session_state['meta_name'])
                    st.session_state['optimized_cache'] = new_cache
                st.session_state['map_bounds'] = None; st.rerun()
    with tab_save:
        n = st.text_input("Nazwa:", value=st.session_state.get('last_loaded_project_name', ""))
        if n and st.button("Zapisz projekt", use_container_width=True):
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            st.session_state['projects'][n] = {'data': st.session_state['data'].copy(), 'start_name': st.session_state['start_name'], 'meta_name': st.session_state['meta_name'], 'start_coords': st.session_state['start_coords'], 'meta_coords': st.session_state['meta_coords'], 'optimized_cache': st.session_state['optimized_cache'].copy(), 'last_modified': now_str}
            sync_save(); st.rerun()

@st.dialog("Dodaj KML")
def modal_add_kml():
    if not st.session_state['start_coords'] or not st.session_state['meta_coords']:
        st.error("Wybierz START i METĘ!"); return
    up = st.file_uploader("Wgraj pliki KML", accept_multiple_files=True)
    if st.button("Oblicz i dodaj", use_container_width=True) and up:
        for f in up:
            content = f.read().decode('utf-8')
            pts = []
            for pm in re.findall(r'<Placemark>(.*?)</Placemark>', content, re.DOTALL):
                coords = re.search(r'<coordinates>\s*([\d\.\-]+),\s*([\d\.\-]+)', pm)
                
                def get_val(key):
                    m = re.search(rf'<Data name="{key}">\s*<value>(.*?)</value>', pm, re.DOTALL)
                    return m.group(1).strip() if m else ""

                rej = get_val("NR_REJONU") or get_val("JEDNOSTKA_DOR")
                if rej and ".0" in str(rej): rej = str(rej).replace(".0", "")
                
                pna = get_val("PNA_DORECZ")
                typ_prz = get_val("TYP_PRZ")
                format_prz = get_val("FORMAT")
                powiat = get_val("Powiat")
                gmina = get_val("Gmina")
                miejsc = get_val("MIEJSC_DORECZ")
                ulica = get_val("ULICA_DORECZ")
                nr_dom = get_val("NR_DOM_DORECZ")

                full_adr = f"{ulica} {nr_dom}".strip()
                if not ulica or full_adr == "" or full_adr == "None":
                    name_t = re.search(r'<name>(.*?)</name>', pm)
                    full_adr = name_t.group(1) if name_t else "Punkt"

                if coords:
                    pts.append({
                        "display_name": full_adr, "lat": float(coords.group(2)), "lng": float(coords.group(1)), 
                        "source_file": f.name, "NR_REJONU": rej, "PNA_DORECZ": pna,
                        "TYP_PRZ": typ_prz, "FORMAT": format_prz, "Powiat": powiat,
                        "Gmina": gmina, "MIEJSC_DORECZ": miejsc, "ULICA_DORECZ": ulica, "NR_DOM_DORECZ": nr_dom
                    })
            if pts:
                df_new = pd.DataFrame(pts)
                st.session_state['data'] = pd.concat([st.session_state['data'], df_new], ignore_index=True).drop_duplicates()
                all_f = sorted(st.session_state['data']['source_file'].unique().tolist())
                st.session_state['optimized_cache'][f.name] = optimize_route(df_new, st.session_state['start_coords'], st.session_state['meta_coords'], all_f.index(f.name), st.session_state['start_name'], st.session_state['meta_name'])
        st.session_state['map_bounds'] = None; st.rerun()

# --- 4. INICJALIZACJA ---
if 'initialized' not in st.session_state:
    st.session_state.update({'initialized': True, 'authenticated': False, 'data': pd.DataFrame(), 'optimized_cache': {}, 'saved_locations': {}, 'projects': {}, 'start_coords': None, 'meta_coords': None, 'start_name': "---", 'meta_name': "---", 'last_loaded_project_name': "", 'map_bounds': None})

def check_auth():
    if st.session_state.get('authenticated'): return True
    if st.query_params.get("token") == hashlib.sha256(st.secrets.get("password", "").encode()).hexdigest():
        st.session_state['authenticated'] = True; return True
    return False

if check_auth() and not st.session_state['projects']: sync_load()
if not check_auth():
    st.title("🔐 Logowanie")
    with st.form("l"):
        pwd = st.text_input("Hasło:", type="password")
        if st.form_submit_button("Zaloguj"):
            if pwd == st.secrets.get("password"):
                st.query_params["token"] = hashlib.sha256(pwd.encode()).hexdigest()
                st.session_state['authenticated'] = True; sync_load(); st.rerun()
    st.stop()

# --- 5. INTERFEJS GÓRNY ---
c = st.columns([1.5, 1.2, 1.2, 1.2, 1.2, 1])
if c[0].button("📁 Projekty", use_container_width=True): modal_projects()
if c[1].button("📎 Dodaj KML", use_container_width=True): modal_add_kml()
if c[2].button("🏠 Bazy", use_container_width=True):
    @st.dialog("Bazy")
    def modal_bases():
        t1, t2 = st.tabs(["➕ Dodaj", "🗑️ Usuń"])
        with t1:
            n, a = st.text_input("Nazwa:"), st.text_input("Adres:")
            if st.button("Dodaj", use_container_width=True) and n and a: st.session_state['saved_locations'][n]=a; sync_save(); st.rerun()
        with t2:
            if st.session_state['saved_locations']:
                sel = st.selectbox("Wybierz:", sorted(st.session_state['saved_locations'].keys()))
                if st.button("Usuń", type="primary", use_container_width=True): del st.session_state['saved_locations'][sel]; sync_save(); st.rerun()
    modal_bases()
if c[3].button("🗑️ Wyczyść", use_container_width=True):
    st.session_state.update({'data': pd.DataFrame(), 'optimized_cache': {}, 'start_name': "---", 'meta_name': "---", 'start_coords': None, 'meta_coords': None, 'last_loaded_project_name': "", 'map_bounds': None})
    st.rerun()
if c[4].button("🔓 Wyloguj", use_container_width=True): st.query_params.clear(); st.session_state.clear(); st.rerun()

st.divider()

bl = sorted(list(st.session_state['saved_locations'].keys()))
c1, c2 = st.columns(2)
with c1:
    s_s = st.selectbox("🏠 START:", ["---"] + bl, index=(bl.index(st.session_state['start_name'])+1 if st.session_state['start_name'] in bl else 0))
    if s_s != st.session_state['start_name']:
        st.session_state['start_name'] = s_s
        st.session_state['start_coords'] = get_lat_lng(st.session_state['saved_locations'][s_s]) if s_s != "---" else None
        st.session_state['map_bounds'] = None; st.rerun()
with c2:
    m_s = st.selectbox("🏁 META:", ["---"] + bl, index=(bl.index(st.session_state['meta_name'])+1 if st.session_state['meta_name'] in bl else 0))
    if m_s != st.session_state['meta_name']:
        st.session_state['meta_name'] = m_s
        st.session_state['meta_coords'] = get_lat_lng(st.session_state['saved_locations'][m_s]) if m_s != "---" else None
        st.session_state['map_bounds'] = None; st.rerun()

# --- 6. GŁÓWNA SEKCJA MAPY ---
if not st.session_state['data'].empty:
    all_f = sorted(st.session_state['data']['source_file'].unique().tolist())
    
    # WYBÓR TRYBU TWORZENIA TRASY (Zgodnie z Twoją treścią i formatem radio)
    route_mode = st.radio(
        "Wybór trybu tworzenia trasy:", 
        ["Jedna trasa (punkty ze wszystkich rejonów razem)", "Oddzielne trasy (punkty dla każdego rejonu oddzielnie)"],
        horizontal=True,
        index=1
    )

    col_list, col_main = st.columns([1, 3.5])
    v_f = []
    with col_list:
        st.markdown("### Rejony")
        with st.container(height=550):
            for r_n in all_f:
                if st.checkbox(r_n, value=True, key=f"v_{r_n}"): v_f.append(r_n)
                st.divider()

    with col_main:
        show_pins = st.checkbox("Pokaż pinezki", value=True)
        m = folium.Map()
        active_bounds = []
        
        # Bazy
        if st.session_state['start_coords']:
            folium.Marker([st.session_state['start_coords']['lat'], st.session_state['start_coords']['lng']], icon=folium.Icon(color='green', icon='play', prefix='fa'), tooltip=st.session_state['start_name']).add_to(m)
            active_bounds.append([st.session_state['start_coords']['lat'], st.session_state['start_coords']['lng']])
        if st.session_state['meta_coords']:
            folium.Marker([st.session_state['meta_coords']['lat'], st.session_state['meta_coords']['lng']], icon=folium.Icon(color='red', icon='stop', prefix='fa'), tooltip=st.session_state['meta_name']).add_to(m)
            active_bounds.append([st.session_state['meta_coords']['lat'], st.session_state['meta_coords']['lng']])
            
        active_routes = {}
        for r_n in v_f:
            cache = st.session_state['optimized_cache'].get(r_n)
            if cache and 'geom' in cache:
                folium.PolyLine([[c[1], c[0]] for c in cache['geom']], color=cache['color'], weight=5).add_to(m)
                active_routes[r_n] = cache
                if show_pins:
                    f_color = COLOR_MAP.get(cache['color'], 'blue')
                    pts = st.session_state['data'][st.session_state['data']['source_file'] == r_n]
                    for _, r in pts.iterrows():
                        # OPIS PINEZKI ZGODNY Z WYMAGANIAMI
                        html = f"""
                        <div style='min-width:200px; font-size:12px;'>
                            <b>Przesyłka: {r.get('TYP_PRZ','-')} (Format {r.get('FORMAT','-')})</b><br>
                            <b>Rejon:</b> {r.get('NR_REJONU','-')}<br>
                            <b>PNA:</b> {r.get('PNA_DORECZ','-')}<br>
                            <b>Powiat:</b> {r.get('Powiat','-')}<br>
                            <b>Gmina:</b> {r.get('Gmina','-')}<br>
                            <b>Miejscowość:</b> {r.get('MIEJSC_DORECZ','-')}<br>
                            <b>Adres:</b> {r.get('ULICA_DORECZ','-')} {r.get('NR_DOM_DORECZ','-')}
                        </div>
                        """
                        folium.Marker([r['lat'], r['lng']], icon=folium.Icon(color=f_color), popup=folium.Popup(html, max_width=300)).add_to(m)
                        active_bounds.append([r['lat'], r['lng']])

        if active_bounds and st.session_state['map_bounds'] is None:
            st.session_state['map_bounds'] = active_bounds; m.fit_bounds(active_bounds)
        elif st.session_state['map_bounds']: m.fit_bounds(st.session_state['map_bounds'])
        st_folium(m, width="100%", height=600, key="main_map")

    # --- PODSUMOWANIE I TABELE NA DOLE ---
    if active_routes:
        st.markdown("### 📊 Podsumowanie tras")
        r_names = list(active_routes.keys())
        for i in range(0, len(r_names), 3):
            m_cols = st.columns(3)
            for j in range(3):
                if i + j < len(r_names):
                    name = r_names[i + j]
                    data = active_routes[name]
                    with m_cols[j]:
                        st.markdown(f"""
                            <div class="metric-card" style="border-left-color: {data['color']};">
                                <div class="metric-title">📍 {name}</div>
                                <div class="metric-row">📏 {data['dist']/1000:.2f} km</div>
                                <div class="metric-row">⏱️ {int(data['time']//60)} min</div>
                                <div class="metric-row">📦 Punkty: {data['pts_count']}</div>
                            </div>
                        """, unsafe_allow_html=True)

        st.divider()
        st.markdown("### 📝 Harmonogramy (Listy punktów)")
        for name in r_names:
            data = active_routes[name]
            with st.expander(f"Rozwiń listę punktów dla rejonu: {name}"):
                df_v = data['df'].copy()
                cols = [c for c in ['display_name', 'NR_REJONU', 'PNA_DORECZ', 'MIEJSC_DORECZ', 'TYP_PRZ'] if c in df_v.columns]
                st.dataframe(df_v[cols], use_container_width=True, hide_index=True)
else:
    st.info("Wgraj pliki KML, aby rozpocząć optymalizację.")
