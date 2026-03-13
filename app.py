# --- WYŚWIETLANIE MAPY ---
        st.divider()
        col1, col2 = st.columns([1, 2])
        
        # Przygotuj dane do wyświetlenia (zoptymalizowane lub surowe)
        current_df = st.session_state.get('optimized', df)
        
        with col1:
            st.subheader("📋 Kolejność na trasie")
            st.dataframe(current_df[['display_name']], use_container_width=True, height=500)
            
            if 'optimized' in st.session_state:
                st.success("Trasa jest zoptymalizowana!")
                if st.button("Resetuj trasę"):
                    del st.session_state['optimized']
                    st.rerun()

        with col2:
            st.subheader("🗺️ Podgląd mapy")
            
            # 1. Inicjalizacja mapy - ZAWSZE tworzymy obiekt 'm'
            center_lat = current_df['lat'].mean()
            center_lng = current_df['lng'].mean()
            m = folium.Map(location=[center_lat, center_lng], zoom_start=12)
            
            points = []
            # 2. Dodawanie punktów do mapy 'm'
            for i, row in current_df.iterrows():
                # Kolory: Zielony dla Startu, Czerwony dla ostatniego, Niebieski dla reszty
                if i == 0:
                    icon_color = 'green'
                    label = "START"
                elif 'optimized' in st.session_state and i == len(current_df) - 1:
                    icon_color = 'red'
                    label = "META"
                else:
                    icon_color = 'blue'
                    label = f"Punkt {i+1}"
                
                folium.Marker(
                    [row['lat'], row['lng']],
                    popup=f"{label}: {row['display_name']}",
                    tooltip=row['display_name'],
                    icon=folium.Icon(color=icon_color, icon='info-sign')
                ).addTo(m)
                
                points.append([row['lat'], row['lng']])
            
            # 3. Rysowanie linii trasy
            if 'optimized' in st.session_state and len(points) > 1:
                folium.PolyLine(points, color="blue", weight=4, opacity=0.7).addTo(m)
            
            # 4. Wyświetlenie gotowej mapy
            st_folium(m, width="100%", height=600, key="main_map")

else:
    st.info("👈 Wgraj swój plik .txt lub .kml w panelu bocznym, aby zacząć.")
