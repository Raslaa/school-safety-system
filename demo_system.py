import os
import base64
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlencode, urlparse
import pandas as pd
import streamlit as st
from supabase import create_client, Client

LOCATION_FRESH_SECONDS = 120
SCAN_LOCATION_RETENTION_HOURS = 24

SCAN_GPS_HTML = """
<div class="scan-location-action" style="border:3px solid #075E54;border-radius:14px;padding:20px;background:#EAF7F5;font-family:Georgia, 'Times New Roman', serif;">
  <button id="scan-gps-share" type="button" style="border:2px solid #064B44;border-radius:10px;padding:17px 24px;background:#075E54;color:#FFFFFF;font-family:Arial, Helvetica, sans-serif;font-size:21px;font-weight:800;letter-spacing:.02em;cursor:pointer;">
    📍 Start live location sharing
  </button>
  <button id="scan-gps-stop" type="button" style="display:none;border:2px solid #075E54;border-radius:10px;padding:14px 20px;background:#FFFFFF;color:#075E54;font-family:Arial, Helvetica, sans-serif;font-size:18px;font-weight:800;cursor:pointer;">
    Stop sharing
  </button>
  <p id="scan-gps-status" aria-live="polite" style="margin:12px 0 0;color:#163B37;font-family:Georgia, 'Times New Roman', serif;font-size:15px;font-weight:600;line-height:1.5;">
    Location permission is requested only after you press Start.
  </p>
</div>
"""

SCAN_GPS_CSS = """
.scan-location-action {
  border: 2px solid var(--st-primary-color);
  border-radius: 12px;
  padding: 1rem;
  background: color-mix(in srgb, var(--st-primary-color) 8%, var(--st-background-color));
  font-family: Arial, Helvetica, sans-serif;
}
#scan-gps-share {
  border: 2px solid var(--st-primary-color);
  border-radius: 8px;
  padding: .75rem 1rem;
  background: var(--st-primary-color);
  color: var(--st-background-color);
  font: 700 1rem/1.35 Arial, Helvetica, sans-serif;
  letter-spacing: .01em;
  cursor: pointer;
}
#scan-gps-share:focus-visible {
  outline: 3px solid var(--st-text-color);
  outline-offset: 3px;
}
#scan-gps-share:disabled { opacity: .7; cursor: wait; }
#scan-gps-share { border: 2px solid #064B44; background: #075E54; color: #FFFFFF; font-size: 21px; font-weight: 800; }
#scan-gps-stop { margin-left: .5rem; }
#scan-gps-status {
  margin: .75rem 0 0;
  font: 500 .9rem/1.45 Arial, Helvetica, sans-serif;
  color: var(--st-text-color);
}
"""

SCAN_GPS_JS = """
export default function(component) {
  const { parentElement, setStateValue, setTriggerValue } = component;
  const button = parentElement.querySelector('#scan-gps-share');
  const stopButton = parentElement.querySelector('#scan-gps-stop');
  const status = parentElement.querySelector('#scan-gps-status');
  let watchId = null;
  let lastSent = 0;
  function show(message) { status.textContent = message; setStateValue('status', message); }
  function stopWatch(message, notifyServer = true) {
    if (watchId !== null && navigator.geolocation) navigator.geolocation.clearWatch(watchId);
    watchId = null;
    button.disabled = false;
    stopButton.style.display = 'none';
    show(message);
    if (notifyServer) setTriggerValue('stop', Date.now());
  }
  button.onclick = () => {
    if (!navigator.geolocation) { show('This browser does not support location sharing.'); return; }
    if (watchId !== null) return;
    button.disabled = true;
    show('Requesting permission for this phone’s location…');
    watchId = navigator.geolocation.watchPosition((position) => {
      const now = Date.now();
      if (now - lastSent < 15000) return;
      lastSent = now;
      button.disabled = true;
      stopButton.style.display = 'inline-block';
      show(`🟢 Live sharing is on. Reported GPS accuracy: ±${Math.round(position.coords.accuracy)} m. Keep this page open for fresh fixes.`);
      setTriggerValue('position', {
        latitude: position.coords.latitude,
        longitude: position.coords.longitude,
        accuracy: position.coords.accuracy,
        captured_at: new Date(position.timestamp).toISOString()
      });
    }, (error) => {
      const messages = {1:'Permission was denied. No location was shared.',
        2:'This phone could not determine its location. Try again outdoors.',
        3:'The location request timed out. Please try again.'};
      stopWatch(messages[error.code] || 'Location is unavailable.');
    }, {enableHighAccuracy:true, maximumAge:0, timeout:60000});
    stopButton.style.display = 'inline-block';
    stopButton.onclick = () => stopWatch('Sharing stopped.');
  };
  return () => { if (watchId !== null && navigator.geolocation) navigator.geolocation.clearWatch(watchId); };
}
"""

# Initialize Database securely from secrets.toml
def init_supabase() -> Client:
    try:
        settings = st.secrets.get("supabase", {})
    except Exception:
        st.error(
            "Could not read Streamlit Secrets. Check Manage app → Settings → Secrets for valid TOML formatting."
        )
        st.stop()
    url = settings.get("url") or os.getenv("SUPABASE_URL")
    # This Streamlit app talks to Supabase from its Python server. Prefer a
    # server-only secret key (or legacy service_role key), never a publishable/
    # anon key, because the app performs privileged admin and parent-link work.
    key = (
        settings.get("secret_key")
        or settings.get("service_role_key")
        or os.getenv("SUPABASE_SECRET_KEY")
        or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    )
    if not url:
        st.error(
            "Supabase URL is missing. In Streamlit Secrets, add `url = \"https://YOUR_PROJECT.supabase.co\"` inside `[supabase]`."
        )
        st.stop()
    if not key:
        st.error(
            "Supabase server key is missing. Add `[supabase].secret_key` (new `sb_secret_...` key) "
            "or `[supabase].service_role_key` (legacy service_role key). A generic `key` or publishable/anon key is not accepted."
        )
        st.stop()
    # Catch the most common copy/paste mistake before the first database query.
    # Legacy API keys are JWTs; inspecting the role claim here does not validate
    # the token, it only prevents knowingly configuring the public anon key.
    if str(key).startswith("sb_publishable_"):
        st.error(
            "The configured Supabase key is a publishable key. Replace it with the "
            "project's Secret key (sb_secret_...) or legacy service_role key in Streamlit Secrets."
        )
        st.stop()
    token_parts = str(key).split(".")
    legacy_role = None
    if len(token_parts) == 3:
        try:
            payload = token_parts[1] + "=" * (-len(token_parts[1]) % 4)
            legacy_role = json.loads(base64.urlsafe_b64decode(payload)).get("role")
        except Exception:
            pass
    if legacy_role == "anon":
        st.error(
            "The configured Supabase key is the legacy anon key. Replace it with the "
            "legacy service_role key or the newer Secret key in Streamlit Secrets."
        )
        st.stop()
    return create_client(url, key)


def build_app_url(parameter: str, value: str, extra_params: dict | None = None) -> str:
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
    params = {parameter: value, **(extra_params or {})}
    return f"{str(base_url).split('?', 1)[0].rstrip('/')}?{urlencode(params)}"


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def valid_share(token: str):
    hashed_token = token_hash(token)
    # New links are unique per guardian and child. Keep old student-wide links
    # valid during migration so existing parents do not lose access at once.
    try:
        result = (
            supabase.table("student_parent_portal_links")
            .select("student_id, guardian_name")
            .eq("token_hash", hashed_token)
            .eq("enabled", True)
            .limit(1)
            .execute()
        )
        if result.data:
            return result.data[0]
    except Exception:
        pass
    result = (
        supabase.table("student_location_shares")
        .select("student_id")
        .eq("token_hash", hashed_token)
        .eq("enabled", True)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def render_location_map(locations: list[dict]) -> None:
    """Render GPS points with a fixed street-level zoom for a single location."""
    if not locations:
        return
    frame = pd.DataFrame(locations)
    frame["latitude"] = frame["latitude"].astype(float)
    frame["longitude"] = frame["longitude"].astype(float)
    span = max(
        float(frame["latitude"].max() - frame["latitude"].min()),
        float(frame["longitude"].max() - frame["longitude"].min()),
    )
    if len(frame) == 1:
        zoom = 18  # Street-level view, centered on the one reported coordinate.
    else:
        zoom = 14 if span < 0.01 else 11 if span < 0.1 else 8
    st.map(
        frame,
        latitude="latitude",
        longitude="longitude",
        size="accuracy_meters" if "accuracy_meters" in frame.columns else 20,
        color="#0e7460",
        zoom=zoom,
        height=600,
        use_container_width=True,
    )


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
            st.error("🚨 Access Refused: This safety tag is inactive or has been reported lost. Please contact the school.")
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

    st.divider()
    with st.container(border=True):
        st.subheader("📍 Share this phone’s live location")
        st.write(
            "Press Start and allow location access to share this phone’s live position with school admins and "
            "the student’s parent/guardian through their private portal link. Fresh browser updates are shared while "
            "this page stays open. Press Stop to end sharing. The last point may remain visible for up to 24 hours. "
            "This is the scanner’s phone location, not verified student tracking; accuracy depends on the device."
        )
        scan_location_component = st.components.v2.component(
            "nfc_scan_location_sharing",
            html=SCAN_GPS_HTML,
            css=SCAN_GPS_CSS,
            js=SCAN_GPS_JS,
        )
        scan_result = scan_location_component(
            key=f"scan_location_{tag_token}",
            on_position_change=lambda: None,
            on_status_change=lambda: None,
            on_stop_change=lambda: None,
        )
        scan_point = getattr(scan_result, "position", None)
        if isinstance(scan_point, dict) and scan_point.get("captured_at"):
            scan_event = f"{tag_token}:{scan_point['captured_at']}"
            if st.session_state.get("last_saved_scan_location") != scan_event:
                try:
                    latitude = float(scan_point["latitude"])
                    longitude = float(scan_point["longitude"])
                    accuracy = float(scan_point["accuracy"])
                    captured = datetime.fromisoformat(
                        str(scan_point["captured_at"]).replace("Z", "+00:00")
                    )
                    if captured.tzinfo is None:
                        captured = captured.replace(tzinfo=timezone.utc)
                    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                        raise ValueError("Invalid coordinates returned by the browser.")
                    if not (0 <= accuracy <= 10000):
                        raise ValueError("Invalid GPS accuracy returned by the browser.")
                    supabase.table("student_tag_scan_locations").upsert(
                        {
                            "student_id": student_uuid,
                            "latitude": latitude,
                            "longitude": longitude,
                            "accuracy_meters": accuracy,
                            "captured_at": captured.astimezone(timezone.utc).isoformat(),
                            "sharing_active": True,
                        },
                        on_conflict="student_id",
                    ).execute()
                    st.session_state["last_saved_scan_location"] = scan_event
                    st.success("Live location update shared with the school and parent portal.")
                except Exception:
                    st.error("Could not save this phone’s scan location. No location was recorded.")
        stop_event = getattr(scan_result, "stop", None)
        if stop_event and st.session_state.get(f"last_scan_stop_{tag_token}") != stop_event:
            try:
                supabase.table("student_tag_scan_locations").update({"sharing_active": False}).eq(
                    "student_id", student_uuid
                ).execute()
                st.session_state[f"last_scan_stop_{tag_token}"] = stop_event
                st.info("Live sharing has stopped. The last shared point remains visible for up to 24 hours.")
            except Exception:
                st.error("Sharing stopped on this phone, but the portal may label the last point stale after two minutes.")
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
        .select("full_name, class_name, student_id")
        .eq("id", student_uuid)
        .limit(1)
        .execute()
    )
    if not student_res.data:
        st.error("Student profile not found.")
        st.stop()
    student = student_res.data[0]
    # The school-facing student ID identifies the child in the URL; the random
    # parent token remains the access credential. Verify the two match.
    url_student_id = st.query_params.get("student_id")
    expected_student_id = str(student.get("student_id") or student_uuid)
    if url_student_id and str(url_student_id) != expected_student_id:
        st.error("This parent link does not match the student ID in the URL.")
        st.stop()

    parent_name = str(share.get("guardian_name") or "Parent")
    st.title(f"👨‍👩‍👦 {parent_name}’s Parent Portal")
    st.caption(f"Private location portal for {student.get('full_name') or 'your child'} · Proximind Safety Hub")
    with st.container(border=True):
        st.subheader("📍 Latest shared NFC scan location")
        st.caption(
            "This is the scanner phone’s location, shared only after that person pressed Start and allowed browser access. "
            "It may not be the student’s location. The portal refreshes every 15 seconds while open; reports older than 24 hours are hidden."
        )

        @st.fragment(run_every="15s")
        def show_parent_scan_report():
            scan_cutoff = datetime.now(timezone.utc) - timedelta(hours=SCAN_LOCATION_RETENTION_HOURS)
            try:
                scan_rows = (
                    supabase.table("student_tag_scan_locations")
                    .select("latitude, longitude, accuracy_meters, captured_at, sharing_active")
                    .eq("student_id", student_uuid)
                    .gte("captured_at", scan_cutoff.isoformat())
                    .order("captured_at", desc=True)
                    .limit(1)
                    .execute()
                    .data
                    or []
                )
            except Exception:
                st.info("NFC scan reports are not available yet. The school may need to apply the latest database setup script.")
                return
            if not scan_rows:
                st.info("No opted-in NFC scan location has been shared in the last 24 hours.")
                return
            scan = scan_rows[0]
            report_key = f"parent_last_seen_nfc_scan_{student_uuid}"
            previous_report = st.session_state.get(report_key)
            current_report = str(scan["captured_at"])
            if previous_report != current_report:
                if previous_report is not None:
                    st.success("New opted-in NFC scan location received.")
                st.session_state[report_key] = current_report
            point = [{
                "student": student.get("full_name") or "Student",
                "latitude": float(scan["latitude"]),
                "longitude": float(scan["longitude"]),
                "accuracy_meters": round(float(scan["accuracy_meters"])),
            }]
            captured = datetime.fromisoformat(str(scan["captured_at"]).replace("Z", "+00:00"))
            if captured.tzinfo is None:
                captured = captured.replace(tzinfo=timezone.utc)
            age_seconds = (datetime.now(timezone.utc) - captured.astimezone(timezone.utc)).total_seconds()
            is_live = bool(scan.get("sharing_active")) and 0 <= age_seconds <= LOCATION_FRESH_SECONDS
            st.success("🟢 Scanner phone is sharing live location now.") if is_live else st.info(
                "Showing the last known scanner phone location. It is no longer updating."
            )
            render_location_map(point)
            maps_url = (
                "https://www.google.com/maps/search/?api=1&query="
                f"{float(scan['latitude']):.6f}%2C{float(scan['longitude']):.6f}"
            )
            st.link_button("Open these coordinates in Google Maps", maps_url)
            st.caption(
                f"Reported {captured.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')} · "
                f"GPS coordinates {float(scan['latitude']):.6f}, {float(scan['longitude']):.6f} · "
                f"reported accuracy ±{round(float(scan['accuracy_meters']))} m. The map circle size reflects "
                "that reported accuracy; zooming in cannot improve the phone’s GPS accuracy."
            )

        show_parent_scan_report()

    with st.container(border=True):
        st.subheader("🔒 NFC tag safety controls")
        st.caption(
            "You can immediately disable an active tag assigned to your child. Once disabled, "
            "its NFC link will no longer show the safety profile."
        )
        try:
            parent_tags = (
                supabase.table("nfc_tags")
                .select("public_token, status")
                .eq("student_id", student_uuid)
                .execute()
                .data
                or []
            )
            active_parent_tags = [
                row for row in parent_tags
                if (row.get("status") or "").lower() in {"active", "enabled"}
                and row.get("public_token")
            ]
            if not active_parent_tags:
                st.info("There are no active NFC tags for this student to terminate.")
            else:
                tag_labels = [
                    f"Active tag ending …{str(row['public_token'])[-6:]}"
                    for row in active_parent_tags
                ]
                tag_index = st.selectbox(
                    "Choose the NFC tag to disable",
                    range(len(active_parent_tags)),
                    format_func=lambda index: tag_labels[index],
                    key=f"parent_tag_to_terminate_{student_uuid}",
                )
                confirm_termination = st.checkbox(
                    "I understand this will stop this tag’s link from opening the student profile.",
                    key=f"confirm_parent_tag_termination_{student_uuid}",
                )
                if st.button(
                    "🚫 Terminate selected NFC tag",
                    type="primary",
                    disabled=not confirm_termination,
                    key=f"terminate_parent_nfc_tag_{student_uuid}",
                ):
                    token_to_terminate = active_parent_tags[tag_index]["public_token"]
                    supabase.table("nfc_tags").update({"status": "lost"}).eq(
                        "student_id", student_uuid
                    ).eq("public_token", token_to_terminate).execute()
                    st.success("NFC tag disabled. Scans of this tag will now be refused.")
                    st.rerun()
        except Exception as e:
            st.error(f"Could not load or disable NFC tags: {e}")

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
        parsed_student_id = None
        if "share_token=" in submitted_value:
            parsed_query = parse_qs(urlparse(submitted_value).query)
            submitted_value = parsed_query.get("share_token", [""])[0]
            parsed_student_id = parsed_query.get("student_id", [None])[0]
        st.query_params["share_token"] = submitted_value
        if parsed_student_id:
            st.query_params["student_id"] = parsed_student_id
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
        st.caption(
            "Report a missing tag to block its current link. Replacing a tag creates a new link; "
            "the old NFC chip cannot be erased remotely."
        )
        try:
            students_list = supabase.table("students").select("id, full_name, student_id").execute().data or []
            if students_list:
                student_options = {f"{s['full_name']} ({s['student_id']})": s["id"] for s in students_list}
                selected_child_name = st.selectbox("Select Student to Bind to Tag:", list(student_options.keys()))
                selected_uuid = student_options[selected_child_name]

                student_tags = (
                    supabase.table("nfc_tags")
                    .select("public_token, status")
                    .eq("student_id", selected_uuid)
                    .execute()
                    .data
                    or []
                )

                selected_tag = None
                if student_tags:
                    tag_labels = [
                        f"{(tag.get('status') or 'unknown').title()} · …{str(tag.get('public_token') or '')[-6:]}"
                        for tag in student_tags
                    ]
                    selected_tag = student_tags[
                        st.selectbox("Existing tag", range(len(student_tags)), format_func=lambda i: tag_labels[i])
                    ]
                    selected_token = selected_tag.get("public_token")
                    selected_status = (selected_tag.get("status") or "").lower()

                    if selected_status in {"active", "enabled"} and selected_token:
                        st.caption("Current tag is active. Its URL opens this student's safety profile.")
                        st.code(build_app_url("tag_token", selected_token))
                        if st.button("🚫 Report this tag lost / terminate it", type="secondary"):
                            try:
                                supabase.table("nfc_tags").update({"status": "lost"}).eq(
                                    "public_token", selected_token
                                ).execute()
                                st.success("Tag terminated. Scans of its current URL will now be refused.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Could not terminate this tag: {e}")
                    else:
                        st.warning("This tag is inactive. Its current NFC URL should be refused by the profile page.")

                    if st.button("🔁 Generate replacement NFC tag link"):
                        replacement_token = secrets.token_urlsafe(32)
                        try:
                            # Insert first so schemas that allow multiple tags keep the old tag's lost record.
                            try:
                                supabase.table("nfc_tags").insert({
                                    "student_id": selected_uuid,
                                    "public_token": replacement_token,
                                    "status": "active",
                                }).execute()
                            except Exception:
                                # Some installations enforce one tag row per student. Re-key that row;
                                # the old physical tag URL then no longer matches any database row.
                                if not selected_token:
                                    raise
                                supabase.table("nfc_tags").update({
                                    "public_token": replacement_token,
                                    "status": "active",
                                }).eq("public_token", selected_token).execute()
                            else:
                                if selected_token:
                                    supabase.table("nfc_tags").update({"status": "lost"}).eq(
                                        "public_token", selected_token
                                    ).execute()

                            st.success("Replacement link created. Write this new link to the replacement NFC tag.")
                            st.code(build_app_url("tag_token", replacement_token))
                        except Exception as e:
                            st.error(f"Could not create a replacement tag: {e}")
                else:
                    st.info("No NFC tag is assigned to this student yet.")
                    if st.button("🔐 Generate first secure NFC tag link"):
                        new_token = secrets.token_urlsafe(32)
                        try:
                            supabase.table("nfc_tags").insert({
                                "student_id": selected_uuid,
                                "public_token": new_token,
                                "status": "active",
                            }).execute()
                            st.success("Secure NFC link created. Write this link to the tag.")
                            st.code(build_app_url("tag_token", new_token))
                        except Exception as e:
                            st.error(f"Could not create an NFC tag: {e}")
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
                    try:
                        guardian_rows = (
                            supabase.table("guardians")
                            .select("*")
                            .eq("student_id", selected_student_id)
                            .execute()
                            .data
                            or []
                        )
                    except Exception as guardian_error:
                        guardian_rows = []
                        st.error(f"Could not load this student's guardians: {guardian_error}")

                    if guardian_rows:
                        guardian_labels = []
                        guardian_keys = []
                        for guardian in guardian_rows:
                            label = str(guardian.get("full_name") or "Guardian")
                            if guardian.get("relationship"):
                                label += f" · {guardian['relationship']}"
                            if guardian.get("phone"):
                                label += f" · {guardian['phone']}"
                            identity = str(guardian.get("id") or guardian.get("phone") or label)
                            guardian_key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
                            guardian_labels.append(f"{label} · {guardian_key[:8]}")
                            guardian_keys.append(guardian_key)

                        guardian_index = st.selectbox(
                            "Choose the parent/guardian for this private portal link",
                            range(len(guardian_rows)),
                            format_func=lambda index: guardian_labels[index],
                            key=f"portal_guardian_{selected_student_id}",
                        )
                        selected_guardian = guardian_rows[guardian_index]
                        selected_guardian_key = guardian_keys[guardian_index]
                        create_col, disable_col = st.columns(2)
                        with create_col:
                            if st.button(
                                "Create / Reset This Guardian’s Link",
                                type="primary",
                                key=f"create_guardian_link_{selected_student_id}_{selected_guardian_key[:8]}",
                            ):
                                raw_token = secrets.token_urlsafe(32)
                                supabase.table("student_parent_portal_links").upsert(
                                    {
                                        "student_id": selected_student_id,
                                        "guardian_key": selected_guardian_key,
                                        "guardian_name": selected_guardian.get("full_name") or "Parent",
                                        "token_hash": token_hash(raw_token),
                                        "enabled": True,
                                    },
                                    on_conflict="student_id,guardian_key",
                                ).execute()
                                st.success("Private link ready for this parent. Resetting it invalidated their previous link.")
                                st.code(
                                    build_app_url(
                                        "share_token",
                                        raw_token,
                                        {
                                            "student_id": str(
                                                student_rows[selected_index].get("student_id") or selected_student_id
                                            )
                                        },
                                    )
                                )
                                st.caption(
                                    "The URL includes this student’s school ID for identification. "
                                    "The private random token in the same URL is required to open the portal."
                                )
                                st.caption(
                                    "Send this URL privately to this guardian. It opens this child’s portal, "
                                    "including opted-in NFC scanner-phone location updates."
                                )
                        with disable_col:
                            if st.button(
                                "Revoke This Guardian’s Link",
                                key=f"revoke_guardian_link_{selected_student_id}_{selected_guardian_key[:8]}",
                            ):
                                supabase.table("student_parent_portal_links").update({"enabled": False}).eq(
                                    "student_id", selected_student_id
                                ).eq("guardian_key", selected_guardian_key).execute()
                                st.success("This guardian’s private portal link has been revoked.")
                    else:
                        st.info("No guardian contacts are saved for this student yet. Add a guardian in Student Directory first.")
            else:
                st.info(
                    "No student records were returned from Supabase. Add students in the Student Directory / Register tab, "
                    "then refresh this page. If students are already registered, check the app's Supabase URL/key and "
                    "the `students` table permissions."
                )

            st.divider()
            st.markdown("#### NFC scanner phone locations")
            st.caption(
                "These pins show phone locations people explicitly shared while scanning a tag. "
                "A point is marked live only while updates are fresh; it is not verified child tracking. "
                "Last known points older than 24 hours are removed."
            )
            scan_retention_cutoff = datetime.now(timezone.utc) - timedelta(
                hours=SCAN_LOCATION_RETENTION_HOURS
            )
            supabase.table("student_tag_scan_locations").delete().lt(
                "captured_at", scan_retention_cutoff.isoformat()
            ).execute()

            @st.fragment(run_every="15s")
            def show_recent_tag_scans():
                rows = (
                    supabase.table("student_tag_scan_locations")
                    .select("student_id, latitude, longitude, accuracy_meters, captured_at, sharing_active")
                    .gte("captured_at", scan_retention_cutoff.isoformat())
                    .execute()
                    .data
                    or []
                )
                if not rows:
                    st.info("No NFC scan locations have been shared in the last 24 hours.")
                    return
                points = []
                detail_rows = []
                for row in rows:
                    points.append(
                        {
                            "student": students_by_uuid.get(str(row["student_id"]), "Student"),
                            "latitude": float(row["latitude"]),
                            "longitude": float(row["longitude"]),
                            "accuracy_meters": round(float(row["accuracy_meters"])),
                        }
                    )
                    captured = datetime.fromisoformat(str(row["captured_at"]).replace("Z", "+00:00"))
                    if captured.tzinfo is None:
                        captured = captured.replace(tzinfo=timezone.utc)
                    age_seconds = (datetime.now(timezone.utc) - captured.astimezone(timezone.utc)).total_seconds()
                    live_now = bool(row.get("sharing_active")) and 0 <= age_seconds <= LOCATION_FRESH_SECONDS
                    detail_rows.append(
                        {
                            "Student": students_by_uuid.get(str(row["student_id"]), "Student"),
                            "Status": "🟢 Live" if live_now else "Last known",
                            "Updated (UTC)": captured.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                            "Coordinates": f"{float(row['latitude']):.6f}, {float(row['longitude']):.6f}",
                            "Accuracy (m)": round(float(row["accuracy_meters"])),
                        }
                    )
                render_location_map(points)
                st.dataframe(pd.DataFrame(detail_rows), use_container_width=True, hide_index=True)

            show_recent_tag_scans()
        except Exception as e:
            st.error(f"Could not load GPS sharing data: {e}")
