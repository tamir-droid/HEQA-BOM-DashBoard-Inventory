"""Upload Data Files — HEQA."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

from config import (
    DATA_DIR, LOGO_PATH,
    SS_AUTH, SS_CURRENT_USER, SS_IS_ADMIN,
    SS_DATA, SS_RESULTS,
    INV_FILENAME, PRICE_FILENAME, TYPE_FILENAME,
    INV_KEY_COL, INV_QTY_COL,
    PRICE_KEY_COL, PRICE_USD_COL,
    TYPE_KEY_COL, TYPE_COL,
)
from utils.inventory_parser import load_inventory
from utils.price_parser import load_prices
from utils.type_parser import load_types

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Upload Files — HEQA",
    page_icon="📤",
    layout="wide",
)

st.markdown(
    "<style>[data-testid=\"stSidebarNav\"] { display: none; }</style>",
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown("### 🗂️ Navigation")
    if st.button("🏠 Main Dashboard", use_container_width=True, key="nav_main"):
        st.switch_page("app.py")
    st.button("📤 Upload Files", use_container_width=True, disabled=True)
    if st.button("📦 System Inventory", use_container_width=True, key="nav_sys"):
        st.switch_page("pages/2_System_Inventory.py")
    if st.session_state.get(SS_IS_ADMIN):
        if st.button("👥 Users", use_container_width=True, key="nav_users"):
            st.switch_page("pages/3_User_Management.py")
    st.markdown("---")

# ── Auth guard ────────────────────────────────────────────────────────────────
if not st.session_state.get(SS_AUTH):
    st.warning("🔒 Please log in from the main page first.")
    st.stop()

# ── Header ────────────────────────────────────────────────────────────────────
if LOGO_PATH.exists():
    logo_col, title_col = st.columns([1, 3])
    with logo_col:
        st.image(str(LOGO_PATH), width=180)
    with title_col:
        st.markdown("# 📤 Upload Data Files")
        st.caption(
            "Upload or replace the support files used in procurement calculations. "
            "After uploading, return to the **Main Dashboard** and press **Calculate**."
        )
else:
    st.title("📤 Upload Data Files")
    st.caption("Upload support files for procurement calculations.")


def _invalidate_cache():
    st.cache_data.clear()
    st.session_state.pop(SS_DATA, None)
    st.session_state.pop(SS_RESULTS, None)


def _file_status(filename: str) -> tuple[bool, str]:
    """Return (exists, info_string) for a data file."""
    path = DATA_DIR / filename
    if not path.exists():
        return False, "Not found"
    size_kb = path.stat().st_size / 1024
    return True, f"{size_kb:,.0f} KB"


# ── Current file status ───────────────────────────────────────────────────────
st.markdown("### 📁 Current Files in Data Folder")

files_info = [
    (INV_FILENAME,   "System Inventory",  "מק\"ט + כמות columns"),
    (PRICE_FILENAME, "Item Cost",         "מק\"ט + עלות תקן USD columns"),
    (TYPE_FILENAME,  "Buy & Make (Types)", "מק\"ט + טיפוס P/R/O columns"),
]

cols = st.columns(3)
for col, (fname, label, hint) in zip(cols, files_info):
    exists, info = _file_status(fname)
    with col:
        if exists:
            st.success(f"✅ **{label}**\n\n`{fname}`\n\n{info}")
        else:
            st.error(f"❌ **{label}**\n\n`{fname}`\n\nNot uploaded yet")

st.markdown("---")

# ── Upload sections ───────────────────────────────────────────────────────────

# ── 1. Inventory.xlsx ─────────────────────────────────────────────────────────
st.markdown("### 1️⃣ Inventory File — `Inventory.xlsx`")
st.caption(f"Must contain sheet **Sheet1** with `{INV_KEY_COL}` (Heqa P.N) and `{INV_QTY_COL}` (Qty) columns.")

inv_upload = st.file_uploader(
    "Choose Inventory.xlsx",
    type=["xlsx", "xls"],
    key="inv_upload",
)

if inv_upload is not None:
    file_bytes = inv_upload.read()
    df_preview, parse_err = load_inventory(file_bytes)
    if parse_err:
        st.error(f"❌ Parse error: {parse_err}")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Rows", f"{len(df_preview):,}")
        c2.metric("Parts with stock", f"{int((df_preview[INV_QTY_COL] > 0).sum()):,}")
        c3.metric("Total units", f"{int(df_preview[INV_QTY_COL].sum()):,}")
        st.caption("Preview — first 20 rows:")
        st.dataframe(df_preview.head(20), use_container_width=True, hide_index=True)
        st.warning(f"⚠️ This will **overwrite** `data/{INV_FILENAME}`.")
        save_col, _ = st.columns([1, 5])
        with save_col:
            if st.button("💾 Save Inventory File", type="primary", use_container_width=True, key="save_inv"):
                try:
                    (DATA_DIR / INV_FILENAME).write_bytes(file_bytes)
                    _invalidate_cache()
                    st.success(f"✅ `{INV_FILENAME}` saved ({len(df_preview):,} rows).")
                    st.rerun()
                except Exception as exc:
                    st.error(f"❌ {exc}")

st.markdown("---")

# ── 2. item cost.xlsx ─────────────────────────────────────────────────────────
st.markdown("### 2️⃣ Item Cost File — `item cost.xlsx`")
st.caption(f"Must contain sheet **DataSheet** with `{PRICE_KEY_COL}` and `{PRICE_USD_COL}` columns.")

price_upload = st.file_uploader(
    "Choose item cost.xlsx",
    type=["xlsx", "xls"],
    key="price_upload",
)

if price_upload is not None:
    file_bytes = price_upload.read()
    df_preview, parse_err = load_prices(file_bytes)
    if parse_err:
        st.error(f"❌ Parse error: {parse_err}")
    else:
        priced = int(df_preview[PRICE_USD_COL].notna().sum())
        c1, c2 = st.columns(2)
        c1.metric("Rows", f"{len(df_preview):,}")
        c2.metric("Parts with price", f"{priced:,}")
        st.caption("Preview — first 20 rows:")
        st.dataframe(df_preview.head(20), use_container_width=True, hide_index=True)
        st.warning(f"⚠️ This will **overwrite** `data/{PRICE_FILENAME}`.")
        save_col, _ = st.columns([1, 5])
        with save_col:
            if st.button("💾 Save Cost File", type="primary", use_container_width=True, key="save_price"):
                try:
                    (DATA_DIR / PRICE_FILENAME).write_bytes(file_bytes)
                    _invalidate_cache()
                    st.success(f"✅ `{PRICE_FILENAME}` saved ({len(df_preview):,} rows).")
                    st.rerun()
                except Exception as exc:
                    st.error(f"❌ {exc}")

st.markdown("---")

# ── 3. Buy & Make.xlsx ────────────────────────────────────────────────────────
st.markdown("### 3️⃣ Buy & Make File — `Buy & Make.xlsx`")
st.caption(f"Must contain sheet **DataSheet** with `{TYPE_KEY_COL}` and `{TYPE_COL}` (P/R/O) columns.")

type_upload = st.file_uploader(
    "Choose Buy & Make.xlsx",
    type=["xlsx", "xls"],
    key="type_upload",
)

if type_upload is not None:
    file_bytes = type_upload.read()
    df_preview, parse_err = load_types(file_bytes)
    if parse_err:
        st.error(f"❌ Parse error: {parse_err}")
    else:
        type_counts = df_preview[TYPE_COL].value_counts().to_dict() if TYPE_COL in df_preview.columns else {}
        cols_k = st.columns(len(type_counts) + 1)
        cols_k[0].metric("Total rows", f"{len(df_preview):,}")
        for i, (t, cnt) in enumerate(sorted(type_counts.items()), 1):
            cols_k[i].metric(f"Type {t}", f"{cnt:,}")
        st.caption("Preview — first 20 rows:")
        st.dataframe(df_preview.head(20), use_container_width=True, hide_index=True)
        st.warning(f"⚠️ This will **overwrite** `data/{TYPE_FILENAME}`.")
        save_col, _ = st.columns([1, 5])
        with save_col:
            if st.button("💾 Save Buy & Make File", type="primary", use_container_width=True, key="save_type"):
                try:
                    (DATA_DIR / TYPE_FILENAME).write_bytes(file_bytes)
                    _invalidate_cache()
                    st.success(f"✅ `{TYPE_FILENAME}` saved ({len(df_preview):,} rows).")
                    st.rerun()
                except Exception as exc:
                    st.error(f"❌ {exc}")
