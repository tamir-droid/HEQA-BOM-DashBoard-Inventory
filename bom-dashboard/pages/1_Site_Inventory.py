"""Upload Data Files — HEQA."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

from config import (
    DATA_DIR, LOGO_PATH,
    SS_AUTH, SS_CURRENT_USER, SS_IS_ADMIN,
    SS_DATA, SS_RESULTS,
    INV_FILENAME, PRICE_FILENAME, TYPE_FILENAME, COMBINED_BOM_FILENAME, BRD_SUB_INV_FILENAME,
    INV_KEY_COL, INV_QTY_COL,
    PRICE_KEY_COL, PRICE_USD_COL,
    TYPE_KEY_COL, TYPE_COL,
)
from utils.combined_bom_parser import load_combined_bom
from utils.inventory_parser import load_inventory
from utils.price_parser import load_prices
from utils.type_parser import load_types
from utils.bom_parser import load_bom_file

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
    if st.button("🔌 BRD Assembly", use_container_width=True, key="nav_brd"):
        st.switch_page("pages/4_BRD_Assembly.py")
    if st.button("📦 System Inventory", use_container_width=True, key="nav_sys"):
        st.switch_page("pages/2_System_Inventory.py")
    st.button("📤 Upload Files", use_container_width=True, disabled=True)
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
        st.image(LOGO_PATH.read_bytes(), width=180)
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

# BOM files status
st.markdown("#### 📋 BOM Files")
bom_files_on_disk = [p for p in DATA_DIR.glob("*.xlsx")
                     if p.name not in (INV_FILENAME, PRICE_FILENAME, TYPE_FILENAME)] if DATA_DIR.exists() else []
if bom_files_on_disk:
    for bf in sorted(bom_files_on_disk):
        size_kb = bf.stat().st_size / 1024
        if bf.name == COMBINED_BOM_FILENAME:
            st.success(f"✅ `{bf.name}` *(combined)* — {size_kb:,.0f} KB")
        else:
            st.success(f"✅ `{bf.name}` — {size_kb:,.0f} KB")
else:
    st.error("❌ No BOM files uploaded yet — upload them below in section 4️⃣ or 5️⃣")

st.markdown("---")

# ── 🗑️ Delete Files ───────────────────────────────────────────────────────────
st.markdown("### 🗑️ Delete Files")
st.caption("Select one or more files to permanently remove from the data folder.")

_all_files = sorted(DATA_DIR.glob("*.xlsx")) if DATA_DIR.exists() else []
if _all_files:
    _file_options = {p.name: p for p in _all_files}
    _to_delete = st.multiselect(
        "Select files to delete",
        options=list(_file_options.keys()),
        placeholder="Choose file(s)…",
        label_visibility="collapsed",
    )
    if _to_delete:
        st.warning(f"⚠️ This will **permanently delete** {len(_to_delete)} file(s): {', '.join(f'`{f}`' for f in _to_delete)}")
        _del_col, _ = st.columns([1, 5])
        with _del_col:
            if st.button(f"🗑️ Delete {len(_to_delete)} file(s)", type="primary",
                         use_container_width=True, key="do_delete"):
                _deleted, _errors = [], []
                for fname in _to_delete:
                    try:
                        _file_options[fname].unlink()
                        _deleted.append(fname)
                    except Exception as exc:
                        _errors.append(f"`{fname}`: {exc}")
                _invalidate_cache()
                if _deleted:
                    st.success(f"✅ Deleted: {', '.join(f'`{f}`' for f in _deleted)}")
                if _errors:
                    for e in _errors:
                        st.error(f"❌ {e}")
                st.rerun()
else:
    st.info("No files in data folder.")

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
                    DATA_DIR.mkdir(parents=True, exist_ok=True)
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
                    DATA_DIR.mkdir(parents=True, exist_ok=True)
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
                    DATA_DIR.mkdir(parents=True, exist_ok=True)
                    (DATA_DIR / TYPE_FILENAME).write_bytes(file_bytes)
                    _invalidate_cache()
                    st.success(f"✅ `{TYPE_FILENAME}` saved ({len(df_preview):,} rows).")
                    st.rerun()
                except Exception as exc:
                    st.error(f"❌ {exc}")

st.markdown("---")

# ── 4. BOM Files — Individual SYS-*.xlsx ─────────────────────────────────────
st.markdown("### 4️⃣ BOM Files — Individual `SYS-*.xlsx`")
st.caption("Upload one or more BOM Excel files (sheet: **DataSheet**, must have **Level** and **Vendor Part Number** columns). You can upload all at once.")

bom_uploads = st.file_uploader(
    "Choose BOM file(s)",
    type=["xlsx", "xls"],
    accept_multiple_files=True,
    key="bom_upload",
)

if bom_uploads:
    valid_boms = []
    for uf in bom_uploads:
        file_bytes = uf.read()
        df_bom, bom_err = load_bom_file(uf.name, file_bytes)
        if bom_err:
            st.error(f"❌ `{uf.name}`: {bom_err}")
        else:
            st.success(f"✅ `{uf.name}` — {len(df_bom):,} parts parsed")
            valid_boms.append((uf.name, file_bytes))

    if valid_boms:
        st.warning(f"⚠️ This will **save/overwrite** {len(valid_boms)} BOM file(s) in `data/`.")
        save_col, _ = st.columns([1, 5])
        with save_col:
            if st.button("💾 Save BOM Files", type="primary", use_container_width=True, key="save_boms"):
                try:
                    DATA_DIR.mkdir(parents=True, exist_ok=True)
                    for fname, fbytes in valid_boms:
                        (DATA_DIR / fname).write_bytes(fbytes)
                    _invalidate_cache()
                    st.success(f"✅ {len(valid_boms)} BOM file(s) saved. Go to Main Dashboard and press **Calculate**.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"❌ {exc}")

st.markdown("---")

# ── 5. Combined BOM File — ALL_BOMS.xlsx ──────────────────────────────────────
st.markdown(f"### 5️⃣ Combined BOM File — `{COMBINED_BOM_FILENAME}`")
st.caption(
    f"**Alternative to individual SYS-\\*.xlsx files.** "
    f"Upload a single Excel file (sheet: **DataSheet**) that contains all BOMs concatenated, "
    f"with a **`System`** column identifying which system each row belongs to. "
    f"Example System values: `SYS-BR3-LINK`, `SYS-SP1-1310-D`, etc."
)

# Show current status
_combined_path = DATA_DIR / COMBINED_BOM_FILENAME
if _combined_path.exists():
    _sz = _combined_path.stat().st_size / 1024
    st.success(f"✅ `{COMBINED_BOM_FILENAME}` already uploaded — {_sz:,.0f} KB")
else:
    st.info(f"ℹ️ `{COMBINED_BOM_FILENAME}` not found — upload below (or use individual BOM files above).")

combined_upload = st.file_uploader(
    f"Choose {COMBINED_BOM_FILENAME}",
    type=["xlsx", "xls"],
    key="combined_bom_upload",
)

if combined_upload is not None:
    file_bytes = combined_upload.read()
    bom_dict, parse_err = load_combined_bom(combined_upload.name, file_bytes)
    if parse_err:
        st.error(f"❌ Parse error: {parse_err}")
    else:
        _total_rows = sum(len(v) for v in bom_dict.values())
        st.success(
            f"✅ Parsed **{len(bom_dict)}** system(s), **{_total_rows:,}** total rows:"
        )
        for sys_name, sys_df in sorted(bom_dict.items()):
            st.caption(f"  • **{sys_name}** — {len(sys_df):,} parts")

        st.warning(f"⚠️ This will **overwrite** `data/{COMBINED_BOM_FILENAME}`.")
        save_col, _ = st.columns([1, 5])
        with save_col:
            if st.button("💾 Save Combined BOM", type="primary", use_container_width=True, key="save_combined"):
                try:
                    DATA_DIR.mkdir(parents=True, exist_ok=True)
                    (DATA_DIR / COMBINED_BOM_FILENAME).write_bytes(file_bytes)
                    _invalidate_cache()
                    st.success(
                        f"✅ `{COMBINED_BOM_FILENAME}` saved ({len(bom_dict)} systems, "
                        f"{_total_rows:,} rows). Go to Main Dashboard and press **Calculate**."
                    )
                    st.rerun()
                except Exception as exc:
                    st.error(f"❌ {exc}")
