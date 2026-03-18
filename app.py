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

# Custom CSS - Wymuszenie kolorów na Multiselect, Checkbox i Radio
st.markdown(f"""
    <style>
        .stButton>button {{ border-radius: 8px; }}
        
        /* 1. Przycisk Primary (Optymalizacja) */
        div.stButton > button[kind="primary"] {{
            background-color: #007bff !important;
            border-color: #007bff !important;
        }}

        /* 2. Multiselect - Pigułki (Tagi) */
        span[data-baseweb="tag"] {{
            background-color: #007bff !important;
            color: white !important;
        }}
        
        /* 3. Checkbox (Pokaż pinezki) - kolor po zaznaczeniu */
        div[data-testid="stCheckbox"] input[checked] + div {{
            background-color: #007bff !important;
        }}
        
        /* 4. Radio Buttons - kropka wyboru */
        div[role="radiogroup"] div[data-baseweb="radio"] div[size] {{
            background-color: #007bff !important;
        }}
        
        /* Karty podsumowania */
        .metric-card {{
            background-color: #f8f9fa;
            padding: 15px;
            border-radius: 10px;
            box-shadow: 2px 2px 5px rgba(0,0,0,0.05);
            margin-bottom: 10px;
            border-left-width: 8px;
            border-left-style: solid;
        }}
        .metric-title {{ font-weight: bold; color: #495057; margin-bottom: 5px; }}
        .metric-value {{ font-size: 1.1rem; color: #333; font-weight: bold; }}
    </style>
""", unsafe_allow_html=True)

# --- 2. FUNKCJE POMOCNICZE (BEZ ZMIAN) ---
def generate_session_token(password):
    return hashlib.sha256(password.encode()).hexdigest()

def check_auth():
    if st.session_state.get('authenticated'): return True
    params = st.query_params
    if "token" in params:
        if params["token"] == generate_session_token(st.secrets.get("password", "")):
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
        l_rows = [["Nazwa", "Adres"]] + [[str(n), str(a)] for n, a in st.session_state['saved_locations'].items()]
        l_sh.update(values=l_rows, range_name='A1')
        p_sh = sheet.worksheet("Projects")
        p_sh.clear()
        p_rows = [["Nazwa Projektu", "Dane JSON"]]
        for p_n, p_d in st.session_state['projects'].items():
            s = p_d.copy()
            if isinstance(s.get('data'), pd.DataFrame): s['data'] = s['data'].to_dict()
            if 'optimized_list' in s:
                s['optimized_list'] = [df.to_dict() if isinstance(df, pd.DataFrame) else df for df in s['optimized_list']]
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
                    if 'optimized_list' in c: c['optimized_list'] = [pd.DataFrame(df) for df in c['optimized_list']]
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
    n = st.text_input("Nazwa projektu:")
    if st.button("Zapisz") and n:
        st.session_state['projects'][n] = {
            'data': st.session_state['data'].copy(), 'start_name': st.session_state['start_name'], 'meta_name': st.session_state['meta_name'],
            'start_coords': st.session_state['start_coords'], 'meta_coords': st.session_state['meta_coords'],
            'optimized_list': [df.copy() for df in st.session_state['optimized_list']], 'geometries': st.session_state['geometries']
        }
        sync_save(); st.rerun()

@st.dialog("Dodaj KML")
def modal_add_kml():
    up = st.file_uploader("Dodaj pliki KML", type=['kml'], accept_multiple_files=True)
    if st.button("Wczytaj") and up:
        all_pts = []
        for f in up:
            content = f.read().decode('utf-8')
            pts = []
            for pm in re.findall(r'<Placemark>(.*?)</Placemark>', content, re.DOTALL):
                n = re.search(r'<(?:name|display_name)>(.*?)</', pm)
                c = re.search(r'<coordinates>\s*([\d\.\-]+),\s*([\d\.\-]+)', pm)
                if c: pts.append({"display_name": n.group(1) if n else "Punkt", "lat": float(c.group(2)), "lng": float(c.group(1)), "source_file": f.name})
            all_pts.append(pd.DataFrame(pts))
        if all_pts:
            st.session_state['data'] = pd.concat([st.session_state['data'], pd.concat(all_pts)], ignore_index=True).drop_duplicates()
            st.rerun()

@st.dialog("Usuń KML")
def modal_remove_kml():
    if st.session_state['data'].empty: return
    u_f = sorted(st.session_state['data']['source_file'].unique())
    to_del = st.multiselect("Wybierz rejon:", u_f)
    if st.button("Usuń"):
        st.session_state['data'] = st.session_state['data'][~st.session_state['data']['source_file'].isin(to_del)]
        st.rerun()

@st.dialog("Dodaj nową bazę")
def modal_add_base():
    n, a = st.text_input("Nazwa:"), st.text_input("Adres:")
    if st.button("Dodaj") and n and a:
        st.session_state['saved_locations'][n]=a; sync_save(); st.rerun()

# --- 4. INICJALIZACJA ---
if 'initialized' not in st.session_state:
    st.session_state.update({
        'initialized': True, 'authenticated': False, 'data': pd.DataFrame(), 
        'optimized_list': [], 'saved_locations': {}, 'projects': {}, 
        'start_coords': None, 'meta_coords': None, 'geometries': [],
        'start_name': "---", 'meta_name': "---"
    })

if not check_auth():
    st.title("🔐 Logowanie")
    with st.form("l"):
        p = st.text_input("Hasło:", type="password")
        if st.form_submit_button("Zaloguj"):
            if p == st.secrets.get("password"):
                st.query_params["token"] = generate_session_token(p)
                st.session_state['authenticated'] = True; sync_load(); st.rerun()
    st.stop()

# --- 5. NAWIGACJA ---
with st.container():
    c = st.columns([1, 1, 1.8, 1.2, 1.2, 1.2, 1.2])
    if c[0].button("📂 Otwórz", use_container_width=True): modal_open_project()
    if c[1].button("💾 Zapisz", use_container_width=True): modal_save_project()
    if c[2].button("➕ Zapisz jako Nowy", use_container_width=True): modal_save_project()
    if c[3].button("📎 Dodaj KML", use_container_width=True): modal_add_kml()
    if c[4].button("❌ Usuń KML", use_container_width=True): modal_remove_kml()
    if c[5].button("🏠 Dodaj Bazę", use_container_width=True): modal_add_base()
    if c[6].button("🗑️ Wyczyść", use_container_width=True):
        st.session_state.update({'data': pd.DataFrame(), 'optimized_list': [], 'geometries': [], 'start_name': "---", 'meta_name': "---", 'start_coords': None, 'meta_coords': None})
        st.rerun()

st.markdown("---")

# --- 6. WYBÓR PUNKTÓW ---
def get_lat_lng(addr):
    try:
        loc = Nominatim(user_agent="v189_opt").geocode(addr, timeout=10)
        return {"lat": loc.latitude, "lng": loc.longitude} if loc else None
    except: return None

bases = sorted(list(st.session_state['saved_locations'].keys()))
c1, c2 = st.columns(2)
with c1:
    s_sel = st.selectbox("🏠 WYBIERZ START:", ["---"] + bases, index=0)
    if s_sel != st.session_state['start_name']:
        st.session_state['start_name'] = s_sel
        st.session_state['start_coords'] = get_lat_lng(st.session_state['saved_locations'][s_sel]) if s_sel != "---" else None
        st.rerun()
with c2:
    m_sel = st.selectbox("🏁 WYBIERZ METĘ:", ["---"] + bases, index=0)
    if m_sel != st.session_state['meta_name']:
        st.session_state['meta_name'] = m_sel
        st.session_state['meta_coords'] = get_lat_lng(st.session_state['saved_locations'][m_sel]) if m_sel != "---" else None
        st.rerun()

# --- 7. LOGIKA OBLICZEŃ I MAPA ---
if not st.session_state['data'].empty:
    u_f = sorted(st.session_state['data']['source_file'].unique().tolist())
    v_f = st.multiselect("Wybrane rejony:", u_f, default=u_f)
    f_df = st.session_state['data'][st.session_state['data']['source_file'].isin(v_f)]
    
    cv1, cv2 = st.columns(2)
    show_pins = cv1.checkbox("Pokaż pinezki", value=True)
    mode = cv2.radio("Tryb:", ["Jedna trasa", "Oddzielne"], horizontal=True, index=1)

    # LOGIKA PRZYCISKU (Wyszarzony + Sugestia treści)
    not_ready = st.session_state['start_name'] == "---" or st.session_state['meta_name'] == "---"
    btn_label = "OBLICZ OPTYMALNE TRASY" if not not_ready else "WYBIERZ START I METĘ, ABY OBLICZYĆ"
    
    if st.button(btn_label, type="primary", use_container_width=True, disabled=not_ready):
        with st.spinner("Optymalizacja..."):
            st.session_state.update({'optimized_list': [], 'geometries': []})
            sc, mc = st.session_state['start_coords'], st.session_state['meta_coords']
            grps = [f_df] if mode == "Jedna trasa" else [f_df[f_df['source_file']==f] for f in f_df['source_file'].unique() if f in v_f]
            
            single_color = "#007bff"
            if mode == "Jedna trasa" and not f_df.empty:
                counts = f_df['source_file'].value_counts()
                main_rejon = counts.idxmax()
                single_color = COLORS[u_f.index(main_rejon) % len(COLORS)]

            for idx, g in enumerate(grps):
                if g.empty: continue
                curr_p = {"lat": sc['lat'], "lng": sc['lng']}
                route, unv = [curr_p], g.to_dict('records')
                while unv:
                    nxt = min(unv, key=lambda x: math.sqrt((curr_p['lat']-x['lat'])**2 + (curr_p['lng']-x['lng'])**2))
                    route.append(nxt); curr_p = nxt; unv.remove(nxt)
                route.append({"display_name": "META", "lat": mc['lat'], "lng": mc['lng']})
                
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
                
                rejon_name = g['source_file'].iloc[0]
                rejon_idx = u_f.index(rejon_name)
                final_color = single_color if mode == "Jedna trasa" else COLORS[rejon_idx % len(COLORS)]

                st.session_state['optimized_list'].append(pd.DataFrame(route))
                st.session_state['geometries'].append({
                    "geom": geom, "color": final_color, "dist": dist, "time": dur, 
                    "name": rejon_name if mode != "Jedna trasa" else "Wszystkie", 
                    "pts_count": len(g)
                })
            st.rerun()

    m = folium.Map()
    bounds = []
    if st.session_state['start_coords']:
        bounds.append([st.session_state['start_coords']['lat'], st.session_state['start_coords']['lng']])
        folium.Marker(bounds[-1], icon=folium.Icon(color='green', icon='play', prefix='fa')).add_to(m)
    if st.session_state['meta_coords']:
        bounds.append([st.session_state['meta_coords']['lat'], st.session_state['meta_coords']['lng']])
        folium.Marker(bounds[-1], icon=folium.Icon(color='red', icon='stop', prefix='fa')).add_to(m)
    
    for g in st.session_state['geometries']:
        folium.PolyLine([[c[1], c[0]] for c in g['geom']], color=g['color'], weight=5, opacity=0.8).add_to(m)
    
    if show_pins:
        for _, r in f_df.iterrows():
            r_idx = u_f.index(r['source_file'])
            p_color = COLORS[r_idx % len(COLORS)]
            folium.CircleMarker([r['lat'], r['lng']], radius=6, color=p_color, fill=True, fill_color=p_color, fill_opacity=0.7, tooltip=r['display_name']).add_to(m)
            bounds.append([r['lat'], r['lng']])
    
    if bounds: m.fit_bounds(bounds)
    st_folium(m, width="100%", height=550)

    if st.session_state['geometries']:
        st.markdown("### 📊 Szczegóły rejonów")
        cols = st.columns(min(len(st.session_state['geometries']), 3))
        for idx, g in enumerate(st.session_state['geometries']):
            pts = g.get('pts_count', len(st.session_state['optimized_list'][idx]) - 2 if idx < len(st.session_state['optimized_list']) else "?")
            with cols[idx % 3]:
                st.markdown(f"""
                <div class="metric-card" style="border-left-color: {g['color']};">
                    <div class="metric-title">📍 {g['name']}</div>
                    <div class="metric-value">Dystans: {g['dist']/1000:.2f} km</div>
                    <div class="metric-value">Punkty: {pts} szt.</div>
                    <div style="color: #6c757d;">⏱️ Czas: {int(g['time']//60)} min</div>
                </div>
                """, unsafe_allow_html=True)
                with st.expander("Lista punktów"):
                    if idx < len(st.session_state['optimized_list']):
                        st.dataframe(st.session_state['optimized_list'][idx][['display_name']], use_container_width=True)
else:
    st.info("Wgraj KML i wybierz bazy.")
