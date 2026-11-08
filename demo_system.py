import os
import pandas as pd
import streamlit as st
from supabase import create_client, Client

# Initialize Database securely from secrets.toml
def init_supabase() -> Client:
    return create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])

supabase = init_supabase()

# Fetch parameters directly from browser link string
tag_token = st.query_params.get("tag_token", None)
browser_lat = st.query_params.get("lat", None)
browser_lon = st.query_params.get("lon", None)

# =============================================================
# 🛰️ PRODUCTION GEOLOCATION INTERCEPTOR
# =============================================================
if tag_token:
    # A tag was scanned! Completely lock out the dashboard menus and display fullscreen profile
    try:
        tag_res = supabase.table("nfc_tags").select("student_id, status").eq("public_token", tag_token).execute()
        if not tag_res.data:
            st.error("🚨 Access Refused: Invalid token code.")
            st.stop()
            
        tag_data = tag_res.data
        if tag_data["status"] != "active":
            st.error("🚨 Access Refused: This safety tag has been frozen or reported lost.")
            st.stop()
            
        student_uuid = tag_data["student_id"]
        
        # Log the location coordinates seamlessly if passed via browser query string
        if browser_lat and browser_lon:
            supabase.table("scan_logs").insert({
                "student_id": student_uuid,
                "latitude": float(browser_lat),
                "longitude": float(browser_lon)
            }).execute()
            
        child_res = supabase.table("students").select("*").eq("id", student_uuid).execute()
        guardian_res = supabase.table("guardians").select("*").eq("student_id", student_uuid).execute()
    except Exception as e:
        st.error("Connection error while validating security token infrastructure.")
        st.stop()

    if not child_res.data:
        st.error("🚨 System Profile Error: Enrolled child credentials not found.")
        st.stop()

    child = child_res.data
    guardians = guardian_res.data

    # Request browser GPS coordinates via lightweight automated HTML injection script
    if not browser_lat or not browser_lon:
        st.markdown(
            f"""
            <script>
            navigator.geolocation.getCurrentPosition(function(position) {{
                const lat = position.coords.latitude;
                const lon = position.coords.longitude;
                const currentUrl = new URL(window.location.href);
                currentUrl.searchParams.set('lat', lat);
                currentUrl.searchParams.set('lon', lon);
                window.location.href = currentUrl.toString();
            }});
            </script>
            """,
            unsafe_allow_html=True
        )

    st.title("🛡️ Student Safety Profile")
    if child.get("photo_url") and child["photo_url"].strip() != "":
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
    st.stop()

# -------------------------------------------------------------
# BACKUP DEMO FALLBACK (IF NO TOKEN IS PRESENT)
# -------------------------------------------------------------
st.sidebar.title("🛡️ Proximind Safety Hub")
app_mode = st.sidebar.radio("Navigation View Portal:", ["🚀 Admin Dashboard", "👨‍👩‍👦 Parent Portal Gateway"])

# 🚀 VIEW A: ADMIN DASHBOARD PANEL
if app_mode == "🚀 Admin Dashboard":
    st.title("🔑 Administrative Control Panel (DEMO)")
    admin_tabs = st.tabs(["📋 Student Directory", "➕ Register New Record", "🔗 Assign NFC Tags", "📍 Live Scan Map"])

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
                    st.error("Mandatory fields cannot be blank.")
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

    with admin_tabs:
        st.subheader("Configure Physical NFC Tokens")
        try:
            students_list = supabase.table("students").select("id, full_name, student_id").execute().data
            if students_list:
                student_options = {f"{s['full_name']} ({s['student_id']})": s["id"] for s in students_list}
                selected_child_name = st.selectbox("Select Student to Bind to Tag:", list(student_options.keys()))
                selected_uuid = student_options[selected_child_name]
                
                if st.button("GENERATE NEW SECURE NFC TOKEN"):
                    try:
                        tag_res = supabase.table("nfc_tags").insert({"student_id": selected_uuid}).execute()
                        hex_token = tag_res.data["public_token"]
                        final_nfc_link = f"https://streamlit.app{hex_token}"
                        st.success("🔒 Secure Security Hex Key Generated Successfully!")
                        st.code(final_nfc_link)
                    except Exception as e:
                        existing_tag = supabase.table("nfc_tags").select("public_token").eq("student_id", selected_uuid).execute()
                        if existing_tag.data:
                            hex_token = existing_tag.data["public_token"]
                            fixed_link = f"https://streamlit.app{hex_token}"
                            st.warning("🔄 Token already initialized. Existing link:")
                            st.code(fixed_link)
            else:
                st.info("No students registered yet.")
        except Exception as e:
            st.error(f"Failed to query records: {str(e)}")

    with admin_tabs:
        st.subheader("📍 Live Location Tracking Logs")
        try:
            logs_res = supabase.table("scan_logs").select("latitude, longitude").execute().data
            if logs_res:
                df_map = pd.DataFrame(logs_res).dropna()
                if not df_map.empty:
                    st.map(df_map)
                else:
                    st.info("Awaiting live scanning coordinates to stream onto map layout.")
            else:
                hargeisa_demo = pd.DataFrame({"lat": [9.5623], "lon": [44.0652]})
                st.caption("Showing demo coordinate simulation area for Hargeisa, Somalia:")
                st.map(hargeisa_demo)
        except Exception as e:
    st.error(f"Failed to load location logs: {e}")
