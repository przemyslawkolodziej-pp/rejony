import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
import re, math, json, requests, os, time, zlib, base64
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import extra_streamlit_components as stx  # Nowa biblioteka do ciasteczek

# --- 1. KONFIGURACJA ---
SHEET_ID = "1mTMjUKoHNw-okxpYSAeLsVD7vdxYR1P-ZjelWt9IHAE" 
st.set_page_config(page_title="Optymalizator Tras", page_icon="🗺️", layout="wide")

# Inicjalizacja managera ciasteczek
def get_cookie_manager():
    return stx.CookieManager()

cookie_manager = get_cookie_manager()

# --- 2. INTEGRACJA Z GOOGLE SHEETS (Funkcje pomocnicze) ---
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
        # Zapis lokalizacji
        l_sh = sheet.worksheet("SavedLocations")
        l_sh.clear()
        l_rows = [["Nazwa", "Adres"]] + [[n, a] for n, a in st.session_state['saved_locations'].items()]
        l_sh.update(values=l_rows, range_name='A1')
        # Zapis projektów
        p_sh = sheet.worksheet("Projects")
        p_sh.clear()
        p_rows = [["Nazwa Projektu", "Dane JSON"]]
        for p_n, p_d in st.session_state['projects'].items():
            s = p_d.copy()
            if isinstance(s.get('data'), pd.DataFrame): s['data'] = s['data'].to_dict()
            if 'optimized_list' in s:
                s['optimized_list'] = [df.to_dict() if isinstance(df, pd.DataFrame) else df for df in s['optimized_list']]
            p_rows.append([p_n, compress_data(s)])
        p_sh.update(values=p_rows, range_name='A1')
        st.toast("Zsynchronizowano! ✅")
    except Exception as e:
        st.error(f"Błąd sync: {e}")

def sync_load():
    if not SHEET_ID: return
    try:
        client = get_gspread_client()
        sheet = client.open_by_key(SHEET_ID)
        # Wczytaj lokalizacje
        loc_data = sheet.worksheet("SavedLocations").get_all_records()
        st.session_state['saved_locations'] = {r['Nazwa']: r['Adres'] for r in loc_data if 'Nazwa' in r}
        # Wczytaj projekty
        proj_data = sheet.worksheet("Projects").get_all_records()
        loaded = {}
        for r in proj_data:
            p_n, p_j = r.get('Nazwa Projektu'), r.get('Dane JSON')
            if p_n and p_j:
                c = decompress_data(p_j)
                if 'data' in c: c['data'] = pd.DataFrame(c['data'])
                if 'optimized_list' in c:
                    c['optimized_list'] = [pd.DataFrame(df) for df in c['optimized_list']]
                loaded[p_n] = c
        st.session_state['projects'] = loaded
    except: pass

# --- 3. LOGOWANIE I CIASTECZKA ---
# Sprawdzamy czy ciasteczko istnieje
auth_cookie = cookie_manager.get(cookie="authenticated_user")

# Inicjalizacja session_state
keys = {
    'authenticated': False, 'data': pd.DataFrame(), 'optimized_list': [], 
    'saved_locations': {}, 'projects': {}, 'start_coords': None, 
    'meta_coords': None, 'geometries': [], 'reset_counter': 0,
    'start_name': "Nie wybrano", 'meta_name': "Nie wybrano"
}
for k, v in keys.items():
    if k not in st.session_state: st.session_state[k] = v

# Logika autologowania
if auth_cookie == st.secrets.get("password") and not st.session_state['authenticated']:
    st.session_state['authenticated'] = True
    sync_load()

if not st.session_state['authenticated']:
    st.title("🔐 Logowanie")
    with st.form("login"):
        pwd = st.text_input("Hasło:", type="password")
        if st.form_submit_button("Zaloguj"):
            if pwd == st.secrets.get("password"):
                # Zapisujemy ciasteczko na 30 dni
                cookie_manager.set("authenticated_user", pwd, expires_at=time.time() + (30 * 24 * 3600))
                st.session_state['authenticated'] = True
                sync_load()
                st.rerun()
            else: st.error("❌ Błędne hasło")
    st.stop()

# --- 4. RESZTA KODU (SIDEBAR I MAPA) ---
st.markdown("""<style>
    div.stButton > button { border-radius: 8px; }
    button[kind="primary"] { background-color: #28a745 !important; color: white !important; }
</style>""", unsafe_allow_html=True)

# Pomocnicze funkcje GPS/OSRM
def get_lat_lng(addr):
    try:
        loc = Nominatim(user_agent="v140").geocode(addr, timeout=10)
        return {"lat": loc.latitude, "lng": loc.longitude} if loc else None
    except: return None

def get_math_dist(la1, lo1, la2, lo2): return math.sqrt((la1-la2)**2 + (lo1-lo2)**2)

def get_route_chunked(coords):
    geom, dist, time_s = [], 0, 0
    for i in range(0, len(coords)-1, 39):
        chunk = coords[i:i+40]
        try:
            r = requests.get(f"http://router.project-osrm.org/route/v1/driving/{';'.join([f'{c[1]},{c[0]}' for c in chunk])}?overview=full&geometries=geojson").json()
            if r['code']=='Ok':
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

def get_folium_color(idx):
    return ['blue', 'red', 'green', 'orange', 'purple', 'cadetblue', 'darkred', 'darkblue', 'darkgreen', 'pink', 'lightblue'][idx % 11]

# SIDEBAR
with st.sidebar:
    st.header("⚙️ Zarządzanie")
    
    # Zarządzanie projektami (z poprawką usuwania)
    with st.expander("📁 Projekty", expanded=True):
        p_in = st.text_input("Nazwa projektu do zapisu:")
        if st.button("💾 Zapisz Stan") and p_in:
            st.session_state['projects'][p_in] = {
                'data': st.session_state['data'].copy(), 'start_name': st.session_state['start_name'], 
                'meta_name': st.session_state['meta_name'], 'start_coords': st.session_state['start_coords'], 
                'meta_coords': st.session_state['meta_coords'], 'optimized_list': [df.copy() for df in st.session_state['optimized_list']], 
                'geometries': st.session_state['geometries']
            }
            sync_save(); st.rerun()
        
        if st.session_state['projects']:
            sel_p = st.selectbox("Otwórz Projekt:", ["---"] + sorted(st.session_state['projects'].keys()))
            if sel_p != "---":
                c1, c2 = st.columns([3, 1])
                if c1.button("📂 Otwórz"): st.session_state.update(st.session_state['projects'][sel_p]); st.rerun()
                if c2.button("🗑️", key=f"del_{sel_p}"):
                    del st.session_state['projects'][sel_p]
                    sync_save(); st.rerun()

    # Wczytywanie KML
    with st.expander("☁️ Dodaj Rejony", expanded=False):
        up = st.file_uploader("Pliki KML", type=['kml'], accept_multiple_files=True)
        if up and st.button("Wczytaj Pliki"):
            all_pts = [parse_kml(f.read().decode('utf-8'), f.name) for f in up]
            if all_pts:
                st.session_state['data'] = pd.concat([st.session_state['data'], pd.concat(all_pts)], ignore_index=True).drop_duplicates()
                st.rerun()

    # Bazy
    with st.expander("🏠 Bazy", expanded=True):
        if st.session_state['saved_locations']:
            b_list = sorted(st.session_state['saved_locations'].keys())
            sel_b = st.selectbox("Wybierz bazę:", ["---"] + b_list)
            if sel_b != "---":
                addr = st.session_state['saved_locations'][sel_b]
                c1, c2, c3 = st.columns(3)
                if c1.button("🏠", key=f"s_{sel_b}"):
                    st.session_state.update({'start_name': sel_b, 'start_coords': get_lat_lng(addr)}); st.rerun()
                if c2.button("🏁", key=f"m_{sel_b}"):
                    st.session_state.update({'meta_name': sel_b, 'meta_coords': get_lat_lng(addr)}); st.rerun()
                if c3.button("🗑️", key=f"x_{sel_b}"):
                    del st.session_state['saved_locations'][sel_b]; sync_save(); st.rerun()
        with st.form("new_base", clear_on_submit=True):
            nb_n, nb_a = st.text_input("Nazwa:"), st.text_input("Adres:")
            if st.form_submit_button("➕ Dodaj Bazę"):
                if nb_n and nb_a: st.session_state['saved_locations'][nb_n] = nb_a; sync_save(); st.rerun()

    if st.button("🔓 WYLOGUJ"):
        cookie_manager.delete("authenticated_user")
        st.session_state['authenticated'] = False
        st.rerun()

# PANEL GŁÓWNY
st.title("🗺️ Optymalizator Tras")

# Nagłówki Start/Meta
c_s, c_m = st.columns(2)
c_s.info(f"🏠 **START:** {st.session_state['start_name']}")
c_m.info(f"🏁 **META:** {st.session_state['meta_name']}")

if not st.session_state['data'].empty:
    u_files = sorted(st.session_state['data']['source_file'].unique().tolist())
    v_files = st.multiselect("Widoczne rejony:", u_files, default=u_files)
    f_df = st.session_state['data'][st.session_state['data']['source_file'].isin(v_files)]
    
    col_v1, col_v2 = st.columns(2)
    show_pins = col_v1.checkbox("Pokaż pinezki", value=True)
    mode = col_v2.radio("Tryb:", ["Jedna trasa", "Oddzielne"], horizontal=True)

    if st.button("🚀 OBLICZ OPTYMALNE TRASY", type="primary", use_container_width=True):
        if not (st.session_state['start_coords'] and st.session_state['meta_coords']):
            st.error("Ustaw Start i Metę!")
        else:
            with st.spinner("Liczenie..."):
                st.session_state.update({'optimized_list': [], 'geometries': []})
                sc, mc = st.session_state['start_coords'], st.session_state['meta_coords']
                groups = [f_df] if mode == "Jedna trasa" else [f_df[f_df['source_file']==f] for f in f_df['source_file'].unique()]
                for idx, group in enumerate(groups):
                    if group.empty: continue
                    curr = {"lat": sc['lat'], "lng": sc['lng']}
                    route, unv = [curr], group.to_dict('records')
                    while unv:
                        nxt = min(unv, key=lambda x: get_math_dist(curr['lat'], curr['lng'], x['lat'], x['lng']))
                        route.append(nxt); curr = nxt; unv.remove(nxt)
                    route.append({"lat": mc['lat'], "lng": mc['lng'], "display_name": "META"})
                    geom, d, t = get_route_chunked([[r['lat'], r['lng']] for r in route])
                    st.session_state['optimized_list'].append(pd.DataFrame(route))
                    st.session_state['geometries'].append({
                        "geom": geom, "color": get_folium_color(idx), "dist": d, "time": t, 
                        "name": group['source_file'].iloc[0] if mode != "Jedna trasa" else "Wszystkie", "pts": len(group)
                    })
                st.rerun()

    # Mapa
    m = folium.Map()
    sc, mc = st.session_state['start_coords'], st.session_state['meta_coords']
    bounds = [[sc['lat'], sc['lng']], [mc['lat'], mc['lng']]] if sc and mc else []
    if sc: folium.Marker([sc['lat'], sc['lng']], icon=folium.Icon(color='green', icon='home', prefix='fa')).add_to(m)
    if mc: folium.Marker([mc['lat'], mc['lng']], icon=folium.Icon(color='red', icon='flag', prefix='fa')).add_to(m)
    
    visible_geoms = [g for g in st.session_state['geometries'] if mode == "Jedna trasa" or g['name'] in v_files]
    for g in visible_geoms:
        folium.PolyLine([[c[1], c[0]] for c in g['geom']], color=g['color'], weight=5).add_to(m)
    if show_pins:
        f_colors = {f: get_folium_color(i) for i, f in enumerate(u_files)}
        for _, r in f_df.iterrows():
            folium.Marker([r['lat'], r['lng']], icon=folium.Icon(color=f_colors.get(r['source_file'], 'gray'), icon='circle', prefix='fa'), tooltip=r['display_name']).add_to(m)
            bounds.append([r['lat'], r['lng']])
    
    if bounds: m.fit_bounds(bounds)
    st_folium(m, width="100%", height=550)

    # Statystyki (Naprawiony KeyError: 'pts')
    if st.session_state['geometries']:
        st.markdown("### 📊 Szczegóły tras")
        td, tt = 0, 0
        cols = st.columns(min(len(visible_geoms), 4))
        for i, g in enumerate(visible_geoms):
            with cols[i % 4]:
                st.metric(f"📍 {g['name']}", f"{g['dist']/1000:.2f} km")
                st.caption(f"⏱️ {int(g['time']//3600)}h {int((g['time']%3600)//60)}min | 🏠 {g.get('pts', 0)} pkt")
            td += g['dist']; tt += g['time']
        st.success(f"✅ RAZEM: {td/1000:.2f} km | Szacowany czas: {int(tt//3600)}h {int((tt%3600)//60)}min")
else:
    st.info("👈 Wgraj KML i wybierz bazy z menu po lewej.")
