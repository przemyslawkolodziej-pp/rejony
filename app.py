import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
import re
import time
import math
import json

# --- 1. SYSTEM LOGOWANIA ---

def logout():
    st.session_state['authenticated'] = False
    st.query_params.clear()
    st.rerun()

if "logged_in" in st.query_params and st.query_params["logged_in"] == "true":
    st.session_state['authenticated'] = True

if 'authenticated' not in st.session_state:
    st.session_state['authenticated'] = False

def check_password():
    if "password" in st.secrets:
        if st.session_state["password_input"] == st.secrets["password"]:
            st.session_state["authenticated"] = True
            st.query_params["logged_in"] = "true"
            del st.session_state["password_input"]
        else:
            st.error("❌ Błędne hasło")
    else:
        st.error("Błąd: Skonfiguruj hasło w 'Secrets'.")

if not st.session_state['authenticated']:
    st.title("🔐 Dostęp chroniony")
    st.text_input("Wpisz hasło dostępu:", type="password", key="password_input", on_change=check_password)
    st.stop()

# --- 2. GŁÓWNA LOGIKA APLIKACJI ---

st.set_page_config(page_title="Optymalizator Tras", layout="wide")
st.title("🗺️ Optymalizator Tras")

# Styl CSS
st.markdown("""
    <style>
    div[data-testid="column"] { display: flex; align-items: center; justify-content: center; }
    .stButton button { width: 100%; }
    .logout-btn button { background-color: #ff4b4b !important; color: white !important; }
    </style>
    """, unsafe_allow_html=True)

# Inicjalizacja stanów
if 'saved_locations' not in st.session_state: st.session_state['saved_locations'] = {}
if 'projects' not in st.session_state: st.session_state['projects'] = {}
if 'data' not in st.session_state: st.session_state['data'] = pd.DataFrame(columns=['address', 'display_name', 'lat', 'lng'])
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

# 1. SEKCOJA: TRASA
with st.sidebar.expander("🚀 Konfiguracja Trasy", expanded=True):
    st.session_state['start_addr'] = st.text_input("Start:", value=st.session_state['start_addr'])
    st.session_state['meta_addr'] = st.text_input("Meta:", value=st.session_state['meta_addr'])
    up_kml = st.file_uploader("Dodaj plik KML", type=['kml'])
    if up_kml and st.button("Wczytaj punkty z KML"):
        new_pts = parse_kml_custom(up_kml.read().decode('utf-8'))
        st.session_state['data'] = pd.concat([st.session_state['data'], new_pts], ignore_index=True).drop_duplicates(subset=['lat', 'lng'])
        st.rerun()
    if st.button("🗑️ Wyczyść mapę"):
        st.session_state['data'] = pd.DataFrame(columns=['address', 'display_name', 'lat', 'lng'])
        if 'optimized' in st.session_state: del st.session_state['optimized']
        st.rerun()

# 2. SEKCOJA: PROJEKTY
with st.sidebar.expander("📁 Projekty i Rejony", expanded=False):
    p_name = st.text_input("Nazwa dla zapisu:")
    if st.button("Zapisz aktualny stan"):
        if p_name:
            st.session_state['projects'][p_name] = {'data': st.session_state['data'].copy(), 'start': st.session_state['start_addr'], 'meta': st.session_state['meta_addr']}
            st.success(f"Zapisano {p_name}")

    if st.session_state['projects']:
        st.divider()
        sel_p = st.selectbox("Twoje rejony:", list(st.session_state['projects'].keys()))
        c_l, c_d = st.columns(2)
        if c_l.button("Wczytaj"):
            pr = st.session_state['projects'][sel_p]
            st.session_state['data'], st.session_state['start_addr'], st.session_state['meta_addr'] = pr['data'].copy(), pr['start'], pr['meta']
            if 'optimized' in st.session_state: del st.session_state['optimized']
            st.rerun()
        if c_d.button("Usuń"):
            del st.session_state['projects'][sel_p]
            st.rerun()

# 3. SEKCOJA: BAZY (PUNKTY STAŁE)
with st.sidebar.expander("📍 Punkty Stałe (Bazy)", expanded=False):
    n_n, n_a = st.text_input("Nazwa bazy:"), st.text_input("Adres bazy:")
    if st.button("Dodaj bazę"):
        if n_n and n_a:
            st.session_state['saved_locations'][n_n] = n_a
            st.rerun()
    
    st.divider()
    for n, a in st.session_state['saved_locations'].items():
        st.write(f"**{n}**")
        c1, c2, c3 = st.columns([1, 1, 0.6])
        if c1.button(f"Start", key=f"s_{n}"): st.session_state['start_addr'] = a
        if c2.button(f"Meta", key=f"m_{n}"): st.session_state['meta_addr'] = a
        if c3.button("🗑️", key=f"d_{n}"):
            del st.session_state['saved_locations'][n]
            st.rerun()

# 4. SEKCOJA: KOPIA ZAPASOWA (PRZENIESIONA NIŻEJ)
with st.sidebar.expander("💾 Kopia zapasowa danych", expanded=False):
    st.write("Pobierz dane, aby nie zginęły po restarcie serwera.")
    full_export = {
        "saved_locations": st.session_state['saved_locations'],
        "projects": {k: {"start": v["start"], "meta": v["meta"], "data": v["data"].to_dict()} for k, v in st.session_state['projects'].items()}
    }
    st.download_button("📥 Pobierz plik JSON", data=json.dumps(full_export), file_name="backup_optymalizator.json")
    
    st.divider()
    up_backup = st.file_uploader("📤 Wczytaj plik JSON", type="json")
    if up_backup:
        try:
            b = json.load(up_backup)
            st.session_state['saved_locations'] = b["saved_locations"]
            for k, v in b["projects"].items():
                st.session_state['projects'][k] = {"start": v["start"], "meta": v["meta"], "data": pd.DataFrame(v["data"])}
            st.success("Dane wczytane!")
        except: st.error("Błąd pliku.")

# 5. PRZYCISK WYLOGOWANIA
st.sidebar.markdown('<div class="logout-btn">', unsafe_allow_html=True)
if st.sidebar.button("🔓 WYLOGUJ MNIE"):
    logout()
st.sidebar.markdown('</div>', unsafe_allow_html=True)

# --- PANEL GŁÓWNY (MAPA I LISTA) ---

df = st.session_state['data']
if not df.empty:
    if st.button("🚀 OBLICZ OPTYMALNĄ TRASĘ", type="primary", use_container_width=True):
        geolocator = Nominatim(user_agent="opt_v25")
        s_lat, s_lng = geocode_single(st.session_state['start_addr'], geolocator)
        m_lat, m_lng = geocode_single(st.session_state['meta_addr'], geolocator)
        if s_lat and m_lat:
            route, current = [{"display_name": "🏠 START", "lat": s_lat, "lng": s_lng}], {"lat": s_lat, "lng": s_lng}
            unvisited = df.to_dict('records')
            while unvisited:
                nxt = min(unvisited, key=lambda x: math.sqrt((current['lat']-x['lat'])**2 + (current['lng']-x['lng'])**2))
                route.append(nxt)
                current = nxt
                unvisited.remove(nxt)
            route.append({"display_name": "🏁 META", "lat": m_lat, "lng": m_lng})
            st.session_state['optimized'] = pd.DataFrame(route)
            st.rerun()

    res_df = st.session_state.get('optimized', df)
    cl, cr = st.columns([1, 2])
    with cl:
        st.subheader("📋 Plan")
        st.dataframe(res_df[['display_name']], use_container_width=True, height=600)
    with cr:
        st.subheader("🗺️ Mapa")
        m_df = res_df.dropna(subset=['lat', 'lng'])
        if not m_df.empty:
            m = folium.Map(location=[m_df['lat'].mean(), m_df['lng'].mean()], zoom_start=11)
            pts = []
            for i, r in m_df.iterrows():
                color = 'green' if i == 0 else ('red' if i == len(m_df)-1 and 'optimized' in st.session_state else 'blue')
                folium.Marker([r['lat'], r['lng']], tooltip=r['display_name'], icon=folium.Icon(color=color)).addTo(m)
                pts.append([r['lat'], r['lng']])
            if 'optimized' in st.session_state: folium.PolyLine(pts, color="royalblue", weight=4).addTo(m)
            st_folium(m, width="100%", height=600, key="map_v25")
else:
    st.info("👈 Rozwiń sekcję 'Konfiguracja Trasy', aby dodać punkty.")
