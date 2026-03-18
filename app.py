import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
import re, math, json, requests, os
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# --- 1. KONFIGURACJA ---
# TUTAJ WKLEJ ID SWOJEGO ARKUSZA
SHEET_ID = "1mTMjUKoHNw-okxpYSAeLsVD7vdxYR1P-ZjelWt9IHAE" 

st.set_page_config(page_title="Optymalizator Tras", page_icon="🗺️", layout="wide")

# --- 2. INTEGRACJA Z GOOGLE SHEETS ---
def get_gspread_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_dict = dict(st.secrets["gcp_service_account"])
    if "\\n" in creds_dict["private_key"]:
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds)

def sync_save():
    if SHEET_ID == "TU_WKLEJ_SWOJE_ID_ARKUSZA":
        st.error("Błąd: Nie ustawiono SHEET_ID w kodzie!")
        return
    
    msg = st.toast("⏳ Łączenie z Google Sheets...", icon="🔄")
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
        
        st.sidebar.success("Zapisano w Google Sheets! ✅")
        st.toast("Dane wysłane pomyślnie!", icon="✅")
    except Exception as e:
        st.error(f"❌ BŁĄD GOOGLE: {e}")

def sync_load():
    if SHEET_ID == "TU_WKLEJ_SWOJE_ID_ARKUSZA": return
    try:
        client = get_gspread_client()
        sheet = client.open_by_key(SHEET_ID)
        # Wczytanie BAZ
        loc_data = sheet.worksheet("SavedLocations").get_all_records()
        if loc_data:
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

# --- 3. INICJALIZACJA ---
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

# --- 4. SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Zarządzanie")
    
    # Bazy - Przebudowana sekcja dodawania
    with st.expander("🏠 Bazy", expanded=True):
        if st.session_state['saved_locations']:
            sel_b = st.selectbox("Wybierz bazę:", ["---"] + sorted(st.session_state['saved_locations'].keys()))
            if sel_b != "---":
                addr = st.session_state['saved_locations'][sel_b]
                c1, c2, c3 = st.columns(3)
                if c1.button("🏠", key="s_btn"):
                    st.session_state.update({'start_name': sel_b, 'start_coords': get_lat_lng(addr)}); st.rerun()
                if c2.button("🏁", key="m_btn"):
                    st.session_state.update({'meta_name': sel_b, 'meta_coords': get_lat_lng(addr)}); st.rerun()
                if c3.button("🗑️", key="d_btn"):
                    del st.session_state['saved_locations'][sel_b]
                    sync_save()
                    st.rerun()
        
        st.markdown("---")
        # FORMULARZ DODAWANIA
        with st.form("add_base_form", clear_on_submit=True):
            new_n = st.text_input("Nazwa nowej bazy:")
            new_a = st.text_input("Adres:")
            if st.form_submit_button("➕ Dodaj i Zapisz"):
                if new_n and new_a:
                    st.session_state['saved_locations'][new_n] = new_a
                    sync_save()
                    st.rerun()

    # Projekty
    with st.expander("📁 Projekty", expanded=False):
        p_name = st.text_input("Nazwa projektu:")
        if st.button("💾 Zapisz Projekt"):
            if p_name:
                st.session_state['projects'][p_name] = {
                    'data': st.session_state['data'].copy(), 'start_name': st.session_state['start_name'], 'meta_name': st.session_state['meta_name'],
                    'start_coords': st.session_state['start_coords'], 'meta_coords': st.session_state['meta_coords'],
                    'optimized_list': [df.copy() for df in st.session_state['optimized_list']], 'geometries': st.session_state['geometries']
                }
                sync_save()
                st.rerun()
        
        if st.session_state['projects']:
            sel_p = st.selectbox("Otwórz:", ["---"] + sorted(st.session_state['projects'].keys()))
            if sel_p != "---":
                if st.button("📂 Wczytaj"):
                    st.session_state.update(st.session_state['projects'][sel_p]); st.rerun()
                if st.button("🗑️ Usuń Projekt"):
                    del st.session_state['projects'][sel_p]
                    sync_save()
                    st.rerun()

    # KML
    with st.expander("☁️ Wgrywanie KML", expanded=False):
        up = st.file_uploader("Dodaj pliki", type=['kml'], accept_multiple_files=True)
        if up and st.button("Wczytaj pliki"):
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

# --- 5. PANEL GŁÓWNY ---
st.title("🗺️ Optymalizator Tras")

c1, c2 = st.columns(2)
c1.info(f"🏠 START: {st.session_state['start_name']}")
c2.info(f"🏁 META: {st.session_state['meta_name']}")

# (Reszta kodu mapy i obliczeń - skrócona dla czytelności, taka sama jak w v102)
def get_lat_lng(address):
    try:
        gl = Nominatim(user_agent="v104_geo")
        loc = gl.geocode(address, timeout=10)
        return {"lat": loc.latitude, "lng": loc.longitude} if loc else None
    except: return None

if not st.session_state['data'].empty:
    u_files = sorted(st.session_state['data']['source_file'].unique().tolist())
    v_files = st.multiselect("Filtruj rejony:", u_files, default=u_files)
    
    m = folium.Map()
    pts = []
    if st.session_state['start_coords']: pts.append([st.session_state['start_coords']['lat'], st.session_state['start_coords']['lng']])
    if st.session_state['meta_coords']: pts.append([st.session_state['meta_coords']['lat'], st.session_state['meta_coords']['lng']])
    
    for _, r in st.session_state['data'][st.session_state['data']['source_file'].isin(v_files)].iterrows():
        folium.Marker([r['lat'], r['lng']], tooltip=r['display_name']).add_to(m)
        pts.append([r['lat'], r['lng']])
    
    if pts: m.fit_bounds(pts)
    st_folium(m, width="100%", height=500)
else:
    st.warning("👈 Zacznij od dodania bazy i wgrania plików KML.")
