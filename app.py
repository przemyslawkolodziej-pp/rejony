import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
import re, math, json, requests, os
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# --- 1. KONFIGURACJA ---
SHEET_ID = "1mTMjUKoHNw-okxpYSAeLsVD7vdxYR1P-ZjelWt9IHAE" 

st.set_page_config(page_title="Optymalizator Tras", layout="wide")

# --- 2. FUNKCJE GOOGLE (Z DODATKOWYM LOGOWANIEM) ---
def get_gspread_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_dict = dict(st.secrets["gcp_service_account"])
    if "\\n" in creds_dict["private_key"]:
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds)

def sync_save():
    # To musi się pojawić ZAWSZE po kliknięciu
    st.toast("Inicjacja zapisu...", icon="⚙️")
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
        
        st.success("✅ Zapisano w Google Sheets!")
        st.toast("Sukces!", icon="🎉")
    except Exception as e:
        st.error(f"❌ BŁĄD: {e}")

# --- 3. INICJALIZACJA SESJI ---
for key in ['authenticated', 'saved_locations', 'data']:
    if key not in st.session_state:
        if key == 'authenticated': st.session_state[key] = False
        elif key == 'data': st.session_state[key] = pd.DataFrame()
        elif key == 'saved_locations': st.session_state[key] = {}

# Logowanie (uproszczone dla testu)
if not st.session_state['authenticated']:
    p = st.text_input("Hasło:", type="password")
    if st.button("Zaloguj"):
        if p == st.secrets["password"]:
            st.session_state['authenticated'] = True
            st.rerun()
    st.stop()

# --- 4. SIDEBAR - TESTOWANIE ---
with st.sidebar:
    st.header("🛠 DEBUG PANEL")
    
    # PRZYCISK FORCE - Jeśli to nie zadziała, to znaczy że Secrets są źle wczytane
    if st.button("🔥 WYMUŚ TEST POŁĄCZENIA", type="primary"):
        st.session_state['saved_locations']["TEST_DEBUG"] = "Warszawa, Polska"
        sync_save()

    st.markdown("---")
    
    st.subheader("🏠 Dodaj Bazę (BEZ FORMULARZA)")
    n = st.text_input("Nazwa:")
    a = st.text_input("Adres:")
    if st.button("Dodaj i synchronizuj"):
        if n and a:
            st.session_state['saved_locations'][n] = a
            sync_save()
            st.rerun()

    if st.session_state['saved_locations']:
        st.write("Aktualne bazy:", st.session_state['saved_locations'])
        if st.button("Wyczyść lokalnie"):
            st.session_state['saved_locations'] = {}
            st.rerun()

# --- 5. PANEL GŁÓWNY ---
st.title("Mapa i Dane")
st.write("Jeśli kliknąłeś przycisk po lewej, sprawdź czy poniżej pojawił się komunikat.")

if not st.session_state['saved_locations']:
    st.info("Brak danych. Użyj panelu bocznego.")
else:
    st.table(pd.DataFrame(st.session_state['saved_locations'].items(), columns=["Nazwa", "Adres"]))
