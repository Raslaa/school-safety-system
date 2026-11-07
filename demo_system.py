import os
from urllib.parse import urlencode

import pandas as pd
import streamlit as st
from supabase import create_client, Client

st.set_page_config(page_title="Student Safety Profile", page_icon="🛡️", layout="centered")


def init_supabase() -> Client:
    # Streamlit Community Cloud can use secrets.toml; Render uses environment variables.
    try:
        supabase_settings = st.secrets.get("supabase", {})
    except Exception:
        supabase_settings = {}
    supabase_url = supabase_settings.get("url") or os.getenv("SUPABASE_URL")
    supabase_key = supabase_settings.get("key") or os.getenv("SUPABASE_KEY")
    if not supabase_url or not supabase_key:
        raise RuntimeError(
            "Set SUPABASE_URL and SUPABASE_KEY in the hosting provider's environment settings."
        )
    return create_client(supabase_url, supabase_key)


def build_profile_url(token: str) -> str:
    """Build the profile link from the app address currently open in the browser."""
    # Use this running app's own address first. This prevents a stale URL setting
    # from sending NFC links to a different Streamlit app.
    try:
        base_url = st.context.url
    except Exception:
        base_url = None
    if not base_url:
        try:
            base_url = st.secrets.get("public_app_url")
        except Exception:
            base_url = None
    base_url = base_url or os.getenv("PUBLIC_APP_URL")
    if not base_url:
        raise ValueError(
            "Set public_app_url in .streamlit/secrets.toml or the PUBLIC_APP_URL "
            "environment variable to the full deployed app URL."
        )
    return f"{base_url.rstrip('/')}?{urlencode({'tag_token': token})}"


supabase = init_supabase()

# Read the token from the URL, e.g. https://your-app.streamlit.app/?tag_token=...
tag_token = st.query_params.get("tag_token")

if tag_token:
    try:
        tag_res = (
            supabase.table("nfc_tags")
            .select("student_id, status")
            .eq("public_token", tag_token)
            .execute()
        )

        if not tag_res.data:
            st.error("🚨 Access refused: invalid token.")
            st.stop()

        tag = tag_res.data[0]
        if tag.get("status") and tag["status"].lower() not in {"active", "enabled"}:
            st.error("🚨 This NFC tag is not active.")
            st.stop()

        student_uuid = tag["student_id"]
        child_res = supabase.table("students").select("*").eq("id", student_uuid).execute()
        if not child_res.data:
            st.error("🚨 Student profile not found.")
            st.stop()

        child = child_res.data[0]
        guardian_res = supabase.table("guardians").select("*").eq("student_id", student_uuid).execute()
        guardians = guardian_res.data or []
    except Exception as e:
        st.error(f"Connection error while validating the profile link: {e}")
        st.stop()

    st.title("🛡️ Student Safety Profile")
    st.caption("Emergency information for this student")
    with st.container(border=True):
        photo_url = child.get("photo_url")
        if isinstance(photo_url, str) and photo_url.strip():
            st.image(photo_url, width=200)
        st.header(child.get("full_name") or "Student")
        st.caption(f"Class / Grade: {child.get('class_name') or 'Not specified'}")
        bio = child.get("bio")
        if bio:
            st.write(bio)

    allergies = child.get("allergies")
    if allergies and str(allergies).strip().lower() not in {"none", "n/a", "na"}:
        st.warning(f"⚠️ Known allergies: {allergies}")
    safety_notes = child.get("safety_notes")
    if safety_notes:
        st.info(f"📌 Critical safety notes: {safety_notes}")

    st.subheader("📞 Emergency Contacts")
    if guardians:
        for guardian in guardians:
            name = guardian.get("full_name") or "Guardian"
            relationship = guardian.get("relationship")
            primary_badge = "⭐ Primary guardian · " if guardian.get("is_primary") else ""
            st.write(f"**{primary_badge}{name}**" + (f" ({relationship})" if relationship else ""))
            phone = guardian.get("phone")
            if phone:
                clean_phone = "".join(ch for ch in str(phone) if ch.isdigit() or ch == "+")
                st.link_button(f"Call {name}", f"tel:{clean_phone}", use_container_width=True)
    else:
        st.info("No guardian contact is listed for this student.")
    st.stop()

st.sidebar.title("🛡️ Proximind Safety Hub")
app_mode = st.sidebar.radio("Navigation Menu:", ["🚀 Admin Dashboard (Demo)", "ℹ️ System Info"])

if app_mode == "🚀 Admin Dashboard (Demo)":
    st.title("🔑 Administrative Control Panel (DEMO MODE)")
    st.warning("Demo mode: administrative authentication is disabled.")
    admin_tabs = st.tabs(["📋 Student Directory", "➕ Register New Record", "🔗 Assign NFC Tags"])

    with admin_tabs[0]:
        st.subheader("Student Database Manifest")
        try:
            students_res = supabase.table("students").select("*").execute().data
            if students_res:
                st.dataframe(
                    pd.DataFrame(students_res)[["student_id", "full_name", "class_name", "allergies"]],
                    use_container_width=True,
                )
            else:
                st.info("No active student items found.")
        except Exception as e:
            st.error(f"Database read failure: {e}")

    with admin_tabs[1]:
        st.subheader("Enroll New Student Identity")
        with st.form("new_student_form", clear_on_submit=True):
            s_id = st.text_input("School Registration ID (e.g. AUS-2026-001):")
            s_name = st.text_input("Legal Full Name:")
            s_class = st.text_input("Assigned Classroom / Grade:")
            s_photo = st.text_input("Photo Storage URL:")
            s_allergies = st.text_input("Known Allergies:", value="None")
            s_notes = st.text_area("Critical Safety / Behavioral Notes:")
            s_bio = st.text_area("Profile Biography / Extra Info:")
            st.write("---")
            st.subheader("Primary Guardian Information")
            g_name = st.text_input("Guardian Full Name:")
            g_rel = st.text_input("Relationship to Child:")
            g_phone = st.text_input("Phone Number (include country code):")

            if st.form_submit_button("COMMIT RECORD TRANSACTION TO CLOUD"):
                if not s_id or not s_name or not g_phone:
                    st.error("ID, name, and guardian phone cannot be blank.")
                else:
                    try:
                        inserted_student = supabase.table("students").insert({
                            "student_id": s_id,
                            "full_name": s_name,
                            "photo_url": s_photo,
                            "bio": s_bio,
                            "class_name": s_class,
                            "allergies": s_allergies,
                            "safety_notes": s_notes,
                        }).execute()
                        new_student_uuid = inserted_student.data[0]["id"]
                        supabase.table("guardians").insert({
                            "student_id": new_student_uuid,
                            "full_name": g_name,
                            "relationship": g_rel,
                            "phone": g_phone,
                            "is_primary": True,
                        }).execute()
                        st.success(f"Registered {s_name} with a primary guardian contact.")
                    except Exception as e:
                        st.error(f"Failed to submit: {e}")

    with admin_tabs[2]:
        st.subheader("Configure Physical NFC Tokens")
        try:
            students_list = supabase.table("students").select("id, full_name, student_id").execute().data
            if students_list:
                student_options = {
                    f"{s['full_name']} ({s['student_id']})": s["id"] for s in students_list
                }
                selected_child_name = st.selectbox("Select Student to Bind to Tag:", list(student_options))
                selected_uuid = student_options[selected_child_name]

                if st.button("GENERATE NEW SECURE NFC TOKEN"):
                    try:
                        # Fail before inserting a token if the app's public address cannot be read.
                        build_profile_url("configuration-check")
                        tag_res = supabase.table("nfc_tags").insert({"student_id": selected_uuid}).execute()
                        hex_token = tag_res.data[0]["public_token"]
                        profile_url = build_profile_url(hex_token)
                        st.success("Secure NFC profile link generated.")
                        st.write("Write this full URL to the NFC tag as a URI/URL record:")
                        st.code(profile_url)
                        st.link_button("Open student profile", profile_url)
                    except Exception as e:
                        existing_tag = (
                            supabase.table("nfc_tags")
                            .select("public_token")
                            .eq("student_id", selected_uuid)
                            .execute()
                        )
                        if existing_tag.data:
                            profile_url = build_profile_url(existing_tag.data[0]["public_token"])
                            st.info("An NFC token already exists for this student:")
                            st.code(profile_url)
                            st.link_button("Open student profile", profile_url)
                        else:
                            st.error(f"Could not generate or retrieve the profile link: {e}")
            else:
                st.info("No students registered yet.")
        except Exception as e:
            st.error(f"Failed to query records: {e}")

elif app_mode == "ℹ️ System Info":
    st.title("🛡️ Proximind Safety Systems")
    st.info("NFC tag links open the matching student profile when the app is deployed and the token is valid.")
