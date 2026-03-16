import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
import re
import time
import math
import json

# --- 1. BEZPIECZNA WERYFIKACJA HASŁA ---
# Hasło musi być ustawione w panelu Streamlit Cloud (Settings -> Secrets)
if 'authenticated' not in st.session_state:
    st.session_state['authenticated'] = False

def check_password():
    if "password" in st.secrets:
        if st.session_state["password_input"] == st.secrets["password"]:
            st.session_state["authenticated"] = True
            del st.session_state["password_input"]
        else:
            st.error("❌ Błędne hasło")
    else:
        st.error("Błąd: Hasło nie zostało ustawione w sekcji Secrets.")

if not st.session_state['authenticated']:
    st.title("🔐 Dostęp chroniony")
    st.text_input("Wpisz hasło dostępu:", type="password", key="password_input", on_change=check_password)
    st.info("Podpowiedź: Hasło jest przechowywane w bezpiecznych ustawieniach serwera.")
    st.stop()

# --- 2. GŁÓWNA LOGIKA APLIKACJI (Uruchomi się tylko po poprawnym haśle) ---

st.set_page_config(page_title="Optymalizator Tras", layout="wide")

st.title("🗺️ Optymalizator Tras")

# Styl CSS do wyśrodkowania przycisków w kolumnach
st.markdown("""
    <style>
    div[data-testid="column"] { display: flex; align-items: center; justify-content: center; }
    .stButton button { width: 100%; }
    </style>
    """, unsafe_allow_html=True)

# Inicjalizacja pamięci podręcznej (Session State)
if 'saved_locations' not in st.session_state: st.session_state['saved_locations'] = {}
if 'projects' not in st.session_state: st.session_state['projects'] = {}
if 'data' not in st.session_state: st.session_state['data'] = pd.DataFrame(columns=['address', 'display_name', 'lat', 'lng'])
if 'start_addr' not in st.session_state: st.session_state['start_addr'] = ""
if 'meta_addr' not in st.session_state: st.session_state['meta_addr'] = ""

# --- FUNKCJE POMOCNICZE ---

def parse_kml_custom(file_content):
    """Parser obsługujący standardowe koordynaty oraz tagi Latitude/Longitude."""
    placemarks = re.findall(r'<Placemark>(.*?)</Placemark>', file_content, re.DOTALL)
    data = []
    for pm in placemarks:
        name_match = re.search(r'<name>(.*?)</name>', pm)
        name = name_match.group(1) if name_match else "Punkt"
        
        # Próba wyciągnięcia Latitude/Longitude z danych dodatkowych
        lat_m = re.search(r'<Data name="Latitude">\s*<value>(.*?)</value>', pm, re.IGNORECASE)
        lng_m = re.search(r'<Data name="Longitude">\s*<value>(.*?)</value>', pm, re.IGNORECASE)
        
        lat, lng = None, None
        if lat_m and lng_m:
            try:
                lat = float(lat_m.group(1).replace(',', '.'))
                lng = float(lng_m.group(1).replace(',', '.'))
            except: pass
        
        # Jeśli nie znaleziono, szukaj w standardowym tagu <coordinates>
        if lat is None:
            coords = re.search(r'<coordinates>\s*([\d\.\-]+),\s*([\d\.\-]+)', pm)
            if coords:
                lng, lat = float(coords.group(1)), float(coords.group(2))
        
        if lat is not None:
            data.append({"address": name, "display_name": name, "lat": lat, "lng": lng})
    return pd.DataFrame(data)

def geocode_single(address, geolocator):
    """Geokodowanie adresu przy użyciu Nominatim."""
    try:
        time.sleep(1.1) # Opóźnienie wymagane przez politykę Nominatim
        loc = geolocator.geocode(address, timeout=10)
        return (loc.latitude, loc.longitude) if loc else (None, None)
    except: return (None, None)

# --- SIDEBAR: KOPIA ZAPASOWA ---
st.sidebar.header("💾 Kopia zapasowa")
full_export = {
    "saved_locations": st.session_state['saved_locations'],
    "projects": {k: {"start": v["start"], "meta": v["meta"], "data": v["data"].to_dict()} 
                 for k, v in st.session_state['projects'].items()}
}
st.sidebar.download_button(
    "📥 Pobierz bazę na dysk", 
    data=json.dumps(full_export), 
    file_name="backup_optymalizator.json",
    use_container_width=True
)

up_backup = st.sidebar.file_uploader("📤 Wgraj bazę z pliku", type="json")
if up_backup:
    try:
        b = json.load(up_backup)
        st.session_state['saved_locations'] = b["saved_locations"]
        for k, v in b["projects"].items():
            st.session_state['projects'][k] = {"start": v["start"], "meta": v["meta"], "data": pd.DataFrame(v["data"])}
        st.sidebar.success("Baza danych wczytana!")
    except:
        st.sidebar.error("Błędny plik kopii zapasowej.")

# --- SIDEBAR: PROJEKTY ---
st.sidebar.divider()
st.sidebar.header("📁 Menedżer Projektów")
p_name = st.sidebar.text_input("Nazwa nowego projektu:")
if st.sidebar.button("Zapisz bieżący rejon", use_container_width=True):
    if p_name:
        st.session_state['projects'][p_name] = {
            'data': st.session_state['data'].copy(),
            'start': st.session_state['start_addr'],
            'meta': st.session_state['meta_addr']
        }
        st.sidebar.success(f"Zapisano: {p_name}")
        st.rerun()

if st.session_state['projects']:
    sel_p = st.sidebar.selectbox("Twoje zapisane rejony:", list(st.session_state['projects'].keys()))
    col_l, col_d = st.sidebar.columns(2)
    if col_l.button("Wczytaj"):
        pr = st.session_state['projects'][sel_p]
        st.session_state['data'], st.session_state['start_addr'], st.session_state['meta_addr'] = pr['data'].copy(), pr['start'], pr['meta']
        if 'optimized' in st.session_state: del st.session_state['optimized']
        st.rerun()
    if col_d.button("Usuń"):
        del st.session_state['projects'][sel_p]
        st.rerun()

# --- SIDEBAR: PUNKTY STAŁE ---
st.sidebar.divider()
st.sidebar.header("📍 Punkty Stałe (Bazy)")
with st.sidebar.expander("Dodaj nową bazę"):
    n_n = st.text_input("Nazwa (np. WER):")
    n_a = st.text_input("Pełny adres:")
    if st.button("Zapisz bazę"):
        if n_n and n_a:
            st.session_state['saved_locations'][n_n] = n_a
            st.rerun()

for n, a in st.session_state['saved_locations'].items():
    c1, c2, c3 = st.sidebar.columns([1, 1, 0.6])
    if c1.button(f"S: {n}", key=f"s_{n}", help="Ustaw jako Start"):
        st.session_state['start_addr'] = a
    if c2.button(f"M: {n}", key=f"m_{n}", help="Ustaw jako Meta"):
        st.session_state['meta_addr'] = a
    if c3.button("🗑️", key=f"d_{n}"):
        del st.session_state['saved_locations'][n]
        st.rerun()

# --- SIDEBAR: KONFIGURACJA TRASY ---
st.sidebar.divider()
st.sidebar.header("🚀 Konfiguracja Trasy")
st.session_state['start_addr'] = st.sidebar.text_input("Adres Startu:", value=st.session_state['start_addr'])
st.session_state['meta_addr'] = st.sidebar.text_input("Adres Mety:", value=st.session_state['meta_addr'])

up_kml = st.sidebar.file_uploader("Dodaj plik KML rejonu", type=['kml'])
if up_kml and st.sidebar.button("Wczytaj punkty z pliku", use_container_width=True):
    new_pts = parse_kml_custom(up_kml.read().decode('utf-8'))
    if not new_pts.empty:
        st.session_state['data'] = pd.concat([st.session_state['data'], new_pts], ignore_index=True).drop_duplicates(subset=['lat', 'lng'])
        st.sidebar.success(f"Dodano {len(new_pts)} punktów.")
    else:
        st.sidebar.error("Nie znaleziono danych w pliku.")

if st.sidebar.button("🗑️ Wyczyść aktualny rejon", use_container_width=True):
    st.session_state['data'] = pd.DataFrame(columns=['address', 'display_name', 'lat', 'lng'])
    if 'optimized' in st.session_state: del st.session_state['optimized']
    st.rerun()

# --- PANEL GŁÓWNY ---
df = st.session_state['data']

if not df.empty:
    if st.button("🚀 OBLICZ OPTYMALNĄ TRASĘ", type="primary", use_container_width=True):
        if not st.session_state['start_addr'] or not st.session_state['meta_addr']:
            st.error("Ustaw adres Startu i Mety w panelu bocznym.")
        else:
            geolocator = Nominatim(user_agent="optymalizator_tras_v22")
            with st.spinner("Lokalizowanie punktów bazy..."):
                s_lat, s_lng = geocode_single(st.session_state['start_addr'], geolocator)
                m_lat, m_lng = geocode_single(st.session_state['meta_addr'], geolocator)
            
            if s_lat and m_lat:
                start_node = {"display_name": "🏠 START", "lat": s_lat, "lng": s_lng}
                end_node = {"display_name": "🏁 META", "lat": m_lat, "lng": m_lng}
                
                unvisited = df.to_dict('records')
                route, current = [start_node], start_node
                
                # Prosty algorytm najbliższego sąsiada (TSP heuristic)
                while unvisited:
                    nxt = min(unvisited, key=lambda x: math.sqrt((current['lat']-x['lat'])**2 + (current['lng']-x['lng'])**2))
                    route.append(nxt)
                    unvisited.remove(nxt)
                
                route.append(end_node)
                st.session_state['optimized'] = pd.DataFrame(route)
                st.rerun()
            else:
                st.error("Nie udało się odnaleźć lokalizacji Startu lub Mety.")

    res_df = st.session_state.get('optimized', df)
    
    col_list, col_map = st.columns([1, 2])
    with col_list:
        st.subheader("📋 Planowana kolejność")
        st.dataframe(res_df[['display_name']], use_container_width=True, height=600)
    
    with col_map:
        st.subheader("🗺️ Wizualizacja")
        try:
            m_df = res_df.dropna(subset=['lat', 'lng'])
            if not m_df.empty:
                m = folium.Map(location=[m_df['lat'].mean(), m_df['lng'].mean()], zoom_start=11)
                pts = []
                for i, row in m_df.iterrows():
                    # Kolory: Start - Zielony, Meta - Czerwony (jeśli trasa obliczona), Inne - Niebieski
                    color = 'green' if i == 0 else ('red' if i == len(m_df)-1 and 'optimized' in st.session_state else 'blue')
                    folium.Marker(
                        [row['lat'], row['lng']], 
                        tooltip=f"{i+1}. {row['display_name']}", 
                        icon=folium.Icon(color=color)
                    ).addTo(m)
                    pts.append([row['lat'], row['lng']])
                
                if 'optimized' in st.session_state and len(pts) > 1:
                    folium.PolyLine(pts, color="royalblue", weight=4, opacity=0.8).addTo(m)
                
                st_folium(m, width="100%", height=600, key="opt_map_v22")
        except Exception as e:
            st.warning("Nie można wyświetlić mapy: brak poprawnych koordynatów.")
else:
    st.info("👈 Zacznij od wgrania pliku KML lub wczytania zapisanego projektu w panelu bocznym.")
