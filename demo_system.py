    import secrets
import streamlit as st
from supabase import create_client, Client

# ------------------------------------------------------------
# PROXIMIND SCHOOL SAFETY HUB
# Public NFC student profile + authenticated admin dashboard
# ------------------------------------------------------------

st.set_page_config(
    page_title="ProxiMind School Safety",
    page_icon="🛡️",
    layout="wide",
)

# Store one Supabase client per Streamlit user session.
# Do NOT use the service_role key in this app.
def get_supabase() -> Client:
    if "supabase_client" not in st.session_state:
        st.session_state.supabase_client = create_client(
            st.secrets["supabase"]["url"],
            st.secrets["supabase"]["anon_key"],
        )
    return st.session_state.supabase_client


try:
    supabase = get_supabase()
except Exception as exc:
    st.error("Could not connect to Supabase. Check your Streamlit secrets.")
    st.code(str(exc))
    st.stop()


def show_student_profile(token: str) -> None:
    """Resolve an NFC token through the restricted Supabase RPC."""
    try:
        response = supabase.rpc(
            "get_public_student_profile",
            {"p_token": token},
        ).execute()
        profile = response.data
    except Exception:
        st.error("We could not verify this NFC tag. Please try again or contact the school.")
        st.stop()

    if not profile or not profile.get("student"):
        st.error("This NFC tag is invalid, inactive, or not assigned to a student.")
        st.stop()

    student = profile["student"]
    guardians = profile.get("guardians") or []

    st.title("🛡️ Student Safety Profile")
    st.caption("ProxiMind School Safety")

    if student.get("photo_url"):
        st.image(student["photo_url"], width=200)

    st.header(student.get("full_name") or "Student")
    st.caption(f"Class / Grade: {student.get('class_name') or 'Not specified'}")

    if student.get("bio"):
        st.write(student["bio"])

    allergies = (student.get("allergies") or "").strip()
    if allergies and allergies.lower() not in {"none", "no known allergies", "n/a"}:
        st.warning(f"⚠️ Known allergies: {allergies}")
    else:
        st.success("No allergies recorded.")

    if student.get("safety_notes"):
        st.info(f"📌 Important safety notes: {student['safety_notes']}")

    st.subheader("📞 Emergency Contacts")
    if not guardians:
        st.warning("No guardian contacts have been registered.")
    else:
        for guardian in guardians:
            name = guardian.get("full_name") or "Guardian"
            relationship = guardian.get("relationship")
            phone = guardian.get("phone") or ""
            primary = "⭐ PRIMARY GUARDIAN — " if guardian.get("is_primary") else ""
            relation_text = f" ({relationship})" if relationship else ""

            st.markdown(f"**{primary}{name}{relation_text}**")
            if phone:
                # Keep the phone value as entered, but remove spaces for the tel link.
                clean_phone = "".join(phone.split())
                st.markdown(
                    f'<a href="tel:{clean_phone}" '
                    'style="display:inline-block;max-width:320px;width:100%;'
                    'text-align:center;padding:12px 8px;margin:4px 0 14px;'
                    'background:#20a464;color:white;border-radius:8px;'
                    'text-decoration:none;font-weight:700;">'
                    f'📞 CALL {name.upper()}</a>',
                    unsafe_allow_html=True,
                )

    st.divider()
    st.caption("If this is an emergency, contact the school or local emergency services.")


def is_admin(user_id: str) -> dict | None:
    """Confirm that the signed-in Supabase user is listed in admin_users."""
    result = (
        supabase.table("admin_users")
        .select("user_id, full_name, role")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def login_screen() -> None:
    st.title("🛡️ ProxiMind Safety Hub")
    st.subheader("Administrator sign in")
    st.write("Sign in with the administrator account created in Supabase Authentication.")

    with st.form("admin_login_form"):
        email = st.text_input("Email address")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in", use_container_width=True)

    if submitted:
        if not email.strip() or not password:
            st.error("Enter both your email address and password.")
            return
        try:
            auth_response = supabase.auth.sign_in_with_password(
                {"email": email.strip(), "password": password}
            )
            user = auth_response.user
            if not user:
                st.error("Sign-in did not return a user account.")
                return

            admin_record = is_admin(user.id)
            if not admin_record:
                supabase.auth.sign_out()
                st.error("This account is not registered as a ProxiMind administrator.")
                return

            st.session_state.admin_user_id = user.id
            st.session_state.admin_name = admin_record.get("full_name") or email
            st.session_state.admin_role = admin_record.get("role") or "admin"
            st.rerun()
        except Exception as exc:
            st.error("Sign-in failed. Check your email and password.")
            st.caption(str(exc))


def admin_dashboard() -> None:
    admin_name = st.session_state.get("admin_name", "Administrator")

    with st.sidebar:
        st.title("🛡️ ProxiMind")
        st.write(f"Signed in as **{admin_name}**")
        st.caption(f"Role: {st.session_state.get('admin_role', 'admin')}")
        if st.button("Sign out", use_container_width=True):
            try:
                supabase.auth.sign_out()
            finally:
                for key in ("admin_user_id", "admin_name", "admin_role"):
                    st.session_state.pop(key, None)
                st.rerun()

    st.title("Administrative Dashboard")
    st.caption("Manage student records and NFC safety tags.")

    directory_tab, register_tab, tags_tab = st.tabs(
        ["📋 Student Directory", "➕ Register Student", "🔗 NFC Tags"]
    )

    # --------------------------------------------------------
    # STUDENT DIRECTORY
    # --------------------------------------------------------
    with directory_tab:
        st.subheader("Student Directory")
        search = st.text_input("Search by student name or school ID", key="student_search")

        try:
            response = (
                supabase.table("students")
                .select("id, student_id, full_name, class_name, allergies")
                .order("full_name")
                .execute()
            )
            students = response.data or []

            if search.strip():
                needle = search.strip().lower()
                students = [
                    item for item in students
                    if needle in (item.get("full_name") or "").lower()
                    or needle in (item.get("student_id") or "").lower()
                ]

            if students:
                st.dataframe(
                    [
                        {
                            "School ID": item.get("student_id"),
                            "Student name": item.get("full_name"),
                            "Class / Grade": item.get("class_name"),
                            "Allergies": item.get("allergies"),
                        }
                        for item in students
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
                st.caption(f"{len(students)} student record(s) shown.")
            else:
                st.info("No matching student records found.")
        except Exception as exc:
            st.error("Could not load students. Check your admin access and RLS policies.")
            st.code(str(exc))

    # --------------------------------------------------------
    # REGISTER STUDENT + PRIMARY GUARDIAN
    # --------------------------------------------------------
    with register_tab:
        st.subheader("Register a Student")

        with st.form("register_student_form", clear_on_submit=True):
            school_id = st.text_input("School registration ID *", placeholder="e.g. AUS-2026-001")
            full_name = st.text_input("Student full name *")
            class_name = st.text_input("Class / Grade")
            photo_url = st.text_input("Student photo URL (optional)")
            allergies = st.text_input("Known allergies", value="None")
            safety_notes = st.text_area("Important safety notes")
            bio = st.text_area("Short student profile (optional)")

            st.divider()
            st.markdown("**Primary guardian contact**")
            guardian_name = st.text_input("Guardian full name *")
            relationship = st.text_input("Relationship to student")
            guardian_phone = st.text_input("Guardian phone number *", placeholder="+252...")

            submitted = st.form_submit_button(
                "Save student record",
                use_container_width=True,
            )

        if submitted:
            if not school_id.strip() or not full_name.strip():
                st.error("School registration ID and student name are required.")
            elif not guardian_name.strip() or not guardian_phone.strip():
                st.error("Guardian name and phone number are required.")
            else:
                try:
                    student_payload = {
                        "student_id": school_id.strip(),
                        "full_name": full_name.strip(),
                        "class_name": class_name.strip(),
                        "photo_url": photo_url.strip() or None,
                        "allergies": allergies.strip() or "None",
                        "safety_notes": safety_notes.strip() or None,
                        "bio": bio.strip() or None,
                    }
                    student_response = (
                        supabase.table("students")
                        .insert(student_payload)
                        .execute()
                    )
                    new_student = student_response.data[0]

                    guardian_payload = {
                        "student_id": new_student["id"],
                        "full_name": guardian_name.strip(),
                        "relationship": relationship.strip() or None,
                        "phone": guardian_phone.strip(),
                        "is_primary": True,
                    }
                    supabase.table("guardians").insert(guardian_payload).execute()

                    st.success(
                        f"Student **{full_name.strip()}** was registered successfully."
                    )
                    st.info("Next, open the NFC Tags tab to assign a tag.")
                except Exception as exc:
                    st.error("The record could not be saved. Check required fields and database policies.")
                    st.code(str(exc))
                    st.warning(
                        "If the student was created but the guardian was not, "
                        "check the Student Directory before trying again to avoid a duplicate student ID."
                    )

    # --------------------------------------------------------
    # NFC TAG ASSIGNMENT
    # --------------------------------------------------------
    with tags_tab:
        st.subheader("Assign an NFC Tag")
        try:
            student_response = (
                supabase.table("students")
                .select("id, student_id, full_name")
                .order("full_name")
                .execute()
            )
            students = student_response.data or []

            if not students:
                st.info("Register a student before assigning an NFC tag.")
            else:
                options = {
                    f"{item['full_name']} — {item['student_id']}": item["id"]
                    for item in students
                }
                selected_label = st.selectbox("Choose a student", list(options.keys()))
                selected_student_uuid = options[selected_label]

                if st.button("Generate / Replace NFC tag link", type="primary"):
                    new_token = secrets.token_hex(32)

                    existing_response = (
                        supabase.table("nfc_tags")
                        .select("id")
                        .eq("student_id", selected_student_uuid)
                        .limit(1)
                        .execute()
                    )

                    if existing_response.data:
                        (
                            supabase.table("nfc_tags")
                            .update({
                                "public_token": new_token,
                                "status": "active",
                            })
                            .eq("student_id", selected_student_uuid)
                            .execute()
                        )
                    else:
                        supabase.table("nfc_tags").insert({
                            "student_id": selected_student_uuid,
                            "public_token": new_token,
                            "status": "active",
                        }).execute()

                    st.session_state["new_nfc_token"] = new_token
                    st.session_state["new_nfc_student"] = selected_label

                if st.session_state.get("new_nfc_token"):
                    try:
                        app_url = st.secrets["app"]["url"].rstrip("/")
                        token = st.session_state["new_nfc_token"]
                        nfc_url = f"{app_url}/?tag_token={token}"

                        st.success(
                            f"NFC link created for {st.session_state.get('new_nfc_student', 'the selected student')}."
                        )
                        st.write("Copy this complete URL into the NFC tag:")
                        st.code(nfc_url, language="text")
                        st.link_button("Test student profile", nfc_url)
                        st.warning(
                            "Generating a replacement link invalidates the previous token. "
                            "Write this new link to the physical NFC tag."
                        )
                    except Exception:
                        st.error(
                            "Add your deployed Streamlit URL to .streamlit/secrets.toml "
                            "under [app] url before generating NFC links."
                        )

        except Exception as exc:
            st.error("Could not load or update NFC tags. Check your admin access and RLS policies.")
            st.code(str(exc))


# ------------------------------------------------------------
# APP ROUTING
# ------------------------------------------------------------

# If the URL contains an NFC token, show only that student's
# approved public profile. Do not show the admin dashboard.
nfc_token = st.query_params.get("tag_token")

if nfc_token:
    show_student_profile(nfc_token)
    st.stop()

# No NFC token: show the protected admin area.
if not st.session_state.get("admin_user_id"):
    login_screen()
else:
    try:
        # Re-check admin membership on each app run.
        current_admin = is_admin(st.session_state["admin_user_id"])
        if not current_admin:
            st.session_state.pop("admin_user_id", None)
            st.session_state.pop("admin_name", None)
            st.session_state.pop("admin_role", None)
            st.error("Your administrator access is no longer active. Please sign in again.")
            st.stop()
        admin_dashboard()
    except Exception as exc:
        st.error("Could not verify administrator access. Please sign in again.")
        st.code(str(exc))

