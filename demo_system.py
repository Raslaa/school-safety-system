import os
import pandas as pd
import streamlit as st
from supabase import create_client, Client

# Initialize Database securely from secrets.toml
@st.cache_resource
def init_supabase() -> Client:
    return create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])

supabase = init_supabase()

# =============================================================
# FIXED AUTOMATIC GATEKEEPER ROUTING (FORCED INITIALIZATION)
# =============================================================
# Initialize session routing state to prevent cache lockouts
if "route_checked" not in st.session_state:
    st.session_state.route_checked = False

# Fetch parameter directly from browser link string
tag_token = st.query_params.get("tag_token", None)

# FIX: If a token exists but Streamlit missed it on initial load, force an instant sync rerun
if tag_token and not st.session_state.route_checked:
    st.session_state.route_checked = True
    st.rerun()

# -------------------------------------------------------------
# DDYNAMIC FORCED DISPATCH IF TOKEN IS PRESENT
# -------------------------------------------------------------
if tag_token:
    # A tag was scanned! Completely lock out the admin menu and load profile fullscreen
    try:
        tag_res = supabase.table("nfc_tags").select("student_id, status").eq("public_token", tag_token).execute()
        if not tag_res.data or tag_res.data["status"] != "active":
            st.error("🚨 Access Refused: This NFC tag is inactive or has been reported lost.")
            st.stop()
        student_uuid = tag_res.data["student_id"]
    except Exception as e:
        st.error("Connection error while validating security token infrastructure.")
        st.stop()

    child_res = supabase.table("students").select("*").eq("id", student_uuid).execute()
    guardian_res = supabase.table("guardians").select("*").eq("student_id", student_uuid).execute()

    if not child_res.data:
        st.error("🚨 System Profile Error: Enrolled child credentials not found.")
        st.stop()

    child = child_res.data
    guardians = guardian_res.data

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

    if guardians:
        st.subheader("📞 Emergency Contacts")
        for g in guardians:
            role_label = f" ({g['relationship']})" if g.get("relationship") else ""
            primary_badge = "⭐ PRIMARY GUARDIAN: " if g.get("is_primary") else ""
            st.write(f"**{primary_badge}{g['full_name']}**{role_label}")
            clean_phone = str(g["phone"]).replace(" ", "")
            st.markdown(f'<a href="tel:{clean_phone}" target="_top" style="display:inline-block;width:100%;max-width:300px;text-align:center;padding:12px 0px;font-size:15px;font-weight:bold;border-radius:8px;text-decoration:none;margin-bottom:15px;background-color:#2ecc71;color:white;box-shadow:0px 4px 6px rgba(0,0,0,0.1);">📞 CALL {g["full_name"].upper()}</a>', unsafe_allow_html=True)
    else:
        st.error("No active primary context lines bound to target student profile index.")

# -------------------------------------------------------------
# BACKUP DEMO FALLBACK (IF NO TOKEN IS PRESENT)
# -------------------------------------------------------------
else:
    # Reset tracking variable if user explicitly clears the link parameters
    st.session_state.route_checked = False
    
    st.sidebar.title("🛡️ Proximind Safety Hub")
    app_mode = st.sidebar.radio("Navigation Menu:", ["🚀 Admin Dashboard (Demo)", "ℹ️ System Info"])

    if app_mode == "🚀 Admin Dashboard (Demo)":
        st.title("🔑 Administrative Control Panel (DEMO MODE)")
        st.success("🔓 Security authentication disabled for demonstration presentation purposes.")
        admin_tabs = st.tabs(["📋 Student Directory", "➕ Register New Record", "🔗 Assign NFC Tags"])

        # 1. Directory View
        with admin_tabs:
            st.subheader("Student Database Manifest")
            try:
                students_res = supabase.table("students").select("*").execute().data
                if students_res:
                    st.dataframe(pd.DataFrame(students_res)[["student_id", "full_name", "class_name", "allergies"]], use_container_width=True)
                else:
                    st.info("No active student items found.")
            except Exception as e:
                st.error(f"Database read failure: {str(e)}")

        # 2. Registration Intake Form
        with admin_tabs:
            st.subheader("Enroll New Student Identity")
            with st.form("new_student_form", clear_on_submit=True):
                s_id = st.text_input("School Registration ID (e.g. AUS-2026-001):")
                s_name = st.text_input("Legal Full Name:")
                s_class = st.text_input("Assigned Classroom / Grade:")
                s_photo = st.text_input("Photo Storage URL Endpoint:")
                s_allergies = st.text_input("Known Allergies:", value="None")
                s_notes = st.text_area("Critical Safety / Behavioral Notes:")
                s_bio = st.text_area("Profile Biography / Extra Info:")
                
                st.write("---")
                st.subheader("Primary Guardian Information")
                g_name = st.text_input("Guardian Full Name:")
                g_rel = st.text_input("Relationship to Child (e.g. Father, Mother):")
                g_phone = st.text_input("Active Phone Line Number (Include Country Code):")
                
                if st.form_submit_button("COMMIT RECORD TRANSACTION TO CLOUD"):
                    if not s_id or not s_name or not g_phone:
                        st.error("Mandatory form entry constraints triggered. ID, Name, and Phone cannot be blank.")
                    else:
                        try:
                            student_payload = {
                                "student_id": s_id, "full_name": s_name, "photo_url": s_photo,
                                "bio": s_bio, "class_name": s_class, "allergies": s_allergies, "safety_notes": s_notes
                            }
                            inserted_student = supabase.table("students").insert(student_payload).execute()
                            new_student_uuid = inserted_student.data["id"]
                            
                            guardian_payload = {
                                "student_id": new_student_uuid, "full_name": g_name,
                                "relationship": g_rel, "phone": g_phone, "is_primary": True
                            }
                            supabase.table("guardians").insert(guardian_payload).execute()
                            st.success(f"Success! Registered **{s_name}** along with primary guardian lines.")
                        except Exception as e:
                            st.error(f"Failed to submit: {str(e)}")

        # 3. Assign Tags
        with admin_tabs:
            st.subheader("Configure Physical NFC Tokens")
            try:
                students_list = supabase.table("students").select("id, full_name, student_id").execute().data
                if students_list:
                    student_options = {f"{s['full_name']} ({s['student_id']})": s["id"] for s in students_list}
                    selected_child_name = st.selectbox("Select Student to Bind to Tag:", list(student_options.keys()))
                    selected_uuid = student_options[selected_child_name]
                    
                    if st.button("GENERATE NEW SECURE NFC TOKEN"):
                        tag_res = supabase.table("nfc_tags").insert({"student_id": selected_uuid}).execute()
                        hex_token = tag_res.data["public_token"]
                        st.success("🔒 Secure Security Hex Key Generated Successfully!")
                        st.info("Write this exact URL configuration target below onto your physical NFC tag parameter data window:")
                        st.code(f"https://streamlit.app{hex_token}")
                else:
                    st.info("No students registered yet.")
            except Exception as e:
                st.error(f"Failed to query records: {str(e)}")

    elif app_mode == "ℹ️ System Info":
        st.title("🛡️ Proximind Safety Systems")
        st.info("NFC Tag gateway active. Access control panel via sidebar controls.")
