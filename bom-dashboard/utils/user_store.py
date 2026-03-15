"""User store — reads/writes users from data/users.json.

On first run (no users.json), seeds from st.secrets so existing
secrets.toml / Streamlit Cloud secrets work out of the box.
"""

import json
import streamlit as st
from pathlib import Path


def _json_path() -> Path:
    from config import DATA_DIR
    return DATA_DIR / "users.json"


def read_users() -> dict:
    """Return users dict. Checks data/users.json first, seeds from st.secrets if absent."""
    path = _json_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Seed from st.secrets (works both locally and on Streamlit Cloud)
    try:
        if "users" in st.secrets:
            users = {}
            for uname, udata in st.secrets["users"].items():
                users[uname] = {
                    "password":            str(udata.get("password", "")),
                    "role":                str(udata.get("role", "user")),
                    "must_change_password": bool(udata.get("must_change_password", False)),
                }
            # Persist so future reads use JSON
            write_users(users)
            return users
    except Exception:
        pass

    return {}


def write_users(users_dict: dict):
    """Persist users to data/users.json."""
    from config import DATA_DIR
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _json_path().write_text(
        json.dumps(users_dict, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
