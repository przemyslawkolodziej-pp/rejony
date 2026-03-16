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
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()

if 'authenticated' not in st.session_state:
    st.session_state['authenticated'] = False

if not st.session_state['authenticated']:
    st.set_page_config(page_title="Logowanie", page_icon="🔐")
    st.title("🔐 Dostęp chroniony")
    with st.form("login_form"):
        pwd_input = st.text_input("Hasło:", type="password")
        if st.form_submit_button("Zaloguj"):
            if "password" in st.secrets and pwd_input == st.secrets["password"]:
                st.session_state['authenticated'] = True
                st.rerun()
            else:
                st.error("❌ Błędne hasło")
    st.stop()

# --- 2. GŁÓWNA APLIKACJA ---
st.set_page_config(page_title="Optymalizator", layout="wide")

# Inicjalizacja stanów
if 'data' not in st.session_state: st.session_state['data'] = pd.DataFrame()
if 'saved_locations' not in st.session_state: st.session_state['saved_locations'] = {}
if 'start_addr' not in st.session_state: st.session_state['start_addr'] = ""
if 'meta_addr' not in st.session_state: st.session_state['meta_addr'] = ""
if 'start_name' not in st.session_state: st.session_state['start_name'] = "Brak"
if 'meta_name' not in st.session_state: st.session_state['meta_name'] = "Brak"

def parse_kml_robust(file_content):
    placemarks = re.findall(r'<Placemark>(.*?)</Placemark>', file_content, re.DOTALL)
    pts = []
    for pm in placemarks:
        name_match = re.search(r'<name>(.*?)</name>', pm)
        name = name_match.group(1) if name_match else "Punkt"
        
        # Próba wyciągnięcia współrzędnych
        coord_match = re.search(r'<coordinates>\s*([\d\.\-]+),\s*([\d\.\-]+)', pm)
        lat_m = re.search(r'<Data name="Latitude">.*?<value>(.*?)</value>', pm, re.DOTALL | re.IGNORECASE)
        lng_m = re.search(r'<Data name="Longitude">.*?<value>(.*?)</value>', pm, re.DOTALL | re.IGNORECASE)
        
        try:
            if coord_match:
                lng, lat = float(coord_match.group(1)), float(coord_match.group(2))
            elif lat_m and lng_m:
                lat, lng = float(lat_m.group(1).replace(',', '.')), float(lng_m.group(1).replace(',', '.'))
            else: continue
            pts.append({"display_name": str(name), "lat": float(lat), "lng": float(lng)})
        except: continue
    return pd.DataFrame(pts)

# --- SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Ustawienia")
    up_kml = st.file_uploader("Wgraj KML", type=['kml'])
    if up_kml and st.button("Wczytaj punkty"):
        df_new = parse_kml_robust(up_kml.read().decode('utf-8'))
        st.session_state['data'] = df_new
        if 'optimized' in st.session_state: del st.session_state['optimized']
        st.rerun()
    
    st.divider()
    st.subheader("📍 Twoje Bazy")
    with st.form("new_base"):
        n_n, n_a = st.text_input("Nazwa:"), st.text_input("Adres:")
        if st.form_submit_button("Dodaj bazę") and n_n and n_a:
            st.session_state['saved_locations'][n_n] = n_a
            st.rerun()
            
    for n, a in st.session_state['saved_locations'].items():
        st.write(f"**{n}**")
        c1, c2, c3 = st.columns([1, 1, 0.5])
        if c1.button("S", key=f"s_{n}"): st.session_state.update({'start_addr': a, 'start_name': n})
        if c2.button("M", key=f"m_{n}"): st.session_state.update({'meta_addr': a, 'meta_name': n})
        if c3.button("🗑️", key=f"d_{n}"): del st.session_state['saved_locations'][n]; st.rerun()

    if st.button("🔓 WYLOGUJ", use_container_width=True): logout()

# --- PANEL GŁÓWNY ---
st.title("🗺️ Mapa i Optymalizacja")
st.markdown(f"**Wybrany Start:** {st.session_state['start_name']} | **Wybrana Meta:** {st.session_state['meta_name']}")

df = st.session_state['data']

if not df.empty:
    if st.button("🚀 OBLICZ OPTYMALNĄ TRASĘ", type="primary", use_container_width=True):
        if not st.session_state['start_addr'] or not st.session_state['meta_addr']:
            st.error("Wybierz Start i Metę w panelu bocznym!")
        else:
            with st.spinner("Przetwarzanie..."):
                gl = Nominatim(user_agent="route_opt_v32")
                loc_s = gl.geocode(st.session_state['start_addr'], timeout=10)
                time.sleep(1.1)
                loc_m = gl.geocode(st.session_state['meta_addr'], timeout=10)
                
                if loc_s and loc_m:
                    route = [{"display_name": f"START: {st.session_state['start_name']}", "lat": loc_s.latitude, "lng": loc_s.longitude}]
                    unvisited = df.to_dict('records')
                    curr = {"lat": loc_s.latitude, "lng": loc_s.longitude}
                    
                    while unvisited:
                        nxt = min(unvisited, key=lambda x: math.sqrt((curr['lat']-x['lat'])**2 + (curr['lng']-x['lng'])**2))
                        route.append(nxt)
                        curr = nxt
                        unvisited.remove(nxt)
                        
                    route.append({"display_name": f"META: {st.session_state['meta_name']}", "lat": loc_m.latitude, "lng": loc_m.longitude})
                    st.session_state['optimized'] = pd.DataFrame(route)
                    st.rerun()
                else:
                    st.error("Błąd geokodowania baz. Sprawdź adresy.")

    # LOGIKA MAPY
    res_df = st.session_state.get('optimized', df)
    
    col_t, col_m = st.columns([1, 2])
    
    with col_t:
        st.write("📋 Lista:")
        st.dataframe(res_df[['display_name']], use_container_width=True, height=500)
    
    with col_m:
        # 1. Tworzymy obiekt mapy
        center_lat = res_df['lat'].iloc[0] if not res_df.empty else 52.2
        center_lng = res_df['lng'].iloc[0] if not res_df.empty else 19.1
        
        m = folium.Map(location=[center_lat, center_lng], zoom_start=11, control_scale=True)
        
        # 2. Dodajemy markery
        all_coords = []
        for i, row in res_df.iterrows():
            l_val, ln_val = float(row['lat']), float(row['lng'])
            
            # Kolory markerów
            m_color = 'blue'
            if 'optimized' in st.session_state:
                if i == 0: m_color = 'green'
                elif i == len(res_df) - 1: m_color = 'red'
            
            folium.Marker(
                location=[l_val, ln_val],
                popup=str(row['display_name']),
                tooltip=str(row['display_name']),
                icon=folium.Icon(color=m_color, icon='info-sign')
            ).add_to(m)
            all_coords.append([l_val, ln_val])
        
        # 3. Rysujemy linię jeśli trasa jest zoptymalizowana
        if 'optimized' in st.session_state and len(all_coords) > 1:
            folium.PolyLine(all_coords, color="blue", weight=3, opacity=0.8).add_to(m)
            m.fit_bounds(all_coords) # Automatyczne dopasowanie widoku do trasy

        # 4. KLUCZOWE: Wyświetlanie mapy z unikalnym ID sesji/czasu
        st_folium(m, width="100%", height=500, key=f"map_render_{len(res_df)}")

else:
    st.info("Wgraj KML w panelu bocznym.")
