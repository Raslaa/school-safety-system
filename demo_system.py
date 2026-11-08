import os
import base64
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlencode, urlparse
import pandas as pd
import pydeck as pdk
import streamlit as st
from supabase import create_client, Client

LOCATION_FRESH_SECONDS = 120
LOCATION_RETENTION_HOURS = 24
SCAN_LOCATION_RETENTION_HOURS = 24

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
      show('🟢 Live sharing is on. Keep this page open; fresh browser updates are shared as they arrive.');
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
    }, {enableHighAccuracy:true, maximumAge:10000, timeout:30000});
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


def render_location_map(locations: list[dict], *, key: str) -> None:
    """Render reported GPS coordinates on an interactive, zoomable map."""
    if not locations:
        return
    frame = pd.DataFrame(locations)
    frame["latitude"] = frame["latitude"].astype(float)
    frame["longitude"] = frame["longitude"].astype(float)
    center_lat = float(frame["latitude"].mean())
    center_lon = float(frame["longitude"].mean())
    span = max(
        float(frame["latitude"].max() - frame["latitude"].min()),
        float(frame["longitude"].max() - frame["longitude"].min()),
    )
    zoom = 17 if len(frame) == 1 else (14 if span < 0.01 else 11 if span < 0.1 else 8)
    marker = pdk.Layer(
        "ScatterplotLayer",
        data=frame,
        get_position="[longitude, latitude]",
        get_radius=14,
        radius_units="pixels",
        get_fill_color=[14, 116, 96, 230],
        get_line_color=[255, 255, 255, 255],
        line_width_min_pixels=2,
        stroked=True,
        pickable=True,
        auto_highlight=True,
    )
    deck = pdk.Deck(
        layers=[marker],
        initial_view_state=pdk.ViewState(
            latitude=center_lat,
            longitude=center_lon,
            zoom=zoom,
            pitch=0,
        ),
        map_style=None,
        tooltip={
            "text": (
                "{student}\nLatitude: {latitude}\nLongitude: {longitude}\n"
                "Reported accuracy: ±{accuracy_meters} m"
            )
        },
    )
    st.pydeck_chart(deck, width="stretch", key=key, alt="Interactive map of reported phone locations")


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
            render_location_map(point, key=f"parent_nfc_location_{student_uuid}")
            st.caption(
                f"Reported {captured.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')} · "
                f"GPS coordinates {float(scan['latitude']):.6f}, {float(scan['longitude']):.6f} · "
                f"reported accuracy ±{round(float(scan['accuracy_meters']))} m. "
                "Zoom or pan the map; GPS accuracy depends on the phone."
            )

        show_parent_scan_report()

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
                            st.caption(
                                "Send this link privately to the parent. It allows them to share their phone location "
                                "and view live or last-known opted-in NFC scanner-phone location for this student."
                            )
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
            st.markdown("#### Parent phone locations")
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
                    student_name = students_by_uuid.get(str(row["student_id"]), "Student")
                    points.append(
                        {
                            "student": student_name,
                            "latitude": float(row["latitude"]),
                            "longitude": float(row["longitude"]),
                            "accuracy_meters": round(float(row["accuracy_meters"])),
                        }
                    )
                    captured = datetime.fromisoformat(str(row["captured_at"]).replace("Z", "+00:00"))
                    detail_rows.append(
                        {
                            "Student": students_by_uuid.get(str(row["student_id"]), "Student"),
                            "Updated (UTC)": captured.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                            "Coordinates": f"{float(row['latitude']):.6f}, {float(row['longitude']):.6f}",
                            "Accuracy (m)": round(float(row["accuracy_meters"])),
                        }
                    )
                render_location_map(points, key="admin_parent_locations_map")
                st.dataframe(pd.DataFrame(detail_rows), use_container_width=True, hide_index=True)

            show_recent_locations()

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
                render_location_map(points, key="admin_nfc_locations_map")
                st.dataframe(pd.DataFrame(detail_rows), use_container_width=True, hide_index=True)

            show_recent_tag_scans()
        except Exception as e:
            st.error(f"Could not load GPS sharing data: {e}")
