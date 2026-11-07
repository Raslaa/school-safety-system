import os
import pandas as pd
import streamlit as st
from supabase import create_client, Client

# Initialize Database securely from secrets.toml
# Initialize Database securely from secrets.toml with direct visual debugging
@st.cache_resource
def init_supabase() -> Client:
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        
        # Guard check against bad homepage URLs
        if "supabase.co" in url and len(url) < 30:
            st.error(f"⚠️ Configuration Error: Your URL looks too short ({url}). It must contain your exact 20-character reference ID.")
            st.info("💡 Open your Supabase Dashboard ➔ Project Settings (Gear) ➔ API. Copy the full link from the URL block field and update your secrets box.")
            st.stop()
            
        return create_client(url, key)
    except KeyError:
        st.error("🔒 Secrets Missing: Please populate your [supabase] variables inside the cloud settings panel.")
        st.stop()
    except Exception as e:
        # If it returns HTML, catch it and show helpful visual guidance
        st.error("🚨 Network Connection Refused: The app received an HTML error webpage instead of database data.")
        st.info("This means the URL inside your secrets panel is incorrect or pointing to a paused project database cluster.")
        st.write("---")
        st.write("### 🛠️ Double-Check your Secrets values right now:")
        st.write(f"Current Configured URL: `{st.secrets['supabase'].get('url', 'NOT SET')}`")
        st.write(f"Current Configured Key Length: `{len(st.secrets['supabase'].get('key', ''))} characters`")
        st.stop()

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
# =============================================================
# STAGE 3: STUDENT MANAGEMENT & ADMINISTRATION SYSTEM
# =============================================================
elif app_mode == "Admin Portal Management":
    st.title("🔑 Administrative Control Panel")
    
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False

    # IF NOT LOGGED IN, SHOW LOGIN FORM
    if not st.session_state.logged_in:
        email = st.text_input("Admin Email Address:")
        password = st.text_input("Password / Security Access Code:", type="password")
        
        if st.button("AUTHENTICATE SESSION", use_container_width=True):
            try:
                # 1. Sign in via Supabase Auth
                auth_res = supabase.auth.sign_in_with_password({"email": email, "password": password})
                
                if auth_res.user:
                    user_uuid = auth_res.user.id
                    
                    # 2. FORCE A DIRECT CHECK: See if this UUID is actually inside your public.admin_users table
                    admin_check = supabase.table("admin_users").select("*").eq("user_id", user_uuid).execute()
                    
                    if admin_check.data:
                        st.session_state.logged_in = True
                        st.success("Session verified! Accessing secure system data modules...")
                        st.rerun()
                    else:
                        st.error(f"Authentication rejected: Your account exists, but your UID ({user_uuid}) is missing from the public.admin_users table layout.")
                else:
                    st.error("Authentication rejected: User token could not be verified.")
            except Exception as e:
                st.error(f"Authentication rejected: Check your credentials or network configuration. Error: {str(e)}")
        st.stop()
