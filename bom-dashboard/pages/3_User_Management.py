"""User Management — HEQA. Admin only."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

from config import (
    LOGO_PATH,
    SS_AUTH, SS_CURRENT_USER, SS_IS_ADMIN,
)
from utils.user_store import read_users, write_users

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="User Management — HEQA",
    page_icon="👥",
    layout="centered",
)

st.markdown(
    "<style>[data-testid=\"stSidebarNav\"] { display: none; }</style>",
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown("### 🗂️ Navigation")
    if st.button("🏠 Main Dashboard", use_container_width=True, key="nav_main"):
        st.switch_page("app.py")
    if st.button("📤 Upload Files", use_container_width=True, key="nav_site"):
        st.switch_page("pages/1_Site_Inventory.py")
    if st.button("📦 System Inventory", use_container_width=True, key="nav_sys"):
        st.switch_page("pages/2_System_Inventory.py")
    if st.button("🔌 BRD Assembly", use_container_width=True, key="nav_brd"):
        st.switch_page("pages/4_BRD_Assembly.py")
    st.button("👥 Users", use_container_width=True, disabled=True)
    st.markdown("---")

# ── Auth guard ────────────────────────────────────────────────────────────────
if not st.session_state.get(SS_AUTH):
    st.warning("🔒 Please log in from the main page first.")
    st.stop()

if not st.session_state.get(SS_IS_ADMIN):
    st.error("🚫 Access denied — admins only.")
    st.stop()

# ── Helpers ───────────────────────────────────────────────────────────────────
# read_users / write_users imported from utils.user_store


# ── Header ────────────────────────────────────────────────────────────────────
if LOGO_PATH.exists():
    logo_col, title_col = st.columns([1, 3])
    with logo_col:
        st.image(LOGO_PATH.read_bytes(), width=140)
    with title_col:
        st.markdown("# 👥 User Management")
        st.caption("Add, delete, or manage users. Admin access only.")
else:
    st.title("👥 User Management")

current_user = st.session_state.get(SS_CURRENT_USER, "")

# ── Load users ────────────────────────────────────────────────────────────────
users = read_users()

if not users:
    st.error("No users found. Add [users.USERNAME] blocks to Streamlit Cloud Secrets.")
    st.stop()

# ── Current users table ───────────────────────────────────────────────────────
st.markdown("### 📋 Current Users")

import pandas as pd

rows = []
for uname, udata in users.items():
    rows.append({
        "Delete": False,
        "Username": uname,
        "Role": udata.get("role", "user"),
        "Must Change Password": bool(udata.get("must_change_password", False)),
        "You": "← you" if uname == current_user else "",
    })

users_df = pd.DataFrame(rows)

edited_users = st.data_editor(
    users_df,
    column_config={
        "Delete":               st.column_config.CheckboxColumn("🗑️ Delete", help="Check to delete this user"),
        "Username":             st.column_config.TextColumn("Username", disabled=True),
        "Role":                 st.column_config.SelectboxColumn("Role", options=["user", "admin"]),
        "Must Change Password": st.column_config.CheckboxColumn("Force PW Reset"),
        "You":                  st.column_config.TextColumn("", disabled=True, width="small"),
    },
    disabled=["Username", "You"],
    hide_index=True,
    use_container_width=True,
    key="users_table",
)

# ── Action buttons ─────────────────────────────────────────────────────────────
btn_save, btn_del, _ = st.columns([1, 1, 3])

with btn_save:
    if st.button("💾 Save Role Changes", use_container_width=True, type="primary"):
        updated = dict(users)
        for _, row in edited_users.iterrows():
            uname = row["Username"]
            if uname in updated:
                updated[uname] = dict(updated[uname])
                updated[uname]["role"] = row["Role"]
                updated[uname]["must_change_password"] = bool(row["Must Change Password"])
        write_users(updated)
        st.success("✅ Saved. Changes take effect on next login.")
        st.rerun()

with btn_del:
    to_delete = edited_users.loc[edited_users["Delete"] == True, "Username"].tolist()
    # Protect: cannot delete yourself
    if current_user in to_delete:
        to_delete = [u for u in to_delete if u != current_user]
    # Protect: must keep at least one admin
    remaining_admins = [
        u for u in users
        if u not in to_delete and users[u].get("role", "user") == "admin"
    ]

    lbl = f"🗑️ Delete ({len(to_delete)})" if to_delete else "🗑️ Delete Selected"
    if st.button(lbl, use_container_width=True, disabled=len(to_delete) == 0):
        if not remaining_admins:
            st.error("❌ Cannot delete — there must be at least one admin remaining.")
        elif current_user in [u for u in edited_users.loc[edited_users["Delete"] == True, "Username"]]:
            st.error("❌ You cannot delete your own account.")
        else:
            updated = {u: d for u, d in users.items() if u not in to_delete}
            write_users(updated)
            st.success(f"✅ Deleted: {', '.join(to_delete)}. Changes take effect on next login.")
            st.rerun()

if current_user in edited_users.loc[edited_users["Delete"] == True, "Username"].tolist():
    st.warning("⚠️ You cannot delete your own account.")

st.markdown("---")

# ── Add new user ──────────────────────────────────────────────────────────────
st.markdown("### ➕ Add New User")

with st.form("add_user_form", clear_on_submit=True):
    c1, c2, c3 = st.columns([2, 2, 1])
    with c1:
        new_username = st.text_input("Username *", placeholder="e.g. john")
    with c2:
        new_password = st.text_input("Password *", type="password", placeholder="min 6 chars")
    with c3:
        new_role = st.selectbox("Role", options=["user", "admin"])

    force_reset = st.checkbox("Force password reset on first login", value=True)
    add_btn = st.form_submit_button("➕ Add User", use_container_width=True)

if add_btn:
    uname = new_username.strip().lower()
    if not uname:
        st.error("Username is required.")
    elif len(new_password) < 6:
        st.error("Password must be at least 6 characters.")
    elif uname in users:
        st.error(f"❌ Username `{uname}` already exists.")
    else:
        updated = dict(users)
        updated[uname] = {
            "password": new_password,
            "role": new_role,
            "must_change_password": force_reset,
        }
        write_users(updated)
        st.success(f"✅ User **{uname}** added with role **{new_role}**.")
        st.rerun()

st.markdown("---")

# ── Reset password ─────────────────────────────────────────────────────────────
st.markdown("### 🔑 Reset a User's Password")

with st.form("reset_pw_form", clear_on_submit=True):
    reset_user = st.selectbox("User", options=list(users.keys()))
    new_pw = st.text_input("New Password *", type="password", placeholder="min 6 chars")
    force = st.checkbox("Force password reset on next login", value=True)
    reset_btn = st.form_submit_button("🔑 Reset Password", use_container_width=True)

if reset_btn:
    if len(new_pw) < 6:
        st.error("Password must be at least 6 characters.")
    else:
        updated = dict(users)
        updated[reset_user] = dict(updated[reset_user])
        updated[reset_user]["password"] = new_pw
        updated[reset_user]["must_change_password"] = force
        write_users(updated)
        st.success(f"✅ Password reset for **{reset_user}**.")
        st.rerun()
