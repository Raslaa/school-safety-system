import os
from urllib.parse import urlencode

import pandas as pd
import streamlit as st
from supabase import create_client, Client


st.set_page_config(
    page_title="Student Safety Profile",
    page_icon="🛡️",
    layout="wide",
)


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


def section_heading(title: str, description: str | None = None) -> None:
    """Render a consistent heading and optional short description."""
    st.subheader(title)
    if description:
        st.caption(description)


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
        guardian_res = (
            supabase.table("guardians").select("*").eq("student_id", student_uuid).execute()
        )
        guardians = guardian_res.data or []
    except Exception as e:
        st.error(f"Connection error while validating the profile link: {e}")
        st.stop()

    st.title("🛡️ Student Safety Profile")
    st.caption("Emergency information for this student")
    st.divider()

    # Student identity and photo
    with st.container(border=True):
        photo_col, details_col = st.columns([1, 3], vertical_alignment="center")
        photo_url = child.get("photo_url")
        with photo_col:
            if isinstance(photo_url, str) and photo_url.strip():
                st.image(photo_url, width=220, alt="Student photo")
            else:
                st.caption("No photo available")
        with details_col:
            st.header(child.get("full_name") or "Student")
            st.caption(f"Class / Grade · {child.get('class_name') or 'Not specified'}")
            bio = child.get("bio")
            if bio:
                st.write(bio)

    # Important medical and care information
    allergies = child.get("allergies")
    safety_notes = child.get("safety_notes")
    has_allergies = allergies and str(allergies).strip().lower() not in {"none", "n/a", "na"}
    if has_allergies or safety_notes:
        st.write("")
        section_heading("⚠️ Important Safety Information")
        with st.container(border=True):
            if has_allergies:
                st.warning(f"Known allergies: {allergies}")
            if safety_notes:
                st.info(f"Critical safety notes: {safety_notes}")

    # Emergency contacts
    st.write("")
    section_heading("📞 Emergency Contacts", "Contact a parent or guardian using the buttons below.")
    if guardians:
        contact_columns = st.columns(min(len(guardians), 2))
        for index, guardian in enumerate(guardians):
            with contact_columns[index % len(contact_columns)]:
                with st.container(border=True):
                    name = guardian.get("full_name") or "Guardian"
                    relationship = guardian.get("relationship")
                    if guardian.get("is_primary"):
                        st.caption("⭐ PRIMARY GUARDIAN")
                    st.markdown(f"**{name}**")
                    if relationship:
                        st.caption(relationship)
                    phone = guardian.get("phone")
                    if phone:
                        clean_phone = "".join(ch for ch in str(phone) if ch.isdigit() or ch == "+")
                        st.link_button(f"Call {name}", f"tel:{clean_phone}", use_container_width=True)
                    else:
                        st.caption("No phone number listed")
    else:
        with st.container(border=True):
            st.info("No guardian contact is listed for this student.")
    st.stop()


# Admin dashboard
st.sidebar.title("🛡️ Proximind Safety Hub")
st.sidebar.caption("Student records and NFC tag management")
app_mode = st.sidebar.radio("Navigation", ["🚀 Admin Dashboard (Demo)", "ℹ️ System Info"])

if app_mode == "🚀 Admin Dashboard (Demo)":
    st.title("Administrative Control Panel")
    st.caption("Manage student records, guardian contacts, and NFC profile links.")
    st.warning("Demo mode: administrative authentication is disabled.")

    admin_tabs = st.tabs(["📋 Student Directory", "➕ Register New Record", "🔗 Assign NFC Tags"])

    with admin_tabs[0]:
        section_heading("Student Directory", "Browse registered students and key safety details.")
        with st.container(border=True):
            try:
                students_res = supabase.table("students").select("*").execute().data
                if students_res:
                    student_frame = pd.DataFrame(students_res)
                    visible_columns = [
                        column
                        for column in ["student_id", "full_name", "class_name", "allergies"]
                        if column in student_frame.columns
                    ]
                    st.dataframe(
                        student_frame[visible_columns],
                        use_container_width=True,
                        hide_index=True,
                    )
                else:
                    st.info("No student records found yet.")
            except Exception as e:
                st.error(f"Database read failure: {e}")

    with admin_tabs[1]:
        section_heading(
            "Register a Student",
            "Add the student profile and a primary guardian contact.",
        )
        with st.form("new_student_form", clear_on_submit=True):
            with st.container(border=True):
                st.markdown("#### Student details")
                identity_col, class_col = st.columns(2)
                with identity_col:
                    s_id = st.text_input("School Registration ID", placeholder="e.g. AUS-2026-001")
                    s_name = st.text_input("Full Name")
                with class_col:
                    s_class = st.text_input("Class / Grade")
                    s_photo = st.text_input("Photo URL", placeholder="https://…")
                s_bio = st.text_area("Profile Biography / Extra Information", height=90)

            with st.container(border=True):
                st.markdown("#### Safety details")
                s_allergies = st.text_input("Known Allergies", value="None")
                s_notes = st.text_area("Critical Safety / Behavioral Notes", height=100)

            with st.container(border=True):
                st.markdown("#### Primary guardian")
                guardian_col, relationship_col, phone_col = st.columns(3)
                with guardian_col:
                    g_name = st.text_input("Guardian Full Name")
                with relationship_col:
                    g_rel = st.text_input("Relationship to Child")
                with phone_col:
                    g_phone = st.text_input("Phone Number", placeholder="Include country code")

            st.write("")
            submitted = st.form_submit_button(
                "Save Student Record",
                type="primary",
                use_container_width=True,
            )
            if submitted:
                if not s_id or not s_name or not g_phone:
                    st.error("Registration ID, student name, and guardian phone are required.")
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
        section_heading(
            "Assign an NFC Tag",
            "Generate a profile link and write it to the student's NFC tag.",
        )
        with st.container(border=True):
            try:
                students_list = (
                    supabase.table("students").select("id, full_name, student_id").execute().data
                )
                if students_list:
                    student_options = {
                        f"{student['full_name']} ({student['student_id']})": student["id"]
                        for student in students_list
                    }
                    selected_child_name = st.selectbox(
                        "Select Student",
                        list(student_options),
                    )
                    selected_uuid = student_options[selected_child_name]

                    if st.button("Generate Secure NFC Link", type="primary"):
                        try:
                            # Fail before inserting a token if the app's public address cannot be read.
                            build_profile_url("configuration-check")
                            tag_res = supabase.table("nfc_tags").insert(
                                {"student_id": selected_uuid}
                            ).execute()
                            hex_token = tag_res.data[0]["public_token"]
                            profile_url = build_profile_url(hex_token)
                            st.success("NFC profile link generated.")
                            st.caption("Write this URL to the NFC tag as a URI/URL record:")
                            st.code(profile_url)
                            st.link_button("Open Student Profile", profile_url)
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
                                st.link_button("Open Student Profile", profile_url)
                            else:
                                st.error(f"Could not generate or retrieve the profile link: {e}")
                else:
                    st.info("Register a student before assigning an NFC tag.")
            except Exception as e:
                st.error(f"Failed to query records: {e}")

elif app_mode == "ℹ️ System Info":
    st.title("🛡️ Proximind Safety Systems")
    st.caption("About the student safety profile and NFC workflow.")
    with st.container(border=True):
        st.write(
            "NFC tag links open the matching student profile when the app is deployed "
            "and the token is valid."
        )
