"""BRD Assembly Viewer — HEQA.

Select a BRD assembly and view all its sub-components from the BOM,
including Find Number, Level, Qty, inventory status.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import streamlit as st

from config import (
    DATA_DIR, LOGO_PATH,
    SS_AUTH, SS_IS_ADMIN, SS_CURRENT_USER,
    BOM_LEVEL_COL, BOM_VPN_COL, BOM_QTY_COL, BOM_DESC_COL,
    BOM_MFR_COL, BOM_MPN_COL, BOM_FIND_NUM_COL,
    INV_KEY_COL, INV_QTY_COL, INV_FILENAME,
)
from utils.bom_parser import load_bom_file

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="BRD Assembly — HEQA",
    page_icon="🔌",
    layout="wide",
)

st.markdown(
    "<style>[data-testid=\"stSidebarNav\"] { display: none; }</style>",
    unsafe_allow_html=True,
)

# ── Navigation ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🗂️ Navigation")
    if st.button("🏠 Main Dashboard", use_container_width=True, key="nav_main"):
        st.switch_page("app.py")
    if st.button("📤 Upload Files", use_container_width=True, key="nav_site"):
        st.switch_page("pages/1_Site_Inventory.py")
    if st.button("📦 System Inventory", use_container_width=True, key="nav_inv"):
        st.switch_page("pages/2_System_Inventory.py")
    st.button("🔌 BRD Assembly", use_container_width=True, disabled=True)
    if st.session_state.get(SS_IS_ADMIN):
        if st.button("👥 Users", use_container_width=True, key="nav_users"):
            st.switch_page("pages/3_User_Management.py")
    st.markdown("---")

# ── Auth guard ─────────────────────────────────────────────────────────────────
if not st.session_state.get(SS_AUTH):
    st.warning("🔒 Please log in from the main page first.")
    st.stop()

# ── Header ─────────────────────────────────────────────────────────────────────
if LOGO_PATH.exists():
    logo_col, title_col = st.columns([1, 3])
    with logo_col:
        st.image(LOGO_PATH.read_bytes(), width=180)
    with title_col:
        st.markdown("# 🔌 BRD Assembly Viewer")
        st.caption("Select a BRD assembly to view all sub-components as defined in the BOM hierarchy.")
else:
    st.title("🔌 BRD Assembly Viewer")

# ── Helpers ────────────────────────────────────────────────────────────────────
def _parse_level(val) -> int:
    """Parse mixed-type Level column to integer."""
    try:
        return int(str(val).strip().lstrip("."))
    except (ValueError, TypeError):
        return 999


@st.cache_data(show_spinner=False)
def _load_all_boms() -> dict[str, pd.DataFrame]:
    """Load all BOM files from data/ folder."""
    bom_files = {}
    if not DATA_DIR.exists():
        return bom_files
    for f in DATA_DIR.glob("SYS-*.xlsx"):
        df, err = load_bom_file(f)
        if err is None and df is not None and not df.empty:
            bom_files[f.name] = df
    return bom_files


def _get_brd_assemblies(bom_files: dict) -> dict[str, list[str]]:
    """Return {brd_vpn: [bom_file_name, ...]} for all BRD-prefixed assemblies found in BOMs."""
    result: dict[str, list[str]] = {}
    for bom_name, df in bom_files.items():
        if BOM_VPN_COL not in df.columns:
            continue
        for vpn in df[BOM_VPN_COL].astype(str).str.strip().unique():
            if vpn.upper().startswith("BRD"):
                result.setdefault(vpn, [])
                if bom_name not in result[vpn]:
                    result[vpn].append(bom_name)
    return result


def _get_components(bom_df: pd.DataFrame, brd_vpn: str) -> pd.DataFrame:
    """Extract all rows directly under brd_vpn in the BOM hierarchy."""
    rows = []
    in_brd = False
    brd_level = None

    for _, row in bom_df.iterrows():
        level = _parse_level(row.get(BOM_LEVEL_COL, 999))
        vpn = str(row.get(BOM_VPN_COL, "")).strip()

        if vpn == brd_vpn:
            in_brd = True
            brd_level = level
            continue

        if in_brd:
            if brd_level is not None and level <= brd_level:
                break  # Exited the BRD sub-tree
            rows.append(row)

    return pd.DataFrame(rows) if rows else pd.DataFrame()


def _load_inventory() -> pd.DataFrame:
    """Load Inventory.xlsx for In Stock lookup."""
    inv_path = DATA_DIR / INV_FILENAME
    if not inv_path.exists():
        return pd.DataFrame()
    try:
        return pd.read_excel(inv_path, sheet_name="Sheet1")
    except Exception:
        return pd.DataFrame()


# ── Main ────────────────────────────────────────────────────────────────────────
bom_files = _load_all_boms()

if not bom_files:
    st.warning("⚠️ No BOM files found in the data/ folder. Please upload them via 📤 Upload Files.")
    st.stop()

brd_assemblies = _get_brd_assemblies(bom_files)

if not brd_assemblies:
    st.warning("⚠️ No BRD-prefixed assemblies found in the uploaded BOM files.")
    st.stop()

# ── Selector ───────────────────────────────────────────────────────────────────
sel_col, info_col = st.columns([3, 4])
with sel_col:
    sel_brd = st.selectbox(
        "Select BRD Assembly",
        options=sorted(brd_assemblies.keys()),
        help="Shows all sub-components of the selected BRD assembly.",
    )

# ── Collect components from all BOM files containing this assembly ──────────────
all_components: list[pd.DataFrame] = []
for bom_name in brd_assemblies.get(sel_brd, []):
    df = bom_files[bom_name]
    comp_df = _get_components(df, sel_brd)
    if not comp_df.empty:
        comp_df = comp_df.copy()
        comp_df["BOM File"] = bom_name
        all_components.append(comp_df)

if not all_components:
    st.info(f"No sub-components found under **{sel_brd}** in any BOM file.")
    st.stop()

combined = pd.concat(all_components, ignore_index=True)

# ── Load inventory for In Stock qty ────────────────────────────────────────────
inv_df = _load_inventory()
inv_map: dict[str, float] = {}
if not inv_df.empty and INV_KEY_COL in inv_df.columns and INV_QTY_COL in inv_df.columns:
    for _, r in inv_df.iterrows():
        k = str(r[INV_KEY_COL]).strip()
        v = pd.to_numeric(r[INV_QTY_COL], errors="coerce")
        if k and pd.notna(v):
            inv_map[k] = float(v)

# ── Build display DataFrame ─────────────────────────────────────────────────────
disp_cols = []
for col in [BOM_FIND_NUM_COL, BOM_LEVEL_COL, BOM_VPN_COL, BOM_DESC_COL,
            BOM_MFR_COL, BOM_MPN_COL, BOM_QTY_COL, "BOM File"]:
    if col in combined.columns:
        disp_cols.append(col)

disp = combined[disp_cols].copy()
disp = disp.rename(columns={
    BOM_FIND_NUM_COL: "Find #",
    BOM_LEVEL_COL:    "Level",
    BOM_VPN_COL:      "Heqa P.N",
    BOM_DESC_COL:     "Description",
    BOM_MFR_COL:      "MFR Name",
    BOM_MPN_COL:      "MPN",
    BOM_QTY_COL:      "Qty (BOM)",
})

# Add In Stock column
if "Heqa P.N" in disp.columns:
    disp["In Stock"] = disp["Heqa P.N"].map(lambda v: inv_map.get(str(v).strip(), 0))

# Add status indicator
def _status(row):
    try:
        qty_bom = float(row.get("Qty (BOM)", 0) or 0)
        in_stock = float(row.get("In Stock", 0) or 0)
        if in_stock >= qty_bom:
            return "✅ In Stock"
        elif in_stock > 0:
            return "🟡 Partial"
        else:
            return "🔴 Missing"
    except Exception:
        return "—"

disp["Status"] = disp.apply(_status, axis=1)

# Sort by Find # then Level
disp["Find #"] = pd.to_numeric(disp["Find #"], errors="coerce")
disp = disp.sort_values(["Find #", "Level"], na_position="last").reset_index(drop=True)

# ── Info bar ───────────────────────────────────────────────────────────────────
with info_col:
    _total = len(disp)
    _missing = (disp["Status"] == "🔴 Missing").sum()
    _in_stock = (disp["Status"] == "✅ In Stock").sum()
    _partial = (disp["Status"] == "🟡 Partial").sum()
    _bom_files = ", ".join(brd_assemblies.get(sel_brd, []))
    st.markdown(
        f"**{sel_brd}** → **{_total}** components &nbsp;|&nbsp; "
        f"✅ {_in_stock} &nbsp; 🟡 {_partial} &nbsp; 🔴 {_missing}  \n"
        f"<small>Found in: {_bom_files}</small>",
        unsafe_allow_html=True,
    )

# ── Status filter ──────────────────────────────────────────────────────────────
fc1, fc2 = st.columns([2, 5])
with fc1:
    sel_status = st.selectbox(
        "Filter by Status",
        ["All", "🔴 Missing", "🟡 Partial", "✅ In Stock"],
        label_visibility="collapsed",
    )

if sel_status != "All":
    disp = disp[disp["Status"] == sel_status]

# ── Color coding ───────────────────────────────────────────────────────────────
def _row_color(row):
    s = row.get("Status", "")
    if s == "🔴 Missing":
        color = "#ffd6d6"
    elif s == "🟡 Partial":
        color = "#fff3cd"
    elif s == "✅ In Stock":
        color = "#d4edda"
    else:
        color = "white"
    return [f"background-color: {color}"] * len(row)

# ── Table ──────────────────────────────────────────────────────────────────────
st.dataframe(
    disp.style.apply(_row_color, axis=1),
    use_container_width=True,
    height=min(len(disp) * 35 + 50, 800),
    hide_index=True,
    column_config={
        "Find #":      st.column_config.NumberColumn("Find #", format="%d", width="small"),
        "Level":       st.column_config.TextColumn("Level", width="small"),
        "Heqa P.N":    st.column_config.TextColumn("Heqa P.N"),
        "Description": st.column_config.TextColumn("Description", width="large"),
        "MFR Name":    st.column_config.TextColumn("MFR Name"),
        "MPN":         st.column_config.TextColumn("MPN"),
        "Qty (BOM)":   st.column_config.NumberColumn("Qty (BOM)", format="%g", width="small"),
        "In Stock":    st.column_config.NumberColumn("In Stock", format="%g", width="small"),
        "Status":      st.column_config.TextColumn("Status"),
        "BOM File":    st.column_config.TextColumn("BOM File"),
    },
)

# ── Export ─────────────────────────────────────────────────────────────────────
import datetime
st.download_button(
    "⬇️ Export to CSV",
    data=disp.to_csv(index=False).encode("utf-8-sig"),
    file_name=f"BRD_{sel_brd}_{datetime.date.today()}.csv",
    mime="text/csv",
)
