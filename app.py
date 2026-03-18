import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
import re, math, json, requests, os, time, zlib, base64, hashlib
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# --- 1. KONFIGURACJA I STYLIZACJA ---
SHEET_ID = "1mTMjUKoHNw-okxpYSAeLsVD7vdxYR1P-ZjelWt9IHAE" 
st.set_page_config(page_title="Optymalizator Tras", page_icon="🗺️", layout="wide")

st.markdown("""
    <style>
        .stButton>button { border-radius: 8px; }
        .stMain { margin-top: -30px; }
        /* Kolory nawigacji */
        div[data-testid="stExpander"] { border: 1px solid #e9ecef; }
    </style>
""", unsafe_allow_html=True)

# --- 2. LOGIKA AUTH ---
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

# --- 3. GOOGLE SHEETS ---
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
        # Bazy
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
            if 'optimized_list' in s:
                s['optimized_list'] = [df.to_dict() if isinstance(df, pd.DataFrame) else df for df in s['optimized_list']]
            p_rows.append([str(p_n), compress_data(s)])
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
                c = decompress_data(p_j)
                if 'data' in c: 
                    c['data'] = pd.DataFrame(c['data'])
                    # NAPRAWA: Jeśli w starym projekcie była kolumna 'source_file', zmień na 'Rejon'
                    if 'source_file' in c['data'].columns:
                        c['data'] = c['data'].rename(columns={'source_file': 'Rejon'})
                if 'optimized_list' in c: 
                    c['optimized_list'] = [pd.DataFrame(df) for df in c['optimized_list']]
                    for df in c['optimized_list']:
                        if 'source_file' in df.columns:
                            df.rename(columns={'source_file': 'Rejon'}, inplace=True)
                loaded[p_n] = c
        st.session_state['projects'] = loaded
    except: pass

def save_logic(name):
    st.session_state['projects'][name] = {
        'data': st.session_state['data'].copy(), 
        'start_name': st.session_state['start_name'], 'meta_name': st.session_state['meta_name'],
        'start_coords': st.session_state['start_coords'], 'meta_coords': st.session_state['meta_coords'],
        'optimized_list': [df.copy() for df in st.session_state['optimized_list']], 
        'geometries': st.session_state['geometries']
    }
    sync_save()

# --- 4. MODALE ---
@st.dialog("Otwórz projekt")
def modal_open_project():
    if not st.session_state['projects']:
        st.write("Brak projektów.")
        return
    sel = st.selectbox("Wybierz:", sorted(st.session_state['projects'].keys()))
    if st.button("Ok"):
        st.session_state.update(st.session_state['projects'][sel])
        st.session_state['current_project_name'] = sel
        st.rerun()

@st.dialog("Zapisz jako Nowy")
def modal_save_as():
    n = st.text_input("Nazwa projektu:")
    if st.button("Zapisz"):
        if n in st.session_state['projects']: st.warning("Nazwa zajęta!")
        elif n:
            st.session_state['current_project_name'] = n
            save_logic(n); st.rerun()

@st.dialog("Dodaj pliki KML")
def modal_add_kml():
    up = st.file_uploader("Wgraj KML", type=['kml'], accept_multiple_files=True)
    if st.button("Wczytaj") and up:
        all_pts = []
        for f in up:
            content = f.read().decode('utf-8')
            pts = []
            for pm in re.findall(r'<Placemark>(.*?)</Placemark>', content, re.DOTALL):
                name = re.search(r'<(?:name|display_name)>(.*?)</', pm)
                coords = re.search(r'<coordinates>\s*([\d\.\-]+),\s*([\d\.\-]+)', pm)
                if coords: pts.append({
                    "Punkt": name.group(1) if name else "Punkt", 
                    "lat": float(coords.group(2)), 
                    "lng": float(coords.group(1)), 
                    "Rejon": f.name
                })
            all_pts.append(pd.DataFrame(pts))
        if all_pts:
            new_data = pd.concat(all_pts)
            st.session_state['data'] = pd.concat([st.session_state['data'], new_data], ignore_index=True).drop_duplicates()
            st.rerun()

@st.dialog("Usuń KML")
def modal_remove_kml():
    if st.session_state['data'].empty: return
    u_f = sorted(st.session_state['data']['Rejon'].unique())
    to_del = st.multiselect("Wybierz pliki do usunięcia:", u_f)
    if st.button("Usuń wybrane"):
        st.session_state['data'] = st.session_state['data'][~st.session_state['data']['Rejon'].isin(to_del)]
        st.rerun()

@st.dialog("Dodaj bazę")
def modal_add_base():
    n, a = st.text_input("Nazwa:"), st.text_input("Adres:")
    if st.button("Dodaj") and n and a:
        st.session_state['saved_locations'][n] = a
        sync_save(); st.rerun()

# --- 5. INICJALIZACJA ---
if 'initialized' not in st.session_state:
    st.session_state.update({
        'initialized': True, 'authenticated': False, 'data': pd.DataFrame(columns=["Punkt", "lat", "lng", "Rejon"]), 
        'optimized_list': [], 'saved_locations': {}, 'projects': {}, 
        'start_coords': None, 'meta_coords': None, 'geometries': [],
        'start_name': "---", 'meta_name': "---", 'current_project_name': None
    })

if not check_auth():
    st.title("🔐 Logowanie")
    with st.form("l"):
        p = st.text_input("Hasło:", type="password")
        if st.form_submit_button("Zaloguj"):
            if p == st.secrets.get("password"):
                st.query_params["token"] = generate_session_token(p)
                st.session_state['authenticated'] = True
                sync_load(); st.rerun()
    st.stop()

# --- 6. PASEK NAWIGACJI ---
with st.container():
    c = st.columns([1, 1, 1.8, 1.2, 1.2, 1, 1])
    curr = st.session_state.get('current_project_name')
    if c[0].button("📂 Otwórz", use_container_width=True): modal_open_project()
    if c[1].button("💾 Zapisz", use_container_width=True):
        if curr: save_logic(curr)
        else: modal_save_as()
    if c[2].button("➕ Zapisz jako Nowy", use_container_width=True): modal_save_as()
    if c[3].button("📎 Dodaj KML", use_container_width=True): modal_add_kml()
    if c[4].button("❌ Usuń KML", use_container_width=True): modal_remove_kml()
    if c[5].button("🏠 Baza+", use_container_width=True): modal_add_base()
    if c[6].button("🔓 Wyloguj", use_container_width=True):
        st.query_params.clear(); st.session_state.clear(); st.rerun()

if curr: st.info(f"Aktywny projekt: **{curr}**")
st.markdown("---")

# --- 7. START / META ---
def get_lat_lng(addr):
    try:
        l = Nominatim(user_agent="v181_opti").geocode(addr, timeout=10)
        return {"lat": l.latitude, "lng": l.longitude} if l else None
    except: return None

bases = sorted(list(st.session_state['saved_locations'].keys()))
c1, c2 = st.columns(2)
with c1:
    s_sel = st.selectbox("🏠 START:", ["---"] + bases, index=bases.index(st.session_state['start_name'])+1 if st.session_state['start_name'] in bases else 0)
    if s_sel != "---" and s_sel != st.session_state['start_name']:
        st.session_state['start_name'] = s_sel
        st.session_state['start_coords'] = get_lat_lng(st.session_state['saved_locations'][s_sel])
        st.rerun()
with c2:
    m_sel = st.selectbox("🏁 META:", ["---"] + bases, index=bases.index(st.session_state['meta_name'])+1 if st.session_state['meta_name'] in bases else 0)
    if m_sel != "---" and m_sel != st.session_state['meta_name']:
        st.session_state['meta_name'] = m_sel
        st.session_state['meta_coords'] = get_lat_lng(st.session_state['saved_locations'][m_sel])
        st.rerun()

# --- 8. OBLICZENIA I MAPA ---
if not st.session_state['data'].empty:
    # Zabezpieczenie przed brakiem kolumny Rejon w starych danych
    if 'Rejon' not in st.session_state['data'].columns:
        st.session_state['data']['Rejon'] = "Nieokreślony"

    u_f = sorted(st.session_state['data']['Rejon'].unique())
    v_f = st.multiselect("Filtruj rejony:", u_f, default=u_f)
    f_df = st.session_state['data'][st.session_state['data']['Rejon'].isin(v_f)]
    
    cv1, cv2 = st.columns(2)
    show_pins = cv1.checkbox("Pokaż punkty na mapie", value=True)
    mode = cv2.radio("Sposób łączenia:", ["Wspólna trasa", "Osobne trasy dla rejonów"], horizontal=True)

    if st.button("🚀 OBLICZ TRASY", type="primary", use_container_width=True):
        if not (st.session_state['start_coords'] and st.session_state['meta_coords']):
            st.warning("Najpierw wybierz bazy startu i mety!")
        else:
            with st.spinner("Optymalizacja..."):
                st.session_state.update({'optimized_list': [], 'geometries': []})
                sc, mc = st.session_state['start_coords'], st.session_state['meta_coords']
                grps = [f_df] if mode == "Wspólna trasa" else [f_df[f_df['Rejon']==f] for f in f_df['Rejon'].unique()]
                
                for idx, g in enumerate(grps):
                    if g.empty: continue
                    curr_p = {"lat": sc['lat'], "lng": sc['lng']}
                    route, unv = [curr_p], g.to_dict('records')
                    while unv:
                        nxt = min(unv, key=lambda x: math.sqrt((curr_p['lat']-x['lat'])**2 + (curr_p['lng']-x['lng'])**2))
                        route.append(nxt); curr_p = nxt; unv.remove(nxt)
                    route.append({"Punkt": "META", "lat": mc['lat'], "lng": mc['lng'], "Rejon": "META"})
                    
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
                    
                    st.session_state['optimized_list'].append(pd.DataFrame(route))
                    st.session_state['geometries'].append({
                        "geom": geom, "color": ['#007bff','#28a745','#6f42c1','#fd7e14','#20c997'][idx%5], 
                        "dist": dist, "time": dur, 
                        "name": g['Rejon'].iloc[0] if mode != "Wspólna trasa" else "Całość", 
                        "pts": len(g)
                    })
                st.rerun()

    # --- MAPA ---
    m = folium.Map()
    if st.session_state['start_coords']: folium.Marker([st.session_state['start_coords']['lat'], st.session_state['start_coords']['lng']], icon=folium.Icon(color='green', icon='play', prefix='fa')).add_to(m)
    if st.session_state['meta_coords']: folium.Marker([st.session_state['meta_coords']['lat'], st.session_state['meta_coords']['lng']], icon=folium.Icon(color='red', icon='stop', prefix='fa')).add_to(m)
    
    for g in st.session_state['geometries']:
        folium.PolyLine([[c[1], c[0]] for c in g['geom']], color=g['color'], weight=5, opacity=0.8).add_to(m)
    
    if show_pins:
        for _, r in f_df.iterrows():
            folium.CircleMarker([r['lat'], r['lng']], radius=5, color='#007bff', fill=True, fill_opacity=0.7, tooltip=r['Punkt']).add_to(m)
    
    st_folium(m, width="100%", height=550)

    # --- 9. WYNIKI ---
    if st.session_state['geometries']:
        st.markdown("### 📊 Wyniki i Tabele")
        
        # Statystyki w kolumnach
        m_cols = st.columns(len(st.session_state['geometries']))
        for idx, g in enumerate(st.session_state['geometries']):
            with m_cols[idx]:
                st.metric(g['name'], f"{g['dist']/1000:.2f} km", f"{int(g['time']//60)} min")
        
        # Tabele tras
        for idx, df in enumerate(st.session_state['optimized_list']):
            name = st.session_state['geometries'][idx]['name']
            with st.expander(f"📋 Szczegółowa trasa: {name}"):
                res_df = df[['Punkt', 'Rejon']].reset_index()
                res_df.columns = ['Kolejność', 'Nazwa Punktu', 'Plik/Rejon']
                st.dataframe(res_df, use_container_width=True, hide_index=True)
                csv = res_df.to_csv(index=False).encode('utf-8')
                st.download_button(f"Pobierz listę {name}", csv, f"trasa_{name}.csv", "text/csv")
else:
    st.info("Dodaj pliki KML za pomocą przycisku na górze.")
