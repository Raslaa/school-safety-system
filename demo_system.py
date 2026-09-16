import streamlit as st

st.set_page_config(
    page_title="School Safety Profile",
    page_icon="🛡️"
)

# -----------------------------
# CHILD INFORMATION
# -----------------------------

name = "Ahmed Mohamed"
photo = "ahmed.jpg"
bio = "Friendly and active student. Loves football and reading."
allergies = "Peanuts"
parent_1 = "+252 63 1234567"
parent_2 = "+252 63 7654321"


# -----------------------------
# PAGE
# -----------------------------

st.title("🛡️ School Safety Profile")

st.image(photo, width=200)

st.header(name)

st.write(bio)

st.subheader("⚠️ Medical Information")

if allergies:
    st.warning(f"Allergies: {allergies}")
else:
    st.success("No known allergies")


st.subheader("📞 Parent / Guardian Contacts")

st.write(f"Parent 1: {parent_1}")
st.write(f"Parent 2: {parent_2}")


st.divider()

st.caption("School Safety NFC Demo")


# -----------------------------
# DIRECT CALL BUTTONS (FORCED DIALING)
# -----------------------------
st.subheader("📞 Parent / Guardian Contacts")

button_style = """
display: block; 
width: 100%; 
max-width: 300px;
text-align: center; 
padding: 14px 0px; 
font-size: 16px; 
font-weight: bold; 
border-radius: 8px; 
text-decoration: none; 
margin-bottom: 12px;
box-shadow: 0px 4px 6px rgba(0,0,0,0.1);
"""

# target="_top" forces the phone browser to exit the app frame and launch the phone carrier dialer
father_html = f'<a href="tel:{parent_1}" target="_top" style="{button_style} background-color: #2ecc71; color: white;">📞 CALL PARENT 1</a>'
mother_html = f'<a href="tel:{parent_2}" target="_top" style="{button_style} background-color: #34495e; color: white;">📞 CALL PARENT 2</a>'

st.markdown(father_html, unsafe_html=True)
st.markdown(mother_html, unsafe_html=True)

