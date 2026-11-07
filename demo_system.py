import streamlit as st
import pandas as pd
from supabase import create_client, Client

# Initialize Database securely from secrets.toml
@st.cache_resource
def init_supabase() -> Client:
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)

supabase = init_supabase()

st.sidebar.title("🛡️ Proximind Safety Hub")
app_mode = st.sidebar.radio("Navigation Menu:", ["NFC Tag Scanner Gateway", "Admin Portal Management"])

# =============================================================
# STAGE 4: CONNECT DYNAMIC NFC FRONTEND (PUBLIC GATEWAY)
# =============================================================
if app_mode == "NFC Tag Scanner Gateway":
    query_params = st.query_params
    tag_token = query_params.get("tag_token", None)

    if not tag_token:
        st.info("👋 Proximind System online. Awaiting data from physical NFC tag tap event.")
        st.stop()

    # Step A: Find the active student bound to this security public token
    try:
        tag_res = supabase.table("nfc_tags").select("student_id, status").eq("public_token", tag_token).execute()
        if not tag_res.data or tag_res.data[0]["status"] != "active":
            st.error("🚨 Access Refused: This NFC tag is inactive or has been reported lost.")
            st.stop()
        
        student_uuid = tag_res.data[0]["student_id"]
    except Exception as e:
        st.error("Connection error while validating security token infrastructure.")
        st.stop()

    # Step B: Pull student details and guardian rows using relational data
    child_res = supabase.table("students").select("*").eq("id", student_uuid).execute()
    guardian_res = supabase.table("guardians").select("*").eq("student_id", student_uuid).execute()

    if not child_res.data:
        st.error("🚨 System Profile Error: Enrolled child credentials not found.")
        st.stop()

    child = child_res.data[0]
    guardians = guardian_res.data

    # Render Public Layout View
    st.title("🛡️ Student Safety Profile")
    if child.get("photo_url"):
        st.image(child["photo_url"], width=200)
        
    st.header(child["full_name"])
    st.caption(f"Class/Level: {child.get('class_name', 'Not Specified')}")
    st.write(child.get("bio", ""))

    if child.get("allergies") and child["allergies"].lower() != "none":
        st.warning(f"⚠️ Known Allergies: {child['allergies']}")
    if child.get("safety_notes"):
        st.info(f"📌 Critical Safety Notes: {child['safety_notes']}")

    # Render list of dynamic direct dial guardian contacts
    if guardians:
        st.subheader("📞 Emergency Contacts")
        for g in guardians:
            role_label = f" ({g['relationship']})" if g.get("relationship") else ""
            primary_badge = "⭐ PRIMARY GUARDIAN: " if g.get("is_primary") else ""
            st.write(f"**{primary_badge}{g['full_name']}**{role_label}")
            
            clean_phone = str(g["phone"]).replace(" ", "")
            dial_btn = f"""
            <a href="tel:{clean_phone}" target="_top" style="
                display: inline-block; width: 100%; max-width: 300px; text-align: center; 
                padding: 12px 0px; font-size: 15px; font-weight: bold; border-radius: 8px; 
                text-decoration: none; margin-bottom: 15px; background-color: #2ecc71; color: white;
                box-shadow: 0px 4px 6px rgba(0,0,0,0.1);
            ">📞 CALL {g['full_name'].upper()}</a>
            """
            st.markdown(dial_btn, unsafe_allow_html=True)
    else:
        st.error("No active primary context lines bound to target student profile index.")

# =============================================================
# STAGE 3: STUDENT MANAGEMENT & ADMINISTRATION SYSTEM
# =============================================================
elif app_mode == "Admin Portal Management":
    st.title("🔑 Administrative Control Panel")
    
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False

    if not st.session_state.logged_in:
        email = st.text_input("Admin Email Address:")
        password = st.text_input("Security Access Code:", type="password")
        
        if st.button("AUTHENTICATE SESSION", use_container_width=True):
            try:
                # Login directly using Supabase Native Auth
                auth_res = supabase.auth.sign_in_with_password({"email": email, "password": password})
                st.session_state.logged_in = True
                st.success("Session verified! Accessing secure system data modules...")
                st.rerun()
            except Exception as e:
                st.error("Authentication rejected: Ensure your user account is in the public.admin_users table.")
        st.stop()

    # User Authenticated - Display Dashboard Panel Controls
    st.sidebar.success("Proximind Secure Session")
    if st.sidebar.button("Terminate Access Session (Logout)"):
        st.session_state.logged_in = False
        st.rerun()

    admin_tabs = st.tabs(["📋 Student Directory", "➕ Register New Record", "🔗 Assign NFC Tags"])

    # 1. Directory View
    with admin_tabs[0]:
        st.subheader("Student Database Manifest")
        try:
            students_res = supabase.table("students").select("*").execute().data
            if students_res:
                df_students = pd.DataFrame(students_res)[["student_id", "full_name", "class_name", "allergies"]]
                st.dataframe(df_students, use_container_width=True)
            else:
                st.info("No active student items found.")
        except:
            st.error("Authorization Block: Ensure your authenticated profile UUID is inside the 'admin_users' table.")

    # 2. Complete Registration Intake Form
    with admin_tabs[1]:
        st.subheader("Enroll New Student Identity")
        with st.form("new_student_form", clear_on_submit=True):
            s_id = st.text_input("School Registration ID (e.g. ST-2026-09):")
            s_name = st.text_input("Legal Full Name:")
            s_class = st.text_input("Assigned Classroom / Grade:")
            s_photo = st.text_input("Photo Storage URL Endpoint:")
            s_allergies = st.text_input("Known Allergies:", value="None")
            s_notes = st.text_area("Critical Safety / Behavioral Notes (e.g. Autistic, non-verbal):")
            s_bio = st.text_area("Profile Biography / Extra Info:")
            
            st.write("---")
            st.subheader("Primary Guardian Information")
            g_name = st.text_input("Guardian Full Name:")
            g_rel = st.text_input("Relationship to Child (e.g. Father, Mother):")
            g_phone = st.text_input("Active Phone Line Number (Include Country Code):")
            
            if st.form_submit_value("COMMIT RECORD TRANSACTION TO CLOUD"):
                if not s_id or not s_name or not g_phone:
                    st.error("Mandatory form entry constraints triggered. ID, Name, and Phone cannot be blank.")
                else:
                    # 1. Write the Student Row
                    student_payload = {
                        "student_id": s_id, "full_name": s_name, "photo_url": s_photo,
                        "bio": s_bio, "class_name": s_class, "allergies": s_allergies, "safety_notes": s_notes
                    }
                    student_db_res = supabase.table("students").insert(student_payload).execute()
                    new_student_uuid = student_db_res.data[0]["id"]
                    
                    # 2. Write the Bound Guardian Row linked to the UUID
                    guardian_payload = {
                        "student_id": new_student_uuid, "full_name": g_name,
                        "relationship": g_rel, "phone": g_phone, "is_primary": True
                    }
                    supabase.table("guardians").insert(guardian_payload).execute()
                    st.success(f"Success! Registered **{s_name}** along with primary guardian lines.")

    # 3. Assign & Retrieve Token Keys for Physical NFC writing
    with admin_tabs[2]:
        st.subheader("Configure Physical NFC Tokens")
        try:
            students_list = supabase.table("students").select("id, full_name, student_id").execute().data
            if students_list:
                student_options = {f"{s['full_name']} ({s['student_id']})": s["id"] for s in students_list}
                selected_child_name = st.selectbox("Select Student to Bind to Tag:", list(student_options.keys()))
                selected_uuid = student_options[selected_child_name]
                
                if st.button("GENERATE NEW SECURE NFC TOKEN"):
                    # This insert automatically calls the gen_random_bytes(32) 'hex' default function you coded!
                    tag_write_res = supabase.table("nfc_tags").insert({"student_id": selected_uuid}).execute()
                    hex_token = tag_write_res.data[0]["public_token"]
                    
                    st.success("🔒 Secure Security Hex Key Generated Successfully!")
                    st.info("Write this exact URL configuration target below onto your physical NFC tag parameter data window:")
                    st.code(f"https://streamlit.app{hex_token}")
            else:
                st.info("No students registered yet.")
        except:
            st.error("Failed to query records. Verify authentication rules.")
