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
        pwd_input = st.text_input("Wpisz hasło dostępu:", type="password")
        if st.form_submit_button("Zaloguj"):
            if "password" in st.secrets and pwd_input == st.secrets["password"]:
                st.session_state['authenticated'] = True
                st.rerun()
            else:
                st.error("❌ Błędne hasło")
    st.stop()

# --- 2. KONFIGURACJA ---
st.set_page_config(page_title="Optymalizator Tras", layout="wide")

st.markdown("""
    <style>
    html, body, [class*="css"] { font-size: 14px; }
    input { font-size: 13px !important; padding: 5px !important; }
    .stButton button { font-size: 11px !important; padding: 4px 2px !important; line-height: 1.2 !important; min-height: 40px !important; width: 100%; }
    .status-text { font-size: 11px; font-weight: bold; text-align: center; padding-top: 10px; margin-bottom: 0px; }
    .logout-btn button { background-color: #ff4b4b !important; color: white !important; font-weight: bold; }
    .selection-info { font-size: 13px; color: #1e1e1e; background-color: #e8f0fe; padding: 12px; border-radius: 8px; border-left: 6px solid #4285f4; margin-bottom: 10px; }
    div[data-testid="column"] { display: flex; align-items: center; justify-content: center; gap: 5px; }
    </style>
    """, unsafe_allow_html=True)

# Inicjalizacja stanów
for key in ['data', 'saved_locations', 'projects']:
    if key not in st.session_state: 
        st.session_state[key] = pd.DataFrame() if key == 'data' else {}

if 'start_addr' not in st.session_state: st.session_state.update({
    'start_addr': "", 'meta_addr': "", 'start_name': "Nie wybrano", 'meta_name': "Nie wybrano"
})

def parse_kml_robust(file_content):
    placemarks = re.findall(r'<Placemark>(.*?)</Placemark>', file_content, re.DOTALL)
    pts = []
    for pm in placemarks:
        name_match = re.search(r'<name>(.*?)</name>', pm)
        name = name_match.group(1) if name_match else "Punkt"
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

# --- PANEL BOCZNY ---
with st.sidebar:
    # 1. KONFIGURACJA TRASY
    with st.expander("🚀 Konfiguracja Trasy", expanded=True):
        st.markdown(f'<div class="selection-info"><b>Wybrano:</b><br>📍 S: {st.session_state["start_name"]}<br>🏁 M: {st.session_state["meta_name"]}</div>', unsafe_allow_html=True)
        up_kml = st.file_uploader("Wgraj KML", type=['kml'])
        if up_kml and st.button("Wczytaj punkty z KML"):
            st.session_state['data'] = parse_kml_robust(up_kml.read().decode('utf-8'))
            if 'optimized' in st.session_state: del st.session_state['optimized']
            st.rerun()
        if st.button("🗑️ Wyczyść aktualne punkty"):
            st.session_state['data'] = pd.DataFrame()
            st.session_state.update({'start_name': "Nie wybrano", 'meta_name': "Nie wybrano", 'start_addr': "", 'meta_addr': ""})
            if 'optimized' in st.session_state: del st.session_state['optimized']
            st.rerun()

    # 2. TWOJE BAZY
    with st.expander("📍 Twoje Bazy", expanded=False):
        with st.form("add_base", clear_on_submit=True):
            n_n, n_a = st.text_input("Nazwa:"), st.text_input("Adres:")
            if st.form_submit_button("Dodaj bazę") and n_n and n_a:
                st.session_state['saved_locations'][n_n] = n_a
                st.rerun()
        st.divider()
        for n, a in st.session_state['saved_locations'].items():
            is_s, is_m = (st.session_state['start_name'] == n), (st.session_state['meta_name'] == n)
            st.write(f"**{n}**")
            c1, c2, c3 = st.columns([1, 1, 0.4])
            with c1:
                if is_s: st.markdown('<p class="status-text">🟢 START</p>', unsafe_allow_html=True)
                else:
                    if st.button("Ustaw jako punkt Startu", key=f"s_{n}"):
                        st.session_state.update({'start_addr': a, 'start_name': n}); st.rerun()
            with c2:
                if is_m: st.markdown('<p class="status-text">🔴 META</p>', unsafe_allow_html=True)
                else:
                    if st.button("Ustaw jako punkt Mety", key=f"m_{n}"):
                        st.session_state.update({'meta_addr': a, 'meta_name': n}); st.rerun()
            with c3:
                if st.button("🗑️", key=f"d_{n}"): del st.session_state['saved_locations'][n]; st.rerun()
            st.divider()

    # 3. ZAPISANE PROJEKTY
    with st.expander("📁 Zapisane Projekty", expanded=False):
        p_name = st.text_input("Nazwa projektu:")
        if st.button("Zapisz stan"):
            if p_name:
                st.session_state['projects'][p_name] = {
                    'data': st.session_state['data'].copy(),
                    'start_addr': st.session_state['start_addr'], 'meta_addr': st.session_state['meta_addr'],
                    'start_name': st.session_state['start_name'], 'meta_name': st.session_state['meta_name']
                }
                st.toast(f"Zapisano: {p_name}")
        if st.session_state['projects']:
            st.divider()
            sel_p = st.selectbox("Wczytaj:", list(st.session_state['projects'].keys()))
            cl, cd = st.columns(2)
            if cl.button("Wczytaj"):
                pr = st.session_state['projects'][sel_p]
                st.session_state.update({'data': pr['data'].copy(), 'start_addr': pr['start_addr'], 'meta_addr': pr['meta_addr'], 'start_name': pr['start_name'], 'meta_name': pr['meta_name']})
                if 'optimized' in st.session_state: del st.session_state['optimized']
                st.rerun()
            if cd.button("Usuń"):
                del st.session_state['projects'][sel_p]
                st.rerun()

    # 4. KOPIA ZAPASOWA
    with st.expander("💾 Kopia zapasowa", expanded=False):
        export = {
            "saved_locations": st.session_state['saved_locations'],
            "projects": {k: {**v, "data": v["data"].to_dict()} for k, v in st.session_state['projects'].items()}
        }
        st.download_button("📥 Pobierz bazę (JSON)", data=json.dumps(export), file_name="backup_tras.json")
        up_json = st.file_uploader("📤 Wczytaj bazę", type="json")
        if up_json:
            try:
                b = json.load(up_json)
                st.session_state['saved_locations'] = b["saved_locations"]
                for k, v in b["projects"].items():
                    st.session_state['projects'][k] = {**v, "data": pd.DataFrame(v["data"])}
                st.success("Wczytano pomyślnie!")
            except: st.error("Błąd pliku.")

    st.markdown('<div class="logout-btn">', unsafe_allow_html=True)
    if st.button("🔓 WYLOGUJ MNIE"): logout()
    st.markdown('</div>', unsafe_allow_html=True)

# --- 3. PANEL GŁÓWNY ---
st.title("🗺️ Optymalizator Tras")
df = st.session_state['data']

if not df.empty:
    if st.button("🚀 OBLICZ OPTYMALNĄ TRASĘ", type="primary", use_container_width=True):
        if not st.session_state['start_addr'] or not st.session_state['meta_addr']:
            st.error("⚠️ Wybierz Start i Metę!")
        else:
            with st.spinner("Przetwarzanie..."):
                gl = Nominatim(user_agent="route_opt_v33")
                ls, lm = gl.geocode(st.session_state['start_addr'], timeout=10), gl.geocode(st.session_state['meta_addr'], timeout=10)
                if ls and lm:
                    route = [{"display_name": f"START: {st.session_state['start_name']}", "lat": ls.latitude, "lng": ls.longitude}]
                    unvisited = df.to_dict('records')
                    curr = {"lat": ls.latitude, "lng": ls.longitude}
                    while unvisited:
                        nxt = min(unvisited, key=lambda x: math.sqrt((curr['lat']-x['lat'])**2 + (curr['lng']-x['lng'])**2))
                        route.append(nxt); curr = nxt; unvisited.remove(nxt)
                    route.append({"display_name": f"META: {st.session_state['meta_name']}", "lat": lm.latitude, "lng": lm.longitude})
                    st.session_state['optimized'] = pd.DataFrame(route)
                    st.rerun()
                else: st.error("Błąd lokalizacji baz.")

    res_df = st.session_state.get('optimized', df)
    cl, cm = st.columns([1, 2.5])
    with cl:
        st.write("📋 **Lista:**")
        st.dataframe(res_df[['display_name']], use_container_width=True, height=600)
    with cm:
        m = folium.Map(location=[res_df['lat'].mean(), res_df['lng'].mean()], zoom_start=11)
        pts = []
        for i, row in res_df.iterrows():
            l, ln = float(row['lat']), float(row['lng'])
            color = 'blue'
            if 'optimized' in st.session_state:
                color = 'green' if i == 0 else ('red' if i == len(res_df)-1 else 'blue')
            folium.Marker([l, ln], tooltip=str(row['display_name']), icon=folium.Icon(color=color)).add_to(m)
            pts.append([l, ln])
        if 'optimized' in st.session_state and len(pts) > 1:
            folium.PolyLine(pts, color="blue", weight=4).add_to(m)
            m.fit_bounds(pts)
        st_folium(m, width="100%", height=600, key=f"map_v{len(res_df)}_{st.session_state['start_name']}")
else:
    st.info("👈 Wgraj KML i wybierz bazy, aby rozpocząć.")
