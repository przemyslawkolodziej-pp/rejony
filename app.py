import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
import re, math, json, requests, os
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# --- 1. KONFIGURACJA ---
# WPISZ TUTAJ SWOJE ID ARKUSZA
SHEET_ID = "TWOJE_ID_ARKUSZA" 

st.set_page_config(page_title="Optymalizator Tras", page_icon="🗺️", layout="wide")

# --- 2. INTEGRACJA Z GOOGLE SHEETS ---
def get_gspread_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_dict = dict(st.secrets["gcp_service_account"])
    # Klucz jest już poprawny w Secrets, więc ładujemy go bezpośrednio
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds)

def sync_save():
    if SHEET_ID == "TWOJE_ID_ARKUSZA": return
    try:
        client = get_gspread_client()
        sheet = client.open_by_key(SHEET_ID)
        
        # Zapis BAZ
        loc_sheet = sheet.worksheet("SavedLocations")
        loc_sheet.clear()
        rows = [["Nazwa", "Adres"]]
        for name, addr in st.session_state['saved_locations'].items():
            rows.append([name, addr])
        loc_sheet.update('A1', rows)
            
        # Zapis PROJEKTÓW
        proj_sheet = sheet.worksheet("Projects")
        proj_sheet.clear()
        p_rows = [["Nazwa Projektu", "Dane JSON"]]
        for p_name, p_data in st.session_state['projects'].items():
            serializable = p_data.copy()
            if isinstance(serializable.get('data'), pd.DataFrame):
                serializable['data'] = serializable['data'].to_dict()
            if 'optimized_list' in serializable:
                serializable['optimized_list'] = [df.to_dict() if isinstance(df, pd.DataFrame) else df for df in serializable['optimized_list']]
            p_rows.append([p_name, json.dumps(serializable, ensure_ascii=False)])
        proj_sheet.update('A1', p_rows)
        
        st.toast("Zsynchronizowano z Google Sheets! ✅", icon="☁️")
    except Exception as e:
        st.error(f"Błąd synchronizacji: {e}")

def sync_load():
    if SHEET_ID == "TWOJE_ID_ARKUSZA": return
    try:
        client = get_gspread_client()
        sheet = client.open_by_key(SHEET_ID)
        # Wczytanie BAZ
        loc_data = sheet.worksheet("SavedLocations").get_all_records()
        st.session_state['saved_locations'] = {row['Nazwa']: row['Adres'] for row in loc_data if 'Nazwa' in row}
        # Wczytanie PROJEKTÓW
        proj_data = sheet.worksheet("Projects").get_all_records()
        loaded_projs = {}
        for row in proj_data:
            p_name, p_json = row.get('Nazwa Projektu'), row.get('Dane JSON')
            if p_name and p_json:
                p_content = json.loads(p_json)
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

# --- 4. STYLE CSS ---
st.markdown("""
<style>
    div.stButton > button { height: 40px; width: 100%; font-size: 18px !important; border-radius: 8px; }
    .base-info-box { background-color: #f0f2f6; padding: 15px; border-radius: 10px; border-left: 5px solid #28a745; margin-bottom: 10px; }
    button[kind="primary"] { background-color: #28a745 !important; color: white !important; }
</style>
""", unsafe_allow_html=True)

# --- 5. LOGIKA POMOCNICZA ---
def get_lat_lng(address):
    try:
        gl = Nominatim(user_agent="v106_geo")
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

# --- 6. SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Menu")
    
    with st.expander("🏠 Bazy (Start/Meta)", expanded=True):
        if st.session_state['saved_locations']:
            sel_b = st.selectbox("Wybierz lokalizację:", ["---"] + sorted(st.session_state['saved_locations'].keys()))
            if sel_b != "---":
                addr = st.session_state['saved_locations'][sel_b]
                c1, c2, c3 = st.columns(3)
                if c1.button("🏠", help="Ustaw jako START"):
                    st.session_state.update({'start_name': sel_b, 'start_coords': get_lat_lng(addr)}); st.rerun()
                if c2.button("🏁", help="Ustaw jako META"):
                    st.session_state.update({'meta_name': sel_b, 'meta_coords': get_lat_lng(addr)}); st.rerun()
                if c3.button("🗑️"):
                    del st.session_state['saved_locations'][sel_b]
                    sync_save(); st.rerun()
        st.markdown("---")
        with st.form("new_base", clear_on_submit=True):
            n, a = st.text_input("Nazwa:"), st.text_input("Adres:")
            if st.form_submit_button("➕ Dodaj nową bazę"):
                if n and a:
                    st.session_state['saved_locations'][n] = a
                    sync_save(); st.rerun()

    with st.expander("📁 Projekty", expanded=False):
        p_name = st.text_input("Zapisz projekt jako:")
        if st.button("💾 Zapisz Projekt") and p_name:
            st.session_state['projects'][p_name] = {
                'data': st.session_state['data'].copy(), 'start_name': st.session_state['start_name'], 'meta_name': st.session_state['meta_name'],
                'start_coords': st.session_state['start_coords'], 'meta_coords': st.session_state['meta_coords'],
                'optimized_list': [df.copy() for df in st.session_state['optimized_list']], 'geometries': st.session_state['geometries']
            }
            sync_save(); st.rerun()
        if st.session_state['projects']:
            sel_p = st.selectbox("Wczytaj projekt:", ["---"] + sorted(st.session_state['projects'].keys()))
            if sel_p != "---":
                if st.button("📂 Otwórz"):
                    st.session_state.update(st.session_state['projects'][sel_p]); st.rerun()
                if st.button("🗑️ Usuń Projekt"):
                    del st.session_state['projects'][sel_p]; sync_save(); st.rerun()

    with st.expander("☁️ Rejony (KML)", expanded=False):
        up = st.file_uploader("Wgraj pliki KML", type=['kml'], accept_multiple_files=True)
        if up and st.button("Wczytaj punkty"):
            def parse_kml(content, name):
                placemarks = re.findall(r'<Placemark>(.*?)</Placemark>', content, re.DOTALL)
                pts = []
                for pm in placemarks:
                    n = re.search(r'<(?:name|display_name)>(.*?)</', pm)
                    c = re.search(r'<coordinates>\s*([\d\.\-]+),\s*([\d\.\-]+)', pm)
                    if c: pts.append({"display_name": n.group(1) if n else "Punkt", "lat": float(c.group(2)), "lng": float(c.group(1)), "source_file": name})
                return pd.DataFrame(pts)
            all_pts = [parse_kml(f.read().decode('utf-8'), f.name) for f in up]
            if all_pts:
                st.session_state['data'] = pd.concat([st.session_state['data'], pd.concat(all_pts)], ignore_index=True).drop_duplicates()
                st.rerun()

    st.button("🔓 WYLOGUJ", on_click=lambda: st.session_state.update({'authenticated': False}))

# --- 7. PANEL GŁÓWNY ---
st.title("🗺️ Optymalizator Tras")

col_s, col_m = st.columns(2)
with col_s: st.markdown(f'<div class="base-info-box">🏠 <b>START:</b> {st.session_state["start_name"]}</div>', unsafe_allow_html=True)
with col_m: st.markdown(f'<div class="base-info-box">🏁 <b>META:</b> {st.session_state["meta_name"]}</div>', unsafe_allow_html=True)

sc, mc = st.session_state['start_coords'], st.session_state['meta_coords']

if not st.session_state['data'].empty:
    u_files = sorted(st.session_state['data']['source_file'].unique().tolist())
    v_files = st.multiselect("Widoczne rejony:", u_files, default=u_files)
    filtered_df = st.session_state['data'][st.session_state['data']['source_file'].isin(v_files)]
    
    col_btn, col_opt = st.columns([2, 1])
    with col_opt: mode = st.radio("Tryb trasy:", ["Jedna trasa", "Oddzielne"], horizontal=True)
    
    if col_btn.button("🚀 OBLICZ OPTYMALNĄ TRASĘ", type="primary", use_container_width=True):
        if not (sc and mc): st.error("Wybierz START i METĘ w panelu bocznym!")
        else:
            with st.spinner("Optymalizacja..."):
                st.session_state.update({'optimized_list': [], 'geometries': []})
                groups = [filtered_df] if mode == "Jedna trasa" else [filtered_df[filtered_df['source_file'] == f] for f in filtered_df['source_file'].unique()]
                for group in groups:
                    if group.empty: continue
                    route_color = 'green' if mode == "Jedna trasa" else 'blue'
                    curr = {"lat": sc['lat'], "lng": sc['lng']}
                    route, unv = [curr], group.to_dict('records')
                    while unv:
                        nxt = min(unv, key=lambda x: get_math_dist(curr['lat'], curr['lng'], x['lat'], x['lng']))
                        route.append(nxt); curr = nxt; unv.remove(nxt)
                    route.append({"lat": mc['lat'], "lng": mc['lng']})
                    geom, d, t = get_route_chunked([[r['lat'], r['lng']] for r in route])
                    st.session_state['optimized_list'].append(pd.DataFrame(route))
                    st.session_state['geometries'].append({"geom": geom, "color": route_color, "dist": d, "time": t})
            st.rerun()

    m = folium.Map()
    draw_pts = []
    if sc: 
        folium.Marker([sc['lat'], sc['lng']], icon=folium.Icon(color='green', icon='home')).add_to(m)
        draw_pts.append([sc['lat'], sc['lng']])
    if mc: 
        folium.Marker([mc['lat'], mc['lng']], icon=folium.Icon(color='red', icon='flag')).add_to(m)
        draw_pts.append([mc['lat'], mc['lng']])
    
    for _, r in filtered_df.iterrows():
        folium.CircleMarker([r['lat'], r['lng']], radius=5, color='blue', fill=True).add_to(m)
        draw_pts.append([r['lat'], r['lng']])
    
    for g in st.session_state['geometries']:
        folium.PolyLine([[c[1], c[0]] for c in g['geom']], color=g['color'], weight=4).add_to(m)
    
    if draw_pts: m.fit_bounds(draw_pts)
    st_folium(m, width="100%", height=600)
    
    if st.session_state['geometries']:
        td = sum(g['dist'] for g in st.session_state['geometries'])
        tt = sum(g['time'] for g in st.session_state['geometries'])
        st.success(f"📊 RAZEM: {td/1000:.2f} km | Szacowany czas: {int(tt//3600)}h {int((tt%3600)//60)}min")
else:
    if sc or mc:
        m = folium.Map()
        pts = []
        if sc: 
            folium.Marker([sc['lat'], sc['lng']], icon=folium.Icon(color='green')).add_to(m)
            pts.append([sc['lat'], sc['lng']])
        if mc: 
            folium.Marker([mc['lat'], mc['lng']], icon=folium.Icon(color='red')).add_to(m)
            pts.append([mc['lat'], mc['lng']])
        m.fit_bounds(pts)
        st_folium(m, width="100%", height=600)
    else:
        st.info("👈 Zacznij od dodania bazy lub wgrania KML.")
