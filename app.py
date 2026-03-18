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
        
        # Zapis BAZ (SavedLocations)
        loc_sheet = sheet.worksheet("SavedLocations")
        loc_sheet.clear()
        loc_rows = [["Nazwa", "Adres"]] + [[n, a] for n, a in st.session_state['saved_locations'].items()]
        loc_sheet.update(values=loc_rows, range_name='A1')
        
        # Zapis PROJEKTÓW (Projects)
        proj_sheet = sheet.worksheet("Projects")
        proj_sheet.clear()
        p_rows = [["Nazwa Projektu", "Dane JSON"]]
        for p_name, p_data in st.session_state['projects'].items():
            s = p_data.copy()
            if isinstance(s.get('data'), pd.DataFrame): s['data'] = s['data'].to_dict()
            if 'optimized_list' in s:
                s['optimized_list'] = [df.to_dict() if isinstance(df, pd.DataFrame) else df for df in s['optimized_list']]
            p_rows.append([p_name, compress_data(s)])
        proj_sheet.update(values=p_rows, range_name='A1')
        st.toast("Zsynchronizowano z chmurą! ✅")
    except Exception as e:
        st.error(f"Błąd synchronizacji: {e}")

def sync_load():
    if not SHEET_ID: return
    try:
        client = get_gspread_client()
        sheet = client.open_by_key(SHEET_ID)
        
        # Wczytanie BAZ
        loc_data = sheet.worksheet("SavedLocations").get_all_records()
        st.session_state['saved_locations'] = {r['Nazwa']: r['Adres'] for r in loc_data if 'Nazwa' in r}
        
        # Wczytanie PROJEKTÓW
        proj_data = sheet.worksheet("Projects").get_all_records()
        loaded_projs = {}
        for r in proj_data:
            p_name, p_json = r.get('Nazwa Projektu'), r.get('Dane JSON')
            if p_name and p_json:
                c = decompress_data(p_json)
                if 'data' in c: c['data'] = pd.DataFrame(c['data'])
                if 'optimized_list' in c:
                    c['optimized_list'] = [pd.DataFrame(df) for df in c['optimized_list']]
                loaded_projs[p_name] = c
        st.session_state['projects'] = loaded_projs
    except: pass

# --- 3. INICJALIZACJA SESJI ---
keys = {
    'authenticated': False, 'data': pd.DataFrame(), 'optimized_list': [], 
    'saved_locations': {}, 'projects': {}, 'start_coords': None, 
    'meta_coords': None, 'geometries': [], 'reset_counter': 0,
    'start_name': "Nie wybrano", 'meta_name': "Nie wybrano"
}
for k, v in keys.items():
    if k not in st.session_state: st.session_state[k] = v

# --- LOGOWANIE ---
if not st.session_state['authenticated']:
    st.title("🔐 Logowanie")
    with st.form("login"):
        pwd = st.text_input("Hasło:", type="password")
        if st.form_submit_button("Zaloguj"):
            if pwd == st.secrets.get("password"):
                st.session_state['authenticated'] = True
                sync_load() # <--- KLUCZ: Przywracamy dane z Google Sheets zaraz po wpisaniu hasła
                st.rerun()
            else: st.error("❌ Błędne hasło")
    st.stop()

# --- 4. STYLE ---
st.markdown("""<style>
    div.stButton > button { border-radius: 8px; }
    button[kind="primary"] { background-color: #28a745 !important; color: white !important; }
    .stMetric { background: #f8f9fa; padding: 10px; border-radius: 10px; border: 1px solid #eee; }
</style>""", unsafe_allow_html=True)

# --- 5. POMOCNICZE ---
def get_lat_lng(addr):
    try:
        loc = Nominatim(user_agent="v135").geocode(addr, timeout=10)
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

# --- 6. SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Zarządzanie")
    with st.expander("☁️ KML", expanded=False):
        up = st.file_uploader("Dodaj KML", type=['kml'], accept_multiple_files=True)
        if up and st.button("Wczytaj"):
            all_pts = [parse_kml(f.read().decode('utf-8'), f.name) for f in up]
            if all_pts: 
                st.session_state['data'] = pd.concat([st.session_state['data'], pd.concat(all_pts)], ignore_index=True).drop_duplicates()
                st.rerun()

    if not st.session_state['data'].empty:
        with st.expander("📂 Rejony", expanded=True):
            for f in sorted(st.session_state['data']['source_file'].unique()):
                c1, c2 = st.columns([4, 1])
                c1.write(f"📄 {f}")
                if c2.button("🗑️", key=f"d_{f}"):
                    st.session_state['data'] = st.session_state['data'][st.session_state['data']['source_file']!=f]
                    st.rerun()

    with st.expander("🏠 Bazy", expanded=True):
        if st.session_state['saved_locations']:
            sel_b = st.selectbox("Wybierz:", ["---"] + sorted(st.session_state['saved_locations'].keys()))
            if sel_b != "---":
                addr = st.session_state['saved_locations'][sel_b]
                c1, c2, c3 = st.columns(3)
                if c1.button("🏠", key=f"s_{sel_b}"):
                    st.session_state.update({'start_name': sel_b, 'start_coords': get_lat_lng(addr)}); st.rerun()
                if c2.button("🏁", key=f"m_{sel_b}"):
                    st.session_state.update({'meta_name': sel_b, 'meta_coords': get_lat_lng(addr)}); st.rerun()
                if c3.button("🗑️", key=f"x_{sel_b}"):
                    del st.session_state['saved_locations'][sel_b]; sync_save(); st.rerun()
        with st.form("nb", clear_on_submit=True):
            n, a = st.text_input("Nazwa:"), st.text_input("Adres:")
            if st.form_submit_button("➕"):
                if n and a: st.session_state['saved_locations'][n]=a; sync_save(); st.rerun()

    with st.expander("📁 Projekty", expanded=True):
        p_input = st.text_input("Nazwa projektu:")
        if st.button("💾 Zapisz Projekt") and p_input:
            st.session_state['projects'][p_input] = {
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
                if c2.button("🗑️", key=f"dp_{sel_p}"):
                    del st.session_state['projects'][sel_p]; sync_save(); st.rerun()

    st.button("🔓 WYLOGUJ", on_click=lambda: st.session_state.update({'authenticated': False}))

# --- 7. PANEL GŁÓWNY ---
st.title("🗺️ Optymalizator Tras")

col_s, col_m = st.columns(2)
with col_s:
    st.info(f"🏠 **START:** {st.session_state['start_name']}")
    if st.session_state['start_name'] != "Nie wybrano":
        if st.button("Wyczyść Start"): st.session_state.update({'start_name': "Nie wybrano", 'start_coords': None}); st.rerun()
with col_m:
    st.info(f"🏁 **META:** {st.session_state['meta_name']}")
    if st.session_state['meta_name'] != "Nie wybrano":
        if st.button("Wyczyść Metę"): st.session_state.update({'meta_name': "Nie wybrano", 'meta_coords': None}); st.rerun()

sc, mc = st.session_state['start_coords'], st.session_state['meta_coords']

if not st.session_state['data'].empty:
    u_files = sorted(st.session_state['data']['source_file'].unique().tolist())
    v_files = st.multiselect("Widoczne rejony:", u_files, default=u_files)
    filtered_df = st.session_state['data'][st.session_state['data']['source_file'].isin(v_files)]
    
    c_v1, c_v2 = st.columns(2)
    show_pins = c_v1.checkbox("Pokaż pinezki", value=True)
    mode = c_v2.radio("Tryb:", ["Jedna trasa", "Oddzielne"], horizontal=True)

    c_calc, c_res = st.columns([4, 1])
    if c_calc.button("🚀 OBLICZ OPTYMALNE TRASY", type="primary", use_container_width=True):
        if not (sc and mc): st.error("Ustaw Start i Metę!")
        else:
            with st.spinner("Liczenie..."):
                st.session_state.update({'optimized_list': [], 'geometries': []})
                groups = [filtered_df] if mode == "Jedna trasa" else [filtered_df[filtered_df['source_file']==f] for f in filtered_df['source_file'].unique()]
                for idx, group in enumerate(groups):
                    if group.empty: continue
                    curr = {"lat": sc['lat'], "lng": sc['lng'], "display_name": "START"}
                    route, unv = [curr], group.to_dict('records')
                    while unv:
                        nxt = min(unv, key=lambda x: get_math_dist(curr['lat'], curr['lng'], x['lat'], x['lng']))
                        route.append(nxt); curr = nxt; unv.remove(nxt)
                    route.append({"lat": mc['lat'], "lng": mc['lng'], "display_name": "META"})
                    geom, d, t = get_route_chunked([[r['lat'], r['lng']] for r in route])
                    st.session_state['optimized_list'].append(pd.DataFrame(route))
                    st.session_state['geometries'].append({"geom": geom, "color": get_folium_color(idx), "dist": d, "time": t, "name": group['source_file'].iloc[0] if mode != "Jedna trasa" else "Całość", "pts": len(group)})
                st.rerun()

    if c_res.button("✖ WYCZYŚĆ WSZYSTKO", use_container_width=True):
        st.session_state.update({'optimized_list': [], 'geometries': [], 'data': pd.DataFrame(), 'start_name': "Nie wybrano", 'meta_name': "Nie wybrano", 'start_coords': None, 'meta_coords': None})
        st.rerun()

    m = folium.Map()
    file_color_map = {f: get_folium_color(i) for i, f in enumerate(u_files)}
    bounds = [[sc['lat'], sc['lng']], [mc['lat'], mc['lng']]] if sc and mc else []
    if sc: folium.Marker([sc['lat'], sc['lng']], icon=folium.Icon(color='green', icon='home', prefix='fa')).add_to(m)
    if mc: folium.Marker([mc['lat'], mc['lng']], icon=folium.Icon(color='red', icon='flag', prefix='fa')).add_to(m)
    
    visible_geoms = [g for g in st.session_state['geometries'] if mode == "Jedna trasa" or g['name'] in v_files]
    for g in visible_geoms: 
        folium.PolyLine([[c[1], c[0]] for c in g['geom']], color=g['color'], weight=5).add_to(m)
    if show_pins:
        for _, r in filtered_df.iterrows():
            folium.Marker([r['lat'], r['lng']], icon=folium.Icon(color=file_color_map.get(r['source_file'], 'gray'), icon='circle', prefix='fa'), tooltip=r['display_name']).add_to(m)
            bounds.append([r['lat'], r['lng']])
    
    if bounds: m.fit_bounds(bounds)
    st_folium(m, width="100%", height=550)

    # --- PODSUMOWANIE ---
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
        
        with st.expander("📋 Tabela kolejności"):
            for i, df in enumerate(st.session_state['optimized_list']):
                st.write(f"**Trasa: {visible_geoms[i]['name'] if i < len(visible_geoms) else i}**")
                st.dataframe(df[['display_name', 'lat', 'lng']], use_container_width=True)
else:
    st.info("👈 Wgraj KML i wybierz bazy.")
