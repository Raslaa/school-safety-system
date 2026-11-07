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
