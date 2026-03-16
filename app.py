import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
import re
import time
import math
import json

# --- 1. BEZPIECZNY SYSTEM LOGOWANIA ---

def logout():
    st.session_state['authenticated'] = False
    st.rerun()

# Inicjalizacja stanu autoryzacji
if 'authenticated' not in st.session_state:
    st.session_state['authenticated'] = False

# Ekran logowania
if not st.session_state['authenticated']:
    st.set_page_config(page_title="Logowanie", page_icon="🔐")
    st.title("🔐 Dostęp chroniony")
    
    with st.form("login_form"):
        pwd_input = st.text_input("Wpisz hasło dostępu:", type="password")
        submit_button = st.form_submit_button("Zaloguj")
        
        if submit_button:
            if "password" in st.secrets:
                if pwd_input == st.secrets["password"]:
                    # Sukces: ustawiamy flagę tylko w pamięci serwera (session_state)
                    st.session_state['authenticated'] = True
                    st.rerun()
                else:
                    st.error("❌ Błędne hasło")
            else:
                st.error("Błąd: Skonfiguruj hasło w 'Secrets'.")
    st.stop()

# Jeśli kod dojdzie tutaj, oznacza to, że użytkownik przeszedł przez st.form powyżej

# --- 2. GŁÓWNA LOGIKA APLIKACJI ---

st.set_page_config(page_title="Optymalizator Tras", layout="wide")

# STYLIZACJA CSS
st.markdown("""
    <style>
    html, body, [class*="css"] { font-size: 14px; }
    .stTextInput label, .stSelectbox label, .stFileUploader label { font-size: 12px !important; margin-bottom: 2px; }
    input { font-size: 13px !important; padding: 5px !important; }
    .stButton button { font-size: 12px !important; padding: 2px 10px !important; min-height: 30px !important; width: 100%; }
    div[data-testid="column"] { display: flex; align-items: center; justify-content: center; gap: 5px; }
    .logout-btn button { background-color: #ff4b4b !important; color: white !important; font-weight: bold; }
    .selection-info { font-size: 13px; color: #1e1e1e; background-color: #e8f0fe; padding: 12px; border-radius: 8px; border-left: 6px solid #4285f4; margin-bottom: 10px; }
    </style>
    """, unsafe_allow_html=True)

# Inicjalizacja stanów
if 'saved_locations' not in st.session_state: st.session_state['saved_locations'] = {}
if 'projects' not in st.session_state: st.session_state['projects'] = {}
if 'data' not in st.session_state: st.session_state['data'] = pd.DataFrame(columns=['address', 'display_name', 'lat', 'lng'])
if 'start_name' not in st.session_state: st.session_state['start_name'] = "Nie wybrano"
if 'meta_name' not in st.session_state: st.session_state['meta_name'] = "Nie wybrano"
if 'start_addr' not in st.session_state: st.session_state['start_addr'] = ""
if 'meta_addr' not in st.session_state: st.session_state['meta_addr'] = ""

# Funkcje pomocnicze
def parse_kml_custom(file_content):
    placemarks = re.findall(r'<Placemark>(.*?)</Placemark>', file_content, re.DOTALL)
    data = []
    for pm in placemarks:
        name_match = re.search(r'<name>(.*?)</name>', pm)
        name = name_match.group(1) if name_match else "Punkt"
        lat_m = re.search(r'<Data name="Latitude">\s*<value>(.*?)</value>', pm, re.IGNORECASE)
        lng_m = re.search(r'<Data name="Longitude">\s*<value>(.*?)</value>', pm, re.IGNORECASE)
        lat, lng = None, None
        if lat_m and lng_m:
            try:
                lat, lng = float(lat_m.group(1).replace(',', '.')), float(lng_m.group(1).replace(',', '.'))
            except: pass
        if lat is None:
            coords = re.search(r'<coordinates>\s*([\d\.\-]+),\s*([\d\.\-]+)', pm)
            if coords: lng, lat = float(coords.group(1)), float(coords.group(2))
        if lat is not None: data.append({"address": name, "display_name": name, "lat": lat, "lng": lng})
    return pd.DataFrame(data)

def geocode_single(address, geolocator):
    try:
        time.sleep(1.1)
        loc = geolocator.geocode(address, timeout=10)
        return (loc.latitude, loc.longitude) if loc else (None, None)
    except: return (None, None)

# --- PANEL BOCZNY (SIDEBAR) ---

# 1. SEKCOJA: KONFIGURACJA TRASY (Bez pól tekstowych)
with st.sidebar.expander("🚀 Konfiguracja Trasy", expanded=True):
    st.markdown(f"""
    <div class="selection-info">
    <b>Wybrano do pracy:</b><br>
    📍 Start: <b>{st.session_state['start_name']}</b><br>
    🏁 Meta: <b>{st.session_state['meta_name']}</b>
    </div>
    """, unsafe_allow_html=True)
    
    up_kml = st.file_uploader("Wgraj plik KML rejonu", type=['kml'])
    if up_kml and st.button("Wczytaj punkty z KML"):
        new_pts = parse_kml_custom(up_kml.read().decode('utf-8'))
        st.session_state['data'] = pd.concat([st.session_state['data'], new_pts], ignore_index=True).drop_duplicates(subset=['lat', 'lng'])
        st.rerun()
    
    if st.button("🗑️ Wyczyść aktualne punkty"):
        st.session_state['data'] = pd.DataFrame(columns=['address', 'display_name', 'lat', 'lng'])
        st.session_state['start_name'], st.session_state['meta_name'] = "Nie wybrano", "Nie wybrano"
        st.session_state['start_addr'], st.session_state['meta_addr'] = "", ""
        if 'optimized' in st.session_state: del st.session_state['optimized']
        st.rerun()

# 2. SEKCOJA: BAZY (Przyciski S / M)
with st.sidebar.expander("📍 Twoje Bazy", expanded=False):
    with st.form("add_base_form", clear_on_submit=True):
        n_n = st.text_input("Nazwa (np. WER):")
        n_a = st.text_input("Pełny adres:")
        if st.form_submit_button("Dodaj nową bazę"):
            if n_n and n_a:
                st.session_state['saved_locations'][n_n] = n_a
                st.rerun()
    
    st.divider()
    for n, a in st.session_state['saved_locations'].items():
        st.write(f"**{n}**")
        c1, c2, c3 = st.columns([1, 1, 0.6])
        if c1.button(f"S", key=f"s_{n}"):
            st.session_state['start_addr'] = a
            st.session_state['start_name'] = n
            st.toast(f"Ustawiono START: {n}")
            st.rerun()
        if c2.button(f"M", key=f"m_{n}"):
            st.session_state['meta_addr'] = a
            st.session_state['meta_name'] = n
            st.toast(f"Ustawiono METĘ: {n}")
            st.rerun()
        if c3.button("🗑️", key=f"d_{n}"):
            del st.session_state['saved_locations'][n]
            st.rerun()

# 3. SEKCOJA: PROJEKTY
with st.sidebar.expander("📁 Zapisane Projekty", expanded=False):
    p_name = st.text_input("Nazwa projektu:")
    if st.button("Zapisz bieżący stan"):
        if p_name:
            st.session_state['projects'][p_name] = {
                'data': st.session_state['data'].copy(), 
                'start_addr': st.session_state['start_addr'], 
                'meta_addr': st.session_state['meta_addr'],
                'start_name': st.session_state['start_name'],
                'meta_name': st.session_state['meta_name']
            }
            st.toast(f"Zapisano projekt: {p_name}")

    if st.session_state['projects']:
        st.divider()
        sel_p = st.selectbox("Wczytaj projekt:", list(st.session_state['projects'].keys()))
        c_l, c_d = st.columns(2)
        if c_l.button("Wczytaj"):
            pr = st.session_state['projects'][sel_p]
            st.session_state['data'] = pr['data'].copy()
            st.session_state['start_addr'] = pr['start_addr']
            st.session_state['meta_addr'] = pr['meta_addr']
            st.session_state['start_name'] = pr['start_name']
            st.session_state['meta_name'] = pr['meta_name']
            if 'optimized' in st.session_state: del st.session_state['optimized']
            st.rerun()
        if c_d.button("Usuń"):
            del st.session_state['projects'][sel_p]
            st.rerun()

# 4. SEKCOJA: KOPIA ZAPASOWA
with st.sidebar.expander("💾 Kopia zapasowa", expanded=False):
    full_export = {
        "saved_locations": st.session_state['saved_locations'],
        "projects": {k: {
            "start_addr": v["start_addr"], "meta_addr": v["meta_addr"], 
            "start_name": v["start_name"], "meta_name": v["meta_name"],
            "data": v["data"].to_dict()
        } for k, v in st.session_state['projects'].items()}
    }
    st.download_button("📥 Pobierz bazę (JSON)", data=json.dumps(full_export), file_name="backup_tras.json")
    up_backup = st.file_uploader("📤 Wczytaj bazę", type="json")
    if up_backup:
        try:
            b = json.load(up_backup)
            st.session_state['saved_locations'] = b["saved_locations"]
            for k, v in b["projects"].items():
                st.session_state['projects'][k] = {
                    "start_addr": v["start_addr"], "meta_addr": v["meta_addr"], 
                    "start_name": v["start_name"], "meta_name": v["meta_name"],
                    "data": pd.DataFrame(v["data"])
                }
            st.success("Wczytano pomyślnie!")
        except: st.error("Błąd pliku.")

st.sidebar.markdown('<div class="logout-btn">', unsafe_allow_html=True)
if st.sidebar.button("🔓 WYLOGUJ MNIE"):
    logout()
st.sidebar.markdown('</div>', unsafe_allow_html=True)

# --- PANEL GŁÓWNY ---
df = st.session_state['data']
if not df.empty:
    if st.button("🚀 OBLICZ OPTYMALNĄ TRASĘ", type="primary", use_container_width=True):
        if st.session_state['start_addr'] == "" or st.session_state['meta_addr'] == "":
            st.error("Wybierz Start i Metę z sekcji 'Twoje Bazy'!")
        else:
            geolocator = Nominatim(user_agent="opt_v27")
            s_lat, s_lng = geocode_single(st.session_state['start_addr'], geolocator)
            m_lat, m_lng = geocode_single(st.session_state['meta_addr'], geolocator)
            if s_lat and m_lat:
                route, current = [{"display_name": f"🏠 START ({st.session_state['start_name']})", "lat": s_lat, "lng": s_lng}], {"lat": s_lat, "lng": s_lng}
                unvisited = df.to_dict('records')
                while unvisited:
                    nxt = min(unvisited, key=lambda x: math.sqrt((current['lat']-x['lat'])**2 + (current['lng']-x['lng'])**2))
                    route.append(nxt)
                    current = nxt
                    unvisited.remove(nxt)
                route.append({"display_name": f"🏁 META ({st.session_state['meta_name']})", "lat": m_lat, "lng": m_lng})
                st.session_state['optimized'] = pd.DataFrame(route)
                st.rerun()
            else:
                st.error("Nie udało się zlokalizować bazy. Sprawdź poprawność adresu.")

    res_df = st.session_state.get('optimized', df)
    cl, cr = st.columns([1, 2.5])
    with cl:
        st.dataframe(res_df[['display_name']], use_container_width=True, height=600)
    with cr:
        m_df = res_df.dropna(subset=['lat', 'lng'])
        if not m_df.empty:
            m = folium.Map(location=[m_df['lat'].mean(), m_df['lng'].mean()], zoom_start=11)
            pts = []
            for i, r in m_df.iterrows():
                color = 'green' if i == 0 else ('red' if i == len(m_df)-1 and 'optimized' in st.session_state else 'blue')
                folium.Marker([r['lat'], r['lng']], tooltip=r['display_name'], icon=folium.Icon(color=color)).addTo(m)
                pts.append([r['lat'], r['lng']])
            if 'optimized' in st.session_state: folium.PolyLine(pts, color="royalblue", weight=4).addTo(m)
            st_folium(m, width="100%", height=600, key="map_v27")
else:
    st.info("👈 Wgraj plik KML i wybierz bazy (Start/Meta), aby rozpocząć.")
