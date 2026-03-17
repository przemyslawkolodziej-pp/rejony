import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
import re
import time
import math
import json
import requests
import hashlib # Dodane dla generowania kolorów

# --- 1. SYSTEM LOGOWANIA ---
def logout():
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()

if 'authenticated' not in st.session_state:
    st.session_state['authenticated'] = False

if not st.session_state['authenticated']:
    st.set_page_config(page_title="Logowanie", page_icon="🗺️")
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

# --- 2. FUNKCJE ROUTINGU (OSRM) ---
def get_road_distance(lat1, lon1, lat2, lon2):
    try:
        url = f"http://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=false"
        r = requests.get(url, timeout=5)
        res = r.json()
        if res['code'] == 'Ok':
            return res['routes'][0]['distance'], res['routes'][0]['duration']
    except: pass
    return math.sqrt((lat1-lat2)**2 + (lon1-lon2)**2) * 111000, 0

def get_full_route_info(coords_list):
    coords_str = ";".join([f"{c[1]},{c[0]}" for c in coords_list])
    url = f"http://router.project-osrm.org/route/v1/driving/{coords_str}?overview=full&geometries=geojson"
    try:
        r = requests.get(url, timeout=10)
        res = r.json()
        if res['code'] == 'Ok':
            route = res['routes'][0]
            return {'geometry': route['geometry']['coordinates'], 'distance': route['distance'], 'duration': route['duration']}
    except: return None

# Zmieniona funkcja, przyjmuje nazwę pliku jako argument
def parse_kml_robust(file_content, file_name="unknown"):
    placemarks = re.findall(r'<Placemark>(.*?)</Placemark>', file_content, re.DOTALL)
    pts = []
    for pm in placemarks:
        name_match = re.search(r'<(?:name|display_name)>(.*?)</(?:name|display_name)>', pm)
        name = name_match.group(1) if name_match else "Punkt"
        coords = re.search(r'<coordinates>\s*([\d\.\-]+),\s*([\d\.\-]+)', pm)
        if coords:
            pts.append({"display_name": str(name), "lat": float(coords.group(2)), "lng": float(coords.group(1)), "source_file": file_name})
    return pd.DataFrame(pts)

# Nowa funkcja do generowania kolorów
def get_color_for_file(file_name):
    # Dostępne kolory Folium
    folium_colors = ['blue', 'green', 'purple', 'orange', 'darkred', 'lightred', 'darkblue', 'darkgreen', 'cadetblue', 'pink', 'lightblue', 'lightgreen']
    # Używamy hasha nazwy pliku, żeby deterministycznie przypisać kolor
    hash_object = hashlib.md5(file_name.encode())
    hex_dig = hash_object.hexdigest()
    # Przekształcamy hash na indeks koloru
    color_index = int(hex_dig, 16) % len(folium_colors)
    return folium_colors[color_index]


# --- 3. KONFIGURACJA UI ---
st.set_page_config(page_title="Optymalizator Drogowy", page_icon="🗺️", layout="wide")

st.markdown("""
    <style>
    .selection-info { font-size: 13px; color: #1e1e1e; background-color: #e8f0fe; padding: 12px; border-radius: 8px; border-left: 6px solid #4285f4; margin-bottom: 15px; }
    .status-text { font-size: 11px; font-weight: bold; text-align: center; margin-top: 5px; color: #2e7d32; }
    .stMetric { background-color: #f8f9fa; padding: 10px; border-radius: 10px; border: 1px solid #eee; }
    </style>
    """, unsafe_allow_html=True)

for key in ['data', 'saved_locations', 'projects']:
    if key not in st.session_state: 
        # Zmienione, aby DataFrame 'data' zawsze zawierała 'source_file'
        st.session_state[key] = pd.DataFrame(columns=["display_name", "lat", "lng", "source_file"]) if key == 'data' else {}
if 'start_name' not in st.session_state: 
    st.session_state.update({'start_name': "Nie wybrano", 'meta_name': "Nie wybrano", 'start_addr': "", 'meta_addr': ""})

# --- SIDEBAR ---
with st.sidebar:
    st.header("🗺️ Menu Główne")
    
    with st.expander("🚀 Wczytaj Dane (KML)", expanded=True):
        st.markdown(f'<div class="selection-info">📍 S: {st.session_state["start_name"]}<br>🏁 M: {st.session_state["meta_name"]}</div>', unsafe_allow_html=True)
        
        up_kmls = st.file_uploader("Wgraj pliki KML (można kilka)", type=['kml'], accept_multiple_files=True)
        
        if up_kmls and st.button("Wczytaj wszystkie pliki"):
            all_pts = []
            for uploaded_file in up_kmls:
                # Przekazujemy nazwę pliku do funkcji parse_kml_robust
                df_single = parse_kml_robust(uploaded_file.read().decode('utf-8'), uploaded_file.name)
                all_pts.append(df_single)
            
            if all_pts:
                st.session_state['data'] = pd.concat(all_pts, ignore_index=True)
                st.success(f"Wczytano łącznie {len(st.session_state['data'])} punktów.")
                if 'optimized' in st.session_state: del st.session_state['optimized']
                st.rerun()

        if st.button("🗑️ Wyczyść aktualne dane"):
            st.session_state['data'] = pd.DataFrame(columns=["display_name", "lat", "lng", "source_file"]) # Resetujemy z kolumną source_file
            st.session_state.update({'start_name': "Nie wybrano", 'meta_name': "Nie wybrano", 'start_addr': "", 'meta_addr': ""})
            if 'optimized' in st.session_state: del st.session_state['optimized']
            st.rerun()

    with st.expander("📍 Twoje Bazy"):
        with st.form("add_base_form", clear_on_submit=True):
            n_n, n_a = st.text_input("Nazwa bazy:"), st.text_input("Adres bazy:")
            if st.form_submit_button("Dodaj bazę") and n_n and n_a:
                st.session_state['saved_locations'][n_n] = n_a; st.rerun()
        for n, a in st.session_state['saved_locations'].items():
            is_s, is_m = (st.session_state['start_name'] == n), (st.session_state['meta_name'] == n)
            st.write(f"**{n}**")
            c1, c2, c3 = st.columns([1, 1, 0.4])
            with c1:
                if is_s: st.markdown('<p class="status-text">🟢 START</p>', unsafe_allow_html=True)
                else:
                    if st.button("S", key=f"s_{n}"): st.session_state.update({'start_addr': a, 'start_name': n}); st.rerun()
            with c2:
                if is_m: st.markdown('<p class="status-text">🔴 META</p>', unsafe_allow_html=True)
                else:
                    if st.button("M", key=f"m_{n}"): st.session_state.update({'meta_addr': a, 'meta_name': n}); st.rerun()
            with c3:
                if st.button("🗑️", key=f"d_{n}"): del st.session_state['saved_locations'][n]; st.rerun()

    with st.expander("📁 Projekty"):
        p_name = st.text_input("Nazwa projektu do zapisu:")
        if st.button("Zapisz bieżący stan"):
            if p_name:
                st.session_state['projects'][p_name] = {
                    'data': st.session_state['data'].copy(),
                    'start_addr': st.session_state['start_addr'], 'meta_addr': st.session_state['meta_addr'],
                    'start_name': st.session_state['start_name'], 'meta_name': st.session_state['meta_name']
                }
                st.toast(f"Projekt {p_name} zapisany!")
        
        if st.session_state['projects']:
            sel_p = st.selectbox("Wczytaj projekt:", list(st.session_state['projects'].keys()))
            cp1, cp2 = st.columns(2)
            if cp1.button("Wczytaj"):
                p = st.session_state['projects'][sel_p]
                st.session_state.update({'data': p['data'].copy(), 'start_addr': p['start_addr'], 'meta_addr': p['meta_addr'], 'start_name': p['start_name'], 'meta_name': p['meta_name']})
                if 'optimized' in st.session_state: del st.session_state['optimized']
                st.rerun()
            if cp2.button("Usuń"):
                del st.session_state['projects'][sel_p]; st.rerun()

    with st.expander("💾 Kopia zapasowa"):
        export_data = {
            "saved_locations": st.session_state['saved_locations'],
            "projects": {k: {**v, "data": v["data"].to_dict()} for k, v in st.session_state['projects'].items()}
        }
        st.download_button("📥 Pobierz Backup (JSON)", data=json.dumps(export_data), file_name="backup_tras.json")
        up_json = st.file_uploader("📤 Wczytaj Backup", type="json")
        if up_json:
            try:
                b = json.load(up_json)
                st.session_state['saved_locations'] = b["saved_locations"]
                for k, v in b["projects"].items():
                    # Upewniamy się, że wczytane dane mają kolumnę source_file, jeśli jej brakuje
                    df_proj = pd.DataFrame(v["data"])
                    if "source_file" not in df_proj.columns:
                        df_proj["source_file"] = "Wczytany projekt" # Domyślna nazwa źródła
                    st.session_state['projects'][k] = {**v, "data": df_proj}
                st.success("Wczytano backup!")
            except: st.error("Błąd pliku JSON.")

    st.markdown('<br>', unsafe_allow_html=True)
    if st.button("🔓 WYLOGUJ", use_container_width=True): logout()

# --- PANEL GŁÓWNY ---
st.title("🗺️ Optymalizator Wieloplikowy")

df = st.session_state['data']

# Dodajemy kolumnę 'source_file' do początkowego DataFrame, jeśli jej brakuje (dla starszych danych)
if not df.empty and "source_file" not in df.columns:
    df["source_file"] = "Wczytane punkty" # Domyślna nazwa dla danych bez źródła
    st.session_state['data'] = df


if not df.empty:
    if st.button("🚀 OBLICZ TRASĘ (OSRM)", type="primary", use_container_width=True):
        if not st.session_state['start_addr'] or not st.session_state['meta_addr']:
            st.error("⚠️ Wybierz Start i Metę w panelu bocznym!")
        else:
            with st.spinner("Szukanie najkrótszej drogi..."):
                gl = Nominatim(user_agent="v44")
                ls, lm = gl.geocode(st.session_state['start_addr']), gl.geocode(st.session_state['meta_addr'])
                if ls and lm:
                    # START i META nie mają pliku źródłowego, więc mogą mieć inny kolor lub domyślny
                    curr = {"lat": ls.latitude, "lng": ls.longitude, "display_name": f"START: {st.session_state['start_name']}", "source_file": "START"}
                    route = [curr]
                    unvisited = df.to_dict('records')
                    while unvisited:
                        nxt = min(unvisited, key=lambda x: get_road_distance(curr['lat'], curr['lng'], x['lat'], x['lng'])[0])
                        route.append(nxt); curr = nxt; unvisited.remove(nxt)
                    route.append({"display_name": f"META: {st.session_state['meta_name']}", "lat": lm.latitude, "lng": lm.longitude, "source_file": "META"})
                    st.session_state['optimized'] = pd.DataFrame(route)
                    
                    f_i = get_full_route_info([[r['lat'], r['lng']] for r in route])
                    if f_i: st.session_state.update({'geometry': f_i['geometry'], 'dist': f_i['distance'], 'time': f_i['duration']})
                    st.rerun()

    if 'dist' in st.session_state:
        m1, m2, m3 = st.columns(3)
        m1.metric("Łączny dystans", f"{st.session_state['dist']/1000:.2f} km")
        m2.metric("Czas jazdy", f"{int(st.session_state['time']//3600)}h {int((st.session_state['time']%3600)//60)}min")
        m3.metric("Liczba punktów", len(st.session_state.get('optimized', [])))

    res_df = st.session_state.get('optimized', df)
    
    # MAPA
    m = folium.Map(location=[res_df['lat'].mean(), res_df['lng'].mean()], zoom_start=11)
    
    # Dodanie legendy
    if 'source_file' in res_df.columns:
        unique_files = res_df['source_file'].unique()
        legend_html = '<div style="position: fixed; bottom: 50px; left: 50px; width: 150px; background-color: white; border:2px solid grey; z-index:9999; font-size:14px; padding: 10px;"><b>Legenda</b><br>'
        for file in unique_files:
            color = get_color_for_file(file)
            # Specjalne kolory dla START i META
            if file == "START":
                color = "green"
            elif file == "META":
                color = "red"
            legend_html += f'<i style="background:{color}; border-radius: 50%; display: inline-block; width: 10px; height: 10px;"></i> {file}<br>'
        legend_html += '</div>'
        m.get_root().html.add_child(folium.Element(legend_html))


    for i, r in res_df.iterrows():
        # Kolor pinezki Folium
        icon_color = get_color_for_file(r.get('source_file', 'unknown')) # Używamy nazwy pliku do wyboru koloru
        
        # Specjalne kolory dla START i META
        if r.get('source_file') == "START":
            icon_color = "green"
        elif r.get('source_file') == "META":
            icon_color = "red"

        folium.Marker([r['lat'], r['lng']], 
                      tooltip=f"{str(r['display_name'])} (Źródło: {r.get('source_file', 'N/A')})", 
                      icon=folium.Icon(color=icon_color)).add_to(m)
    
    if 'geometry' in st.session_state:
        flip = [[c[1], c[0]] for c in st.session_state['geometry']]
        folium.PolyLine(flip, color="#4285f4", weight=6, opacity=0.8).add_to(m)
        m.fit_bounds(flip)
    
    st_folium(m, width="100%", height=500, key=f"map_{len(res_df)}")

    # TABELA (Szeroka, nagłówek "Etykieta" i nowa kolumna "Źródło pliku")
    st.markdown("### 📋 Kolejność przystanków")
    
    # Kolumny do wyświetlenia w tabeli
    cols_to_display = ["display_name", "source_file"] if "source_file" in res_df.columns else ["display_name"]

    st.dataframe(
        res_df[cols_to_display], 
        use_container_width=True,
        column_config={
            "display_name": "Etykieta",
            "source_file": "Źródło pliku" # Nowy nagłówek dla kolumny źródłowej
        }
    )
else:
    st.info("👈 Wgraj jeden lub więcej plików KML w panelu bocznym.")
