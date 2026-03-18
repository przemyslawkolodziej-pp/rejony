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

# --- 2. LOGIKA BEZPIECZEŃSTWA (TOKEN URL) ---
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

# --- 3. INTEGRACJA GOOGLE SHEETS ---
def get_gspread_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds)

def compress_data(data_dict):
    json_str = json.dumps(data_dict, ensure_ascii=False, separators=(',', ':'))
    return base64.b64encode(zlib.compress(json_str.encode('utf-8'))).decode('utf-8')

def decompress_data(compressed_str):
    try: return json.loads(zlib.decompress(base64.b64decode(compressed_str)).decode('utf-8'))
    except: return json.loads(compressed_str)

def sync_save():
    try:
        client = get_gspread_client()
        sheet = client.open_by_key(SHEET_ID)
        # Lokacje
        l_sh = sheet.worksheet("SavedLocations")
        l_sh.clear()
        l_rows = [["Nazwa", "Adres"]] + [[n, a] for n, a in st.session_state['saved_locations'].items()]
        l_sh.update(values=l_rows, range_name='A1')
        # Projekty
        p_sh = sheet.worksheet("Projects")
        p_sh.clear()
        p_rows = [["Nazwa Projektu", "Dane JSON"]]
        for p_n, p_d in st.session_state['projects'].items():
            s = p_d.copy()
            if isinstance(s.get('data'), pd.DataFrame): s['data'] = s['data'].to_dict()
            if 'optimized_list' in s: s['optimized_list'] = [df.to_dict() if isinstance(df, pd.DataFrame) else df for df in s['optimized_list']]
            p_rows.append([str(p_n), compress_data(s)])
        p_sh.update(values=p_rows, range_name='A1')
        st.toast("Zsynchronizowano! ✅")
    except Exception as e: st.error(f"Błąd zapisu: {e}")

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
                c = decompress_data(p_j)
                if 'data' in c: c['data'] = pd.DataFrame(c['data'])
                if 'optimized_list' in c: c['optimized_list'] = [pd.DataFrame(df) for df in c['optimized_list']]
                loaded[p_n] = c
        st.session_state['projects'] = loaded
    except: pass

# --- 4. MODALE (OKNA DIALOGOWE) ---
@st.dialog("Otwórz projekt")
def modal_open_project():
    if not st.session_state['projects']:
        st.write("Brak zapisanych projektów.")
        return
    sel = st.selectbox("Wybierz projekt:", sorted(st.session_state['projects'].keys()))
    if st.button("Ok", use_container_width=True):
        st.session_state.update(st.session_state['projects'][sel])
        st.session_state['current_project_name'] = sel
        st.rerun()

@st.dialog("Zapisz projekt jako Nowy")
def modal_save_as():
    new_name = st.text_input("Nazwa nowego projektu:")
    if st.button("Ok", use_container_width=True):
        if new_name in st.session_state['projects']:
            st.error("Ta nazwa już istnieje w arkuszu!")
        elif new_name:
            st.session_state['current_project_name'] = new_name
            # Logika zapisu
            save_logic(new_name)
            st.rerun()

@st.dialog("Dodaj pliki KML")
def modal_add_kml():
    up = st.file_uploader("Wybierz pliki KML", type=['kml'], accept_multiple_files=True)
    if st.button("Wczytaj", use_container_width=True) and up:
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

@st.dialog("Usuń pliki KML")
def modal_remove_kml():
    if st.session_state['data'].empty:
        st.write("Brak wczytanych plików.")
        return
    u_files = sorted(st.session_state['data']['source_file'].unique())
    to_del = st.multiselect("Wybierz pliki do usunięcia:", u_files)
    if st.button("Usuń wybrane", use_container_width=True):
        st.session_state['data'] = st.session_state['data'][~st.session_state['data']['source_file'].isin(to_del)]
        st.rerun()

@st.dialog("Dodaj bazę")
def modal_add_base():
    n = st.text_input("Nazwa bazy:")
    a = st.text_input("Adres bazy:")
    if st.button("Dodaj", use_container_width=True) and n and a:
        st.session_state['saved_locations'][n] = a
        sync_save()
        st.rerun()

def save_logic(name):
    st.session_state['projects'][name] = {
        'data': st.session_state['data'].copy(), 
        'start_name': st.session_state['start_name'], 
        'meta_name': st.session_state['meta_name'],
        'start_coords': st.session_state['start_coords'], 
        'meta_coords': st.session_state['meta_coords'],
        'optimized_list': [df.copy() for df in st.session_state['optimized_list']], 
        'geometries': st.session_state['geometries']
    }
    sync_save()

# --- 5. INICJALIZACJA I AUTH ---
if 'initialized' not in st.session_state:
    st.session_state.update({
        'initialized': True, 'authenticated': False, 'data': pd.DataFrame(), 
        'optimized_list': [], 'saved_locations': {}, 'projects': {}, 
        'start_coords': None, 'meta_coords': None, 'geometries': [],
        'start_name': "Baza", 'meta_name': "Baza", 'current_project_name': None
    })

if not check_auth():
    st.title("🔐 Logowanie")
    with st.form("login"):
        pwd = st.text_input("Hasło:", type="password")
        if st.form_submit_button("Zaloguj"):
            if pwd == st.secrets.get("password"):
                st.query_params["token"] = generate_session_token(pwd)
                st.session_state['authenticated'] = True
                sync_load(); st.rerun()
    st.stop()

# --- 6. GÓRNY PASEK NAWIGACJI (ZABLOKOWANY) ---
# Używamy st.container z CSS, aby udawał pasek nawigacji
nav_container = st.container()
with nav_container:
    cols = st.columns([1.2, 1.2, 1.8, 1.3, 1.3, 1.2, 1])
    if cols[0].button("📂 Otwórz", use_container_width=True): modal_open_project()
    if cols[1].button("💾 Zapisz", use_container_width=True):
        if st.session_state['current_project_name']: save_logic(st.session_state['current_project_name'])
        else: modal_save_as()
    if cols[2].button("➕ Zapisz jako Nowy", use_container_width=True): modal_save_as()
    if cols[3].button("📎 Dodaj KML", use_container_width=True): modal_add_kml()
    if cols[4].button("❌ Usuń KML", use_container_width=True): modal_remove_kml()
    if cols[5].button("🏠 Baza+", use_container_width=True): modal_add_base()
    if cols[6].button("🔓 Wyloguj", use_container_width=True):
        st.query_params.clear()
        st.session_state.update({'authenticated': False})
        st.rerun()
st.markdown("---")

# --- 7. SEKCJA START / META (POŁĄCZONA Z BAZĄ) ---
def get_lat_lng(addr):
    try:
        loc = Nominatim(user_agent="v160").geocode(addr, timeout=10)
        return {"lat": loc.latitude, "lng": loc.longitude} if loc else None
    except: return None

# Pobieramy nazwy baz z arkusza
base_options = sorted(list(st.session_state['saved_locations'].keys()))

c_start, c_meta = st.columns(2)

with c_start:
    # Wykrywamy zmianę w Selectbox
    current_start = st.selectbox("🏠 WYBIERZ START (Baza):", ["---"] + base_options, 
                                 index=base_options.index(st.session_state['start_name'])+1 if st.session_state['start_name'] in base_options else 0)
    if current_start != "---" and current_start != st.session_state['start_name']:
        st.session_state['start_name'] = current_start
        st.session_state['start_coords'] = get_lat_lng(st.session_state['saved_locations'][current_start])
        st.rerun()

with c_meta:
    current_meta = st.selectbox("🏁 WYBIERZ METĘ (Baza):", ["---"] + base_options, 
                                index=base_options.index(st.session_state['meta_name'])+1 if st.session_state['meta_name'] in base_options else 0)
    if current_meta != "---" and current_meta != st.session_state['meta_name']:
        st.session_state['meta_name'] = current_meta
        st.session_state['meta_coords'] = get_lat_lng(st.session_state['saved_locations'][current_meta])
        st.rerun()

# --- 8. MAPA I OBLICZENIA (BEZ ZMIAN W LOGICE) ---
if not st.session_state['data'].empty:
    u_f = sorted(st.session_state['data']['source_file'].unique().tolist())
    v_f = st.multiselect("Widoczne rejony na mapie:", u_f, default=u_f)
    f_df = st.session_state['data'][st.session_state['data']['source_file'].isin(v_f)]
    
    cv1, cv2 = st.columns(2)
    show_pins = cv1.checkbox("Pokaż punkty (pinezki)", value=True)
    mode = cv2.radio("Tryb trasy:", ["Jedna trasa dla wszystkich", "Oddzielna trasa dla każdego pliku"], horizontal=True)

    if st.button("🚀 OBLICZ OPTYMALNE TRASY", type="primary", use_container_width=True):
        if not (st.session_state['start_coords'] and st.session_state['meta_coords']):
            st.error("Wybierz Start i Metę z listy powyżej!")
        else:
            with st.spinner("Optymalizacja..."):
                # (Tutaj logika OSRM pozostaje taka sama jak wcześniej)
                st.session_state.update({'optimized_list': [], 'geometries': []})
                sc, mc = st.session_state['start_coords'], st.session_state['meta_coords']
                grps = [f_df] if mode == "Jedna trasa dla wszystkich" else [f_df[f_df['source_file']==f] for f in f_df['source_file'].unique()]
                
                for idx, g in enumerate(grps):
                    if g.empty: continue
                    curr = {"lat": sc['lat'], "lng": sc['lng']}
                    route, unv = [curr], g.to_dict('records')
                    while unv:
                        nxt = min(unv, key=lambda x: math.sqrt((curr['lat']-x['lat'])**2 + (curr['lng']-x['lng'])**2))
                        route.append(nxt); curr = nxt; unv.remove(nxt)
                    route.append({"lat": mc['lat'], "lng": mc['lng']})
                    
                    # OSRM Call
                    chunk_coords = [[r['lat'], r['lng']] for r in route]
                    geom, dist, time_s = [], 0, 0
                    for i in range(0, len(chunk_coords)-1, 39):
                        c_chunk = chunk_coords[i:i+40]
                        try:
                            r = requests.get(f"http://router.project-osrm.org/route/v1/driving/{';'.join([f'{c[1]},{c[0]}' for c in c_chunk])}?overview=full&geometries=geojson").json()
                            if r['code']=='Ok':
                                geom.extend(r['routes'][0]['geometry']['coordinates'])
                                dist += r['routes'][0]['distance']; time_s += r['routes'][0]['duration']
                        except: pass
                    
                    st.session_state['optimized_list'].append(pd.DataFrame(route))
                    st.session_state['geometries'].append({"geom": geom, "color": ['blue','red','green','orange','purple'][idx%5], "dist": dist, "time": time_s, "name": g['source_file'].iloc[0] if mode != "Jedna trasa dla wszystkich" else "Wszystkie", "pts": len(g)})
                st.rerun()

    # Wyświetlanie mapy
    m = folium.Map()
    if st.session_state['start_coords']: folium.Marker([st.session_state['start_coords']['lat'], st.session_state['start_coords']['lng']], icon=folium.Icon(color='green')).add_to(m)
    if st.session_state['meta_coords']: folium.Marker([st.session_state['meta_coords']['lat'], st.session_state['meta_coords']['lng']], icon=folium.Icon(color='red')).add_to(m)
    
    for g in st.session_state['geometries']:
        folium.PolyLine([[c[1], c[0]] for c in g['geom']], color=g['color'], weight=5).add_to(m)
    
    if show_pins:
        for _, r in f_df.iterrows():
            folium.Marker([r['lat'], r['lng']], tooltip=r['display_name']).add_to(m)
            
    st_folium(m, width="100%", height=600)
    
    if st.session_state['geometries']:
        td = sum(g['dist'] for g in st.session_state['geometries'])
        st.success(f"Łączny dystans: {td/1000:.2f} km")
else:
    st.info("Użyj paska nawigacji na górze, aby dodać dane KML lub otworzyć projekt.")
