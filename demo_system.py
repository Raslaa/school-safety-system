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
