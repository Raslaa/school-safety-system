import os
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlencode, urlparse
import pandas as pd
import streamlit as st
from supabase import create_client, Client

LOCATION_FRESH_SECONDS = 120
LOCATION_RETENTION_HOURS = 24

GPS_HTML = """
<div>
  <button id="gps-start" type="button">Start location sharing</button>
  <button id="gps-stop" type="button">Stop sharing</button>
  <p id="gps-status" aria-live="polite">Location sharing is off.</p>
</div>
"""

GPS_CSS = """
button { border: 0; border-radius: .5rem; padding: .65rem 1rem; margin: 0 .5rem .5rem 0;
  background: var(--st-primary-color); color: var(--st-background-color); font: inherit;
  font-weight: 600; cursor: pointer; }
#gps-stop { background: transparent; color: var(--st-primary-color); border: 1px solid var(--st-primary-color); }
p { color: var(--st-text-color); }
"""

GPS_JS = """
export default function(component) {
  const { parentElement, setStateValue, setTriggerValue } = component;
  const start = parentElement.querySelector('#gps-start');
  const stop = parentElement.querySelector('#gps-stop');
  const status = parentElement.querySelector('#gps-status');
  let watchId = null;
  let lastSent = 0;
  function show(message) { status.textContent = message; setStateValue('status', message); }

  start.onclick = () => {
    if (!navigator.geolocation) { show('This browser does not support location sharing.'); return; }
    if (watchId !== null) return;
    show('Requesting location permission…');
    watchId = navigator.geolocation.watchPosition((position) => {
      const now = Date.now();
      if (now - lastSent < 15000) return;
      lastSent = now;
      show('Sharing location. Keep this page open.');
      setTriggerValue('position', {
        latitude: position.coords.latitude,
        longitude: position.coords.longitude,
        accuracy: position.coords.accuracy,
        captured_at: new Date(position.timestamp).toISOString()
      });
    }, (error) => {
      const messages = {1:'Location permission denied. Allow it in browser settings.',
        2:'Your device could not determine its location. Try again outdoors.',
        3:'Location request timed out. Keep the page open and try again.'};
      show(messages[error.code] || 'Location is unavailable.');
      if (watchId !== null) navigator.geolocation.clearWatch(watchId);
      watchId = null;
    }, {enableHighAccuracy:true, maximumAge:10000, timeout:30000});
  };

  stop.onclick = () => {
    if (watchId !== null && navigator.geolocation) navigator.geolocation.clearWatch(watchId);
    watchId = null;
    show('Sharing stopped.');
    setTriggerValue('stop', Date.now());
  };
  return () => { if (watchId !== null && navigator.geolocation) navigator.geolocation.clearWatch(watchId); };
}
"""

# Initialize Database securely from secrets.toml
def init_supabase() -> Client:
    try:
        settings = st.secrets.get("supabase", {})
    except Exception:
        settings = {}
    url = settings.get("url") or os.getenv("SUPABASE_URL")
    # This Streamlit app talks to Supabase from its Python server. Prefer a
    # server-only secret key (or legacy service_role key), never a publishable/
    # anon key, because the app performs privileged admin and parent-link work.
    key = (
        settings.get("secret_key")
        or settings.get("service_role_key")
        or os.getenv("SUPABASE_SECRET_KEY")
        or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or settings.get("key")
        or os.getenv("SUPABASE_KEY")
    )
    if not url or not key:
        raise RuntimeError(
            "Set Supabase url and a server-side secret/service-role key in Streamlit secrets "
            "or environment variables. Do not use the publishable/anon key for this app."
            "Supabase server key is missing. In Streamlit Secrets, set [supabase].secret_key "
            "to the Supabase Secret key, or [supabase].service_role_key to the legacy service_role key. "
            "The generic 'key' setting and publishable/anon keys are not accepted."
        )
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


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def valid_share(token: str):
    result = (
        supabase.table("student_location_shares")
        .select("student_id")
        .eq("token_hash", token_hash(token))
        .eq("enabled", True)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def save_current_location(student_id: str, point: dict) -> str | None:
    try:
        latitude = float(point["latitude"])
        longitude = float(point["longitude"])
        accuracy = float(point["accuracy"])
        captured = datetime.fromisoformat(str(point["captured_at"]).replace("Z", "+00:00"))
        if captured.tzinfo is None:
            captured = captured.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            return "The device returned invalid coordinates."
        if not (0 <= accuracy <= 10000):
            return "The device returned invalid GPS accuracy."
        if captured > now + timedelta(seconds=60) or captured < now - timedelta(minutes=5):
            return "The GPS reading is too old or the device clock is incorrect. Waiting for a fresh reading."
        supabase.table("student_live_locations").upsert(
            {
                "student_id": student_id,
                "latitude": latitude,
                "longitude": longitude,
                "accuracy_meters": accuracy,
                "captured_at": captured.astimezone(timezone.utc).isoformat(),
            },
            on_conflict="student_id",
        ).execute()
    except (KeyError, TypeError, ValueError, OverflowError):
        return "Could not read the location result. Please try again."
    except Exception:
        return "Could not save the location. Check the connection and try again."
    return None

supabase = init_supabase()

# NFC profiles and guardian sharing use separate private/public URL parameters.
tag_token = st.query_params.get("tag_token", None)

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


# Guardian portal: a private sharing link opens this page directly.
share_token = st.query_params.get("share_token")
if share_token:
    try:
        share = valid_share(str(share_token))
    except Exception:
        share = None
    if not share:
        st.error("This parent sharing link is invalid or has been disabled.")
        st.stop()

    student_uuid = share["student_id"]
    student_res = (
        supabase.table("students")
        .select("full_name, class_name")
        .eq("id", student_uuid)
        .limit(1)
        .execute()
    )
    if not student_res.data:
        st.error("Student profile not found.")
        st.stop()
    student = student_res.data[0]

    st.title("👨‍👩‍👦 Parent Location Portal")
    st.caption("Proximind Safety Hub")
    with st.container(border=True):
        st.subheader(f"Share location for {student.get('full_name') or 'this student'}")
        st.write(
            "When you press **Start location sharing**, this phone will ask for your permission "
            "and send its latest GPS position to the school's protected admin dashboard. "
            "Sharing works only while this page is open. The system stores the latest point, "
            "not a route history."
        )
        st.caption("You can stop sharing at any time. Location access requires HTTPS and browser permission.")
        consent = st.checkbox(
            "I understand and want to share this phone's location for this student.",
            key="parent_location_consent",
        )

    if consent:
        gps_component = st.components.v2.component(
            "parent_location_sharing",
            html=GPS_HTML,
            css=GPS_CSS,
            js=GPS_JS,
        )
        gps_result = gps_component(
            key="parent_gps_component",
            on_position_change=lambda: None,
            on_stop_change=lambda: None,
            on_status_change=lambda: None,
        )
        stop_event = getattr(gps_result, "stop", None)
        if stop_event and st.session_state.get("parent_last_stop") != stop_event:
            supabase.table("student_live_locations").delete().eq(
                "student_id", student_uuid
            ).execute()
            st.session_state["parent_last_stop"] = stop_event
            st.session_state.pop("parent_last_location_time", None)
            st.success("Sharing stopped and the saved location was removed.")

        point = getattr(gps_result, "position", None)
        if isinstance(point, dict) and point.get("captured_at"):
            captured_at = str(point["captured_at"])
            if st.session_state.get("parent_last_location_time") != captured_at:
                location_error = save_current_location(student_uuid, point)
                if location_error:
                    st.warning(location_error)
                else:
                    st.session_state["parent_last_location_time"] = captured_at
                    st.success("Location received. Sharing stays on while this page remains open.")
    else:
        st.info("Check the box above to enable the Start location sharing button.")
    st.stop()

# -------------------------------------------------------------
# BACKUP DEMO FALLBACK (IF NO TOKEN IS PRESENT)
# -------------------------------------------------------------
st.sidebar.title("🛡️ Proximind Safety Hub")
app_mode = st.sidebar.radio("Navigation View Portal:", ["🚀 Admin Dashboard", "👨‍👩‍👦 Parent Portal Gateway"])

if app_mode == "👨‍👩‍👦 Parent Portal Gateway":
    st.title("👨‍👩‍👦 Parent Portal")
    st.write("Open the private location-sharing link provided by the school to begin sharing.")
    with st.form("parent_link_form"):
        parent_token = st.text_input("Paste your private parent sharing link or code", type="password")
        open_portal = st.form_submit_button("Open Parent Portal", type="primary")
    if open_portal and parent_token.strip():
        submitted_value = parent_token.strip()
        if "share_token=" in submitted_value:
            submitted_value = parse_qs(urlparse(submitted_value).query).get("share_token", [""])[0]
        st.query_params["share_token"] = submitted_value
        st.rerun()
    st.stop()

# 🚀 VIEW A: ADMIN DASHBOARD PANEL
if app_mode == "🚀 Admin Dashboard":
    try:
        admin_password = st.secrets.get("ADMIN_PASSWORD") or os.getenv("ADMIN_PASSWORD")
    except Exception:
        admin_password = os.getenv("ADMIN_PASSWORD")
    if not admin_password:
        st.error("Admin access is disabled until you set a strong ADMIN_PASSWORD in deployment secrets.")
        st.stop()
    if not st.session_state.get("admin_authenticated"):
        st.title("🔐 Administrator Sign In")
        with st.form("admin_login_form"):
            entered_password = st.text_input("Admin password", type="password")
            login_clicked = st.form_submit_button("Sign in", type="primary")
        if login_clicked:
            import hmac
            if hmac.compare_digest(entered_password, str(admin_password)):
                st.session_state["admin_authenticated"] = True
                st.rerun()
            st.error("Incorrect password.")
        st.stop()

    if st.sidebar.button("Sign out"):
        st.session_state.pop("admin_authenticated", None)
        st.rerun()

    st.title("🔑 Administrative Control Panel")
    admin_tabs = st.tabs(["📋 Student Directory", "➕ Register New Record", "🔗 Assign NFC Tags", "📍 Live GPS"])

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
        st.subheader("📍 Guardian Location Sharing")
        st.caption("Create a private parent link, revoke it, or view recent locations.")
        try:
            # Read all columns so an optional/missing display column (for example
            # student_id) does not make the whole selector query fail.
            students_for_gps = supabase.table("students").select("*").execute().data or []
            def student_display_name(row):
                name = row.get("full_name") or row.get("student_name") or row.get("name") or "Student"
                school_id = row.get("student_id") or row.get("registration_id") or row.get("school_id") or "No school ID"
                return f"{name} ({school_id})"

            students_by_uuid = {
                str(row["id"]): student_display_name(row)
                for row in students_for_gps
                if row.get("id") is not None
            }
            if students_for_gps:
                if not students_by_uuid:
                    st.error(
                        "Student rows were found, but none has an `id` value. "
                        "The parent location tables need `students.id` as the student key."
                    )
                else:
                    # Include the row id in the option label so duplicate names/IDs
                    # do not silently overwrite each other in a dictionary.
                    student_rows = [row for row in students_for_gps if row.get("id") is not None]
                    student_labels = [
                        f"{student_display_name(row)} · {str(row['id'])[:8]}"
                        for row in student_rows
                    ]
                    selected_index = st.selectbox(
                        "Select student", range(len(student_rows)),
                        format_func=lambda index: student_labels[index], key="gps_student",
                    )
                    selected_student_id = student_rows[selected_index]["id"]
                    st.caption(f"{len(student_rows)} student(s) available.")
                    create_col, disable_col = st.columns(2)
                    with create_col:
                        if st.button("Create / Reset Parent Sharing Link", type="primary"):
                            raw_token = secrets.token_urlsafe(32)
                            supabase.table("student_location_shares").upsert(
                                {
                                    "student_id": selected_student_id,
                                    "token_hash": token_hash(raw_token),
                                    "enabled": True,
                                },
                                on_conflict="student_id",
                            ).execute()
                            st.success("New parent link created. Any previous link for this student is now invalid.")
                            st.code(build_app_url("share_token", raw_token))
                            st.caption("Send this link privately to the parent. It can submit a location but cannot view it.")
                    with disable_col:
                        if st.button("Disable Parent Sharing Link"):
                            supabase.table("student_location_shares").update({"enabled": False}).eq(
                                "student_id", selected_student_id
                            ).execute()
                            supabase.table("student_live_locations").delete().eq(
                                "student_id", selected_student_id
                            ).execute()
                            st.success("Parent link disabled and latest location removed.")
            else:
                st.info(
                    "No student records were returned from Supabase. Add students in the Student Directory / Register tab, "
                    "then refresh this page. If students are already registered, check the app's Supabase URL/key and "
                    "the `students` table permissions."
                )

            st.divider()
            st.markdown("#### Recent locations")
            st.caption("Map refreshes every 15 seconds. Locations older than two minutes are hidden.")
            retention_cutoff = datetime.now(timezone.utc) - timedelta(hours=LOCATION_RETENTION_HOURS)
            supabase.table("student_live_locations").delete().lt(
                "captured_at", retention_cutoff.isoformat()
            ).execute()

            @st.fragment(run_every="15s")
            def show_recent_locations():
                cutoff = datetime.now(timezone.utc) - timedelta(seconds=LOCATION_FRESH_SECONDS)
                rows = (
                    supabase.table("student_live_locations")
                    .select("student_id, latitude, longitude, accuracy_meters, captured_at")
                    .gte("captured_at", cutoff.isoformat())
                    .execute()
                    .data
                    or []
                )
                if not rows:
                    st.info("No parent phones are sharing a recent location right now.")
                    return
                points = []
                detail_rows = []
                for row in rows:
                    points.append({"lat": float(row["latitude"]), "lon": float(row["longitude"])})
                    captured = datetime.fromisoformat(str(row["captured_at"]).replace("Z", "+00:00"))
                    detail_rows.append(
                        {
                            "Student": students_by_uuid.get(str(row["student_id"]), "Student"),
                            "Updated (UTC)": captured.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                            "Accuracy (m)": round(float(row["accuracy_meters"])),
                        }
                    )
                st.map(pd.DataFrame(points), latitude="lat", longitude="lon")
                st.dataframe(pd.DataFrame(detail_rows), use_container_width=True, hide_index=True)

            show_recent_locations()
        except Exception as e:
            st.error(f"Could not load GPS sharing data: {e}")
