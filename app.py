import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
import re
import time
import math

# --- KONFIGURACJA STRONY ---
st.set_page_config(page_title="Optymalizator Kurierski", layout="wide")

st.title("🚚 Optymalizator Trasy: Szczawin Kościelny i okolice")
st.markdown("Aplikacja wyciąga adresy z pliku KML, znajduje ich współrzędne i układa najkrótszą trasę.")

# --- FUNKCJE POMOCNICZE ---

def parse_addresses_from_kml(file_content):
    """Wyciąga dane adresowe z tagów ExtendedData w pliku KML."""
    # Szukamy wartości dla konkretnych pól adresowych
    pnas = re.findall(r'<Data name="PNA_DORECZ">\s*<value>(.*?)</value>', file_content)
    miejsca = re.findall(r'<Data name="MIEJSC_DORECZ">\s*<value>(.*?)</value>', file_content)
    ulice = re.findall(r'<Data name="ULICA_DORECZ">\s*<value>(.*?)</value>', file_content)
    numery = re.findall(r'<Data name="NR_DOM_DORECZ">\s*<value>(.*?)</value>', file_content)
    
    data = []
    for p, m, u, n in zip(pnas, miejsca, ulice, numery):
        # Budujemy pełny adres do geokodowania
        full_addr = f"{u} {n}, {p} {m}, Polska"
        display_name = f"{m}, ul. {u} {n}"
        data.append({"address": full_addr, "display_name": display_name})
    
    return pd.DataFrame(data)

def geocode_points(df):
    """Zamienia adresy tekstowe na współrzędne geograficzne."""
    geolocator = Nominatim(user_agent="my_route_optimizer_app_v2")
    lats, lngs = [], []
    
    progress_text = "Trwa geokodowanie adresów... Proszę czekać."
    my_bar = st.progress(0, text=progress_text)
    
    for i, row in df.iterrows():
        try:
            # Opóźnienie 1s, aby nie zablokowali nam dostępu (wymóg darmowego serwera)
            time.sleep(1.1)
            location = geolocator.geocode(row['address'])
            if location:
                lats.append(location.latitude)
                lngs.append(location.longitude)
            else:
                lats.append(None)
                lngs.append(None)
        except:
            lats.append(None)
            lngs.append(None)
        
        my_bar.progress((i + 1) / len(df), text=f"Znaleziono {i+1} z {len(df)} adresów")
    
    df['lat'] = lats
    df['lng'] = lngs
    return df.dropna(subset=['lat', 'lng']).reset_index(drop=True)

def calculate_distance(p1, p2):
    """Prosta odległość euklidesowa (wystarczy na małe obszary)."""
    return math.sqrt((p1['lat'] - p2['lat'])**2 + (p1['lng'] - p2['lng'])**2)

def optimize_route(df, start_index):
    """Algorytm Najbliższego Sąsiada (Nearest Neighbor)."""
    unvisited = df.to_dict('records')
    route = []
    
    # Wybieramy punkt startowy
    current = unvisited.pop(start_index)
    route.append(current)
    
    while unvisited:
        # Znajdź najbliższy punkt z pozostałych
        next_node = min(unvisited, key=lambda x: calculate_distance(current, x))
        route.append(next_node)
        unvisited.remove(next_node)
        current = next_node
        
    return pd.
