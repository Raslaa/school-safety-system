import os
from urllib.parse import urlencode
import pandas as pd
import streamlit as st
from supabase import create_client, Client

# Initialize Database securely from secrets.toml
def init_supabase() -> Client:
    try:
        settings = st.secrets.get("supabase", {})
    except Exception:
        settings = {}
    url = settings.get("url") or os.getenv("SUPABASE_URL")
    key = settings.get("key") or os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("Set Supabase url and key in Streamlit secrets or environment variables.")
    return create_client(url, key)


def build_app_url(parameter: str, value: str) -> str:
    """Build a link to this Streamlit app with one query parameter."""
    try:
        base_url = st.secrets.get("public_app_url")
    except Exception:
        base_url = None
    base_url = base_url or os.getenv("PUBLIC_APP_URL")
    if not base_url:
        try:
            base_url = st.context.url
        except Exception:
            base_url = None
    if not base_url:
        raise ValueError("Set public_app_url or PUBLIC_APP_URL to the deployed Streamlit URL.")
    return f"{str(base_url).split('?', 1)[0].rstrip('/')}?{urlencode({parameter: value})}"

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
            
        tag_rows = tag_res.data or []
        if not tag_rows:
            st.error("🚨 Access Refused: Invalid token code.")
            st.stop()
        tag_data = tag_rows[0]
        if (tag_data.get("status") or "").lower() not in {"active", "enabled"}:
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

    child = child_res.data[0]
    guardians = guardian_res.data or []

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
            phone = g.get("phone")
            if phone:
                clean_phone = "".join(ch for ch in str(phone) if ch.isdigit() or ch == "+")
                st.link_button(f"📞 Call {g.get('full_name') or 'Guardian'}", f"tel:{clean_phone}")
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

    with admin_tabs[0]:
        st.subheader("Student Database Manifest")
        try:
            students_res = supabase.table("students").select("*").execute().data
            if students_res:
                st.dataframe(pd.DataFrame(students_res)[["student_id", "full_name", "class_name", "allergies"]], use_container_width=True)
            else:
                st.info("No active student items found.")
        except Exception as e:
            st.error(f"Database read failure: {str(e)}")

    with admin_tabs[1]:
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
                        new_student_uuid = inserted_student.data[0]["id"]
                        
                        guardian_payload = {
                            "student_id": new_student_uuid, "full_name": g_name,
                            "relationship": g_rel, "phone": g_phone, "is_primary": True
                        }
                        supabase.table("guardians").insert(guardian_payload).execute()
                        st.success(f"Success! Registered **{s_name}** along with primary guardian lines.")
                    except Exception as e:
                        st.error(f"Failed to submit: {str(e)}")

    with admin_tabs[2]:
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
                        hex_token = tag_res.data[0]["public_token"]
                        final_nfc_link = build_app_url("tag_token", hex_token)
                        st.success("🔒 Secure Security Hex Key Generated Successfully!")
                        st.code(final_nfc_link)
                    except Exception as e:
                        existing_tag = supabase.table("nfc_tags").select("public_token").eq("student_id", selected_uuid).execute()
                        if existing_tag.data:
                            hex_token = existing_tag.data[0]["public_token"]
                            fixed_link = build_app_url("tag_token", hex_token)
                            st.warning("🔄 Token already initialized. Existing link:")
                            st.code(fixed_link)
            else:
                st.info("No students registered yet.")
        except Exception as e:
            st.error(f"Failed to query records: {str(e)}")

    with admin_tabs[3]:
        st.subheader("📍 Live Location Tracking Logs")
        try:
            logs_res = supabase.table("scan_logs").select("latitude, longitude").execute().data
            if logs_res:
                df_map = pd.DataFrame(logs_res).dropna().rename(
                    columns={"latitude": "lat", "longitude": "lon"}
                )
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
