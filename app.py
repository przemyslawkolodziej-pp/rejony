import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
import re, math, json, requests, os, time, zlib, base64, datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import extra_streamlit_components as stx

# --- 1. KONFIGURACJA ---
SHEET_ID = "1mTMjUKoHNw-okxpYSAeLsVD7vdxYR1P-ZjelWt9IHAE" 

st.set_page_config(page_title="Optymalizator Tras", page_icon="🗺️", layout="wide")

# Funkcja bez cache - CookieManager musi być inicjowany przy każdym przebiegu
def get_cookie_manager():
    return stx.CookieManager(key="cookie_manager")

cookie_manager = get_cookie_manager()

# --- 2. INTEGRACJA Z GOOGLE SHEETS ---
def get_gspread_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_dict = dict(st.secrets["gcp_service_account"])
    raw_key = creds_dict["private_key"].replace("\\n", "\n").strip().strip('"').strip("'")
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds)

def compress_data(data_dict):
    json_str = json.dumps(data_dict, ensure_ascii=False, separators=(',', ':'))
    return base64.b64encode(zlib.compress(json_str.encode('utf-8'))).decode('utf-8')

def decompress_data(compressed_str):
    try:
        return json.loads(zlib.decompress(base64.b64decode(compressed_str)).decode('utf-8'))
    except:
        return json.loads(compressed_str)

def sync_save():
    if not SHEET_ID: return
    try:
        client = get_gspread_client()
        sheet = client.open_by_key(SHEET_ID)
        
        # Bazy
        l_sheet = sheet.worksheet("SavedLocations")
        l_sheet.clear()
        l_rows = [["Nazwa", "Adres"]] + [[str(n), str(a)] for n, a in st.session_state['saved_locations'].items()]
        l_sheet.update(values=l_rows, range_name='A1')
        
        # Projekty
        p_sheet = sheet.worksheet("Projects")
        p_sheet.clear()
        p_rows = [["Nazwa Projektu", "Dane JSON"]]
        for p_name, p_data in st.session_state['projects'].items():
            s = p_data.copy()
            if isinstance(s.get('data'), pd.DataFrame): s['data'] = s['data'].to_dict()
            if 'optimized_list' in s:
                s['optimized_list'] = [df.to_dict() if isinstance(df, pd.DataFrame) else df for df in s['optimized_list']]
            p_rows.append([str(p_name), compress_data(s)])
        p_sheet.update(values=p_rows, range_name='A1')
        st.toast("Zsynchronizowano! ✅")
    except Exception as e:
        st.error(f"Błąd zapisu: {e}")

def sync_load():
    if not SHEET_ID: return
    try:
        client = get_gspread_client()
        sheet = client.open_by_key(SHEET_ID)
        # Bazy
        loc_data = sheet.worksheet("SavedLocations").get_all_records()
        st.session_state['saved_locations'] = {row['Nazwa']: row['Adres'] for row in loc_data if 'Nazwa' in row}
        # Projekty
        proj_data = sheet.worksheet("Projects").get_all_records()
        l_projs = {}
        for row in proj_data:
            p_n, p_j = row.get('Nazwa Projektu'), row.get('Dane JSON')
            if p_n and p_j:
                c = decompress_data(p_j)
                if 'data' in c: c['data'] = pd.DataFrame(c['data'])
                if 'optimized_list' in c:
                    c['optimized_list'] = [pd.DataFrame(df) for df in c['optimized_list']]
                l_projs[p_n] = c
        st.session_state['projects'] = l_projs
    except: pass

# --- 3. INICJALIZACJA SESJI I LOGOWANIE ---
keys = {
    'authenticated': False, 'data': pd.DataFrame(), 'optimized_list': [], 
    'saved_locations': {}, 'projects': {}, 'start_coords': None, 
    'meta_coords': None, 'geometries': [], 'start_name': "Nie wybrano", 'meta_name': "Nie wybrano"
}
for k, v in keys.items():
    if k not in st.session_state: st.session_state[k] = v

# Pobieramy wszystkie ciasteczka naraz - to jest stabilniejsze
cookies = cookie_manager.get_all()
auth_val = cookies.get("authenticated_user")

# Debugging (opcjonalne - usuń po testach):
# st.write(f"DEBUG: Znalezione ciasteczka: {cookies}")

if auth_val == st.secrets.get("password") and not st.session_state['authenticated']:
    st.session_state['authenticated'] = True
    sync_load()
    st.rerun() # Wymuszamy odświeżenie po autologowaniu

# --- 4. STYLE ---
st.markdown("<style>div.stButton > button { border-radius: 8px; } button[kind='primary'] { background-color: #28a745 !important; color: white !important; }</style>", unsafe_allow_html=True)

# --- 5. POMOCNICZE ---
def get_folium_color(idx):
    return ['blue', 'red', 'green', 'orange', 'purple', 'cadetblue', 'darkred', 'darkblue', 'darkgreen', 'pink', 'lightblue'][idx % 11]

def get_lat_lng(address):
    try:
        loc = Nominatim(user_agent="optymalizator_v2").geocode(address, timeout=10)
        return {"lat": loc.latitude, "lng": loc.longitude} if loc else None
    except: return None

def get_math_dist(lat1, lon1, lat2, lon2): return math.sqrt((lat1-lat2)**2 + (lon1-lon2)**2)

def get_route_chunked(coords):
    geom, dist, time_s = [], 0, 0
    for i in range(0, len(coords) - 1, 39):
        chunk = coords[i : i + 40]
        try:
            r = requests.get(f"http://router.project-osrm.org/route/v1/driving/{';'.join([f'{c[1]},{c[0]}' for c in chunk])}?overview=full&geometries=geojson").json()
            if r['code'] == 'Ok':
                geom.extend(r['routes'][0]['geometry']['coordinates'])
                dist += r['routes'][0]['distance']; time_s += r['routes'][0]['duration']
        except: pass
    return geom, dist, time_s

def parse_kml(content, name):
    pts = []
    for pm in re.findall(r'<Placemark>(.*?)</Placemark>', content, re.DOTALL):
        n = re.search(r'<(?:name|display_name)>(.*?)</', pm)
        c = re.search(r'<coordinates>\s*([\d\.\-]+),\s*([\d\.\-]+)', pm)
        if c: pts.append({"display_name": n.group(1) if n else "Punkt", "lat": float(c.group(2)), "lng": float(c.group(1)), "source_file": name})
    return pd.DataFrame(pts)

# --- 6. SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Zarządzanie")
    
    with st.expander("📁 Projekty", expanded=True):
        p_in = st.text_input("Nazwa zapisu:")
        if st.button("💾 Zapisz Stan") and p_in:
            st.session_state['projects'][p_in] = {
                'data': st.session_state['data'].copy(), 'start_name': st.session_state['start_name'], 'meta_name': st.session_state['meta_name'],
                'start_coords': st.session_state['start_coords'], 'meta_coords': st.session_state['meta_coords'],
                'optimized_list': [df.copy() for df in st.session_state['optimized_list']], 'geometries': st.session_state['geometries']
            }
            sync_save(); st.rerun()
        if st.session_state['projects']:
            sel_p = st.selectbox("Otwórz:", ["---"] + sorted(st.session_state['projects'].keys()))
            if sel_p != "---":
                c1, c2 = st.columns([3, 1])
                if c1.button("📂 Otwórz"): st.session_state.update(st.session_state['projects'][sel_p]); st.rerun()
                if c2.button("🗑️", key=f"del_{sel_p}"):
                    del st.session_state['projects'][sel_p]; sync_save(); st.rerun()

    with st.expander("☁️ Rejony KML", expanded=False):
        up = st.file_uploader("Wgraj KML", type=['kml'], accept_multiple_files=True)
        if up and st.button("Wczytaj"):
            all_pts = [parse_kml(f.read().decode('utf-8'), f.name) for f in up]
            if all_pts: 
                st.session_state['data'] = pd.concat([st.session_state['data'], pd.concat(all_pts)], ignore_index=True).drop_duplicates()
                st.rerun()

    if not st.session_state['data'].empty:
        with st.expander("📂 Lista rejonów", expanded=True):
            for f in sorted(st.session_state['data']['source_file'].unique()):
                c1, c2 = st.columns([4, 1])
                c1.write(f"📄 {f}")
                if c2.button("🗑️", key=f"f_{f}"):
                    st.session_state['data'] = st.session_state['data'][st.session_state['data']['source_file']!=f]; st.rerun()

    with st.expander("🏠 Bazy", expanded=True):
        if st.session_state['saved_locations']:
            sel_b = st.selectbox("Wybierz bazę:", ["---"] + sorted(st.session_state['saved_locations'].keys()))
            if sel_b != "---":
                addr = st.session_state['saved_locations'][sel_b]
                c1, c2, c3 = st.columns(3)
                if c1.button("🏠", key=f"s_{sel_b}"): st.session_state.update({'start_name': sel_b, 'start_coords': get_lat_lng(addr)}); st.rerun()
                if c2.button("🏁", key=f"m_{sel_b}"): st.session_state.update({'meta_name': sel_b, 'meta_coords': get_lat_lng(addr)}); st.rerun()
                if c3.button("🗑️", key=f"x_{sel_b}"): del st.session_state['saved_locations'][sel_b]; sync_save(); st.rerun()
        with st.form("nb", clear_on_submit=True):
            n, a = st.text_input("Nazwa:"), st.text_input("Adres:")
            if st.form_submit_button("➕ Dodaj"):
                if n and a: st.session_state['saved_locations'][n]=a; sync_save(); st.rerun()

    if st.button("🔓 WYLOGUJ"):
        # Pobieramy aktualną listę ciasteczek, żeby sprawdzić czy klucz istnieje
        current_cookies = cookie_manager.get_all()
        
        # 1. Usuwamy ciasteczko tylko jeśli fizycznie istnieje
        if "authenticated_user" in current_cookies:
            try:
                cookie_manager.delete("authenticated_user")
            except Exception:
                pass # Ignorujemy błędy, jeśli usuwanie się nie powiodło
        
        # 2. Czyścimy stan sesji (to zadziała zawsze, niezależnie od ciasteczek)
        st.session_state['authenticated'] = False
        
        # 3. Czyścimy dane projektu dla bezpieczeństwa
        st.session_state['data'] = pd.DataFrame()
        st.session_state['optimized_list'] = []
        st.session_state['geometries'] = []
        
        # 4. Przeładowujemy stronę
        st.rerun()

# --- 7. PANEL GŁÓWNY ---
st.title("🗺️ Optymalizator Tras")

col1, col2 = st.columns(2)
col1.info(f"🏠 **START:** {st.session_state['start_name']}")
col2.info(f"🏁 **META:** {st.session_state['meta_name']}")

if not st.session_state['data'].empty:
    u_f = sorted(st.session_state['data']['source_file'].unique().tolist())
    v_f = st.multiselect("Widoczne rejony:", u_f, default=u_f)
    f_df = st.session_state['data'][st.session_state['data']['source_file'].isin(v_f)]
    
    cv1, cv2 = st.columns(2)
    show_pins = cv1.checkbox("Pokaż pinezki", value=True)
    mode = cv2.radio("Tryb:", ["Jedna trasa", "Oddzielne"], horizontal=True)

    if st.button("🚀 OBLICZ OPTYMALNE TRASY", type="primary", use_container_width=True):
        if not (st.session_state['start_coords'] and st.session_state['meta_coords']): st.error("Ustaw Start i Metę!")
        else:
            with st.spinner("Liczenie..."):
                st.session_state.update({'optimized_list': [], 'geometries': []})
                sc, mc = st.session_state['start_coords'], st.session_state['meta_coords']
                grps = [f_df] if mode == "Jedna trasa" else [f_df[f_df['source_file']==f] for f in f_df['source_file'].unique()]
                for idx, g in enumerate(grps):
                    if g.empty: continue
                    curr = {"lat": sc['lat'], "lng": sc['lng']}
                    route, unv = [curr], g.to_dict('records')
                    while unv:
                        nxt = min(unv, key=lambda x: get_math_dist(curr['lat'], curr['lng'], x['lat'], x['lng']))
                        route.append(nxt); curr = nxt; unv.remove(nxt)
                    route.append({"lat": mc['lat'], "lng": mc['lng'], "display_name": "META"})
                    geom, d, t = get_route_chunked([[r['lat'], r['lng']] for r in route])
                    st.session_state['optimized_list'].append(pd.DataFrame(route))
                    st.session_state['geometries'].append({"geom": geom, "color": get_folium_color(idx), "dist": d, "time": t, "name": g['source_file'].iloc[0] if mode != "Jedna trasa" else "Wszystkie", "pts": len(g)})
                st.rerun()

    m = folium.Map()
    sc, mc = st.session_state['start_coords'], st.session_state['meta_coords']
    bounds = [[sc['lat'], sc['lng']], [mc['lat'], mc['lng']]] if sc and mc else []
    if sc: folium.Marker([sc['lat'], sc['lng']], icon=folium.Icon(color='green', icon='home', prefix='fa')).add_to(m)
    if mc: folium.Marker([mc['lat'], mc['lng']], icon=folium.Icon(color='red', icon='flag', prefix='fa')).add_to(m)
    
    v_geoms = [g for g in st.session_state['geometries'] if mode == "Jedna trasa" or g['name'] in v_f]
    for g in v_geoms: folium.PolyLine([[c[1], c[0]] for c in g['geom']], color=g['color'], weight=5).add_to(m)
    if show_pins:
        f_cols = {f: get_folium_color(i) for i, f in enumerate(u_f)}
        for _, r in f_df.iterrows():
            folium.Marker([r['lat'], r['lng']], icon=folium.Icon(color=f_cols.get(r['source_file'], 'gray'), icon='circle', prefix='fa'), tooltip=r['display_name']).add_to(m)
            bounds.append([r['lat'], r['lng']])
    if bounds: m.fit_bounds(bounds)
    st_folium(m, width="100%", height=550)
    
    if st.session_state['geometries']:
        st.markdown("### 📊 Szczegóły")
        td, tt = 0, 0
        cols = st.columns(min(len(v_geoms), 4))
        for i, g in enumerate(v_geoms):
            with cols[i % 4]:
                st.metric(f"📍 {g['name']}", f"{g['dist']/1000:.2f} km")
                st.caption(f"⏱️ {int(g['time']//3600)}h {int((g['time']%3600)//60)}min | 🏠 {g.get('pts', 0)} pkt")
            td += g['dist']; tt += g['time']
        st.success(f"✅ RAZEM: {td/1000:.2f} km | Czas: {int(tt//3600)}h {int((tt%3600)//60)}min")
else:
    st.info("👈 Wgraj KML i wybierz bazy.")
