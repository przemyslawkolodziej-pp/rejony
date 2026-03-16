import streamlit as st
import streamlit_authenticator as stauth

st.title("Generator Hasła")

haslo = st.text_input("Wpisz swoje wymarzone hasło:", type="password")

if haslo:
    hash_hasla = stauth.Hasher([haslo]).generate()[0]
    st.write("### Twoje zahashowane hasło:")
    st.code(hash_hasla)
    st.info("Skopiuj powyższy kod i wklej go do głównego pliku aplikacji.")
