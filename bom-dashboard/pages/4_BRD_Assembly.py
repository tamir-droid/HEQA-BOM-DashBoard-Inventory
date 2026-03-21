"""BRD Assembly Viewer — HEQA.

Select a BRD assembly and view all its sub-components from the BOM,
including Find Number, Level, Qty, cost, inventory status and subcontractor stock.
Filters (Part Type / Status / Search) and cost metrics mirror the Main Dashboard.
"""

import datetime
import io
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
    INV_FILENAME, INV_KEY_COL, INV_QTY_COL,
    PRICE_FILENAME, PRICE_KEY_COL, PRICE_USD_COL,
    TYPE_FILENAME, TYPE_KEY_COL, TYPE_COL,
    COMBINED_BOM_FILENAME, BRD_SUB_INV_FILENAME, SUPPORT_FILES,
)
from utils.bom_parser import load_bom_file
from utils.combined_bom_parser import load_combined_bom
from utils.price_parser import load_prices
from utils.type_parser import load_types

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

    # ── Subcontractor Inventory Upload ────────────────────────────────────────
    st.markdown("### 🏭 Subcontractor Stock")
    _sub_path = DATA_DIR / BRD_SUB_INV_FILENAME

    if _sub_path.exists():
        _sz = _sub_path.stat().st_size / 1024
        st.success(f"✅ Loaded ({_sz:,.0f} KB)")
        if st.button("🗑️ Remove Sub Inv", use_container_width=True, key="del_sub_inv"):
            try:
                _sub_path.unlink()
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.error(str(e))
    else:
        st.info("No subcontractor inventory uploaded.")

    st.caption(
        f"Upload an Excel file with columns:\n"
        f"**`{INV_KEY_COL}`** (Heqa P.N) and **`{INV_QTY_COL}`** (Qty)\n"
        f"— same format as main Inventory.xlsx"
    )

    _sub_upload = st.file_uploader(
        "Upload Subcontractor Inventory",
        type=["xlsx", "xls"],
        key="sub_inv_upload",
        label_visibility="collapsed",
    )

    if _sub_upload is not None:
        _sub_bytes = _sub_upload.read()
        try:
            try:
                _sub_preview = pd.read_excel(io.BytesIO(_sub_bytes), sheet_name="Sheet1")
            except Exception:
                _sub_preview = pd.read_excel(io.BytesIO(_sub_bytes))
            _sub_preview.columns = _sub_preview.columns.str.strip()

            _key_col = _qty_col = None
            for c in _sub_preview.columns:
                cs = str(c).strip()
                if cs == INV_KEY_COL or cs.lower() in ("heqa p.n", "vendor part number", 'מק"ט'):
                    _key_col = c
                if cs == INV_QTY_COL or cs.lower() in ("qty", "quantity", "כמות"):
                    _qty_col = c
            if _key_col is None and len(_sub_preview.columns) >= 1:
                _key_col = _sub_preview.columns[0]
            if _qty_col is None and len(_sub_preview.columns) >= 2:
                _qty_col = _sub_preview.columns[1]

            if _key_col and _qty_col:
                _sub_rows = int(
                    (_sub_preview[_qty_col].apply(pd.to_numeric, errors="coerce") > 0).sum()
                )
                st.success(f"✅ {len(_sub_preview):,} rows, {_sub_rows:,} with stock")
                if st.button("💾 Save Sub Inv", type="primary",
                             use_container_width=True, key="save_sub_inv"):
                    DATA_DIR.mkdir(parents=True, exist_ok=True)
                    _sub_path.write_bytes(_sub_bytes)
                    st.cache_data.clear()
                    st.success("✅ Saved!")
                    st.rerun()
            else:
                st.error("❌ Cannot detect P/N and Qty columns.")
        except Exception as exc:
            st.error(f"❌ {exc}")

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
    """Parse mixed-type Level column to integer.

    Handles plain ints, pandas float reads (2.0→2), and '.....8' strings.
    """
    try:
        s = str(val).strip().lstrip(".")
        return int(float(s))
    except (ValueError, TypeError):
        return 999


@st.cache_data(show_spinner=False)
def _load_all_boms() -> dict[str, pd.DataFrame]:
    """Load all BOM files — individual SYS-*.xlsx and/or combined ALL_BOMS.xlsx."""
    bom_files: dict[str, pd.DataFrame] = {}
    if not DATA_DIR.exists():
        return bom_files

    combined_path = DATA_DIR / COMBINED_BOM_FILENAME
    if combined_path.exists():
        try:
            bom_dict, err = load_combined_bom(COMBINED_BOM_FILENAME, combined_path.read_bytes())
            if err is None and bom_dict:
                bom_files.update(bom_dict)
        except Exception:
            pass

    for f in DATA_DIR.glob("*.xlsx"):
        if f.name in SUPPORT_FILES:
            continue
        try:
            df, err = load_bom_file(f.name, f.read_bytes())
            if err is None and df is not None and not df.empty:
                bom_files[f.name] = df
        except Exception:
            continue

    return bom_files


@st.cache_data(show_spinner=False)
def _load_price_map() -> dict[str, float]:
    """Return {vpn: unit_price_usd} from item cost.xlsx."""
    p = DATA_DIR / PRICE_FILENAME
    if not p.exists():
        return {}
    try:
        df, err = load_prices(p.read_bytes())
        if err or df.empty:
            return {}
        result: dict[str, float] = {}
        for _, r in df.iterrows():
            k = str(r[PRICE_KEY_COL]).strip()
            v = pd.to_numeric(r.get(PRICE_USD_COL), errors="coerce")
            if k and k.lower() != "nan" and pd.notna(v) and v > 0:
                result[k] = float(v)
        return result
    except Exception:
        return {}


@st.cache_data(show_spinner=False)
def _load_type_map() -> dict[str, str]:
    """Return {vpn: type (P/R/O)} from Buy & Make.xlsx."""
    p = DATA_DIR / TYPE_FILENAME
    if not p.exists():
        return {}
    try:
        df, err = load_types(p.read_bytes())
        if err or df.empty:
            return {}
        result: dict[str, str] = {}
        for _, r in df.iterrows():
            k = str(r[TYPE_KEY_COL]).strip()
            t = str(r.get(TYPE_COL, "")).strip()
            if k and k.lower() != "nan":
                result[k] = t
        return result
    except Exception:
        return {}


def _get_brd_assemblies(bom_files: dict) -> dict[str, list[str]]:
    """Return {brd_vpn: [bom_key, ...]} for all BRD-prefixed assemblies."""
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
            if not vpn or vpn.lower() == "nan":
                continue
            if brd_level is not None and level <= brd_level:
                break
            rows.append(row)

    return pd.DataFrame(rows) if rows else pd.DataFrame()


@st.cache_data(show_spinner=False)
def _load_inventory() -> pd.DataFrame:
    inv_path = DATA_DIR / INV_FILENAME
    if not inv_path.exists():
        return pd.DataFrame()
    try:
        return pd.read_excel(inv_path, sheet_name="Sheet1")
    except Exception:
        return pd.DataFrame()


@st.cache_data(show_spinner=False)
def _load_sub_inventory() -> dict[str, float]:
    sub_path = DATA_DIR / BRD_SUB_INV_FILENAME
    if not sub_path.exists():
        return {}
    try:
        try:
            df = pd.read_excel(sub_path, sheet_name="Sheet1")
        except Exception:
            df = pd.read_excel(sub_path)
        df.columns = df.columns.str.strip()

        key_col = qty_col = None
        for c in df.columns:
            cs = str(c).strip()
            if cs == INV_KEY_COL or cs.lower() in ("heqa p.n", "vendor part number", 'מק"ט'):
                key_col = c
            if cs == INV_QTY_COL or cs.lower() in ("qty", "quantity", "כמות"):
                qty_col = c
        if key_col is None and len(df.columns) >= 1:
            key_col = df.columns[0]
        if qty_col is None and len(df.columns) >= 2:
            qty_col = df.columns[1]
        if key_col is None or qty_col is None:
            return {}

        result: dict[str, float] = {}
        for _, r in df.iterrows():
            k = str(r[key_col]).strip()
            v = pd.to_numeric(r[qty_col], errors="coerce")
            if k and k.lower() != "nan" and pd.notna(v):
                result[k] = float(v)
        return result
    except Exception:
        return {}


# ── Main ────────────────────────────────────────────────────────────────────────
bom_files = _load_all_boms()

if not bom_files:
    st.warning("⚠️ No BOM files found. Please upload via 📤 Upload Files.")
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

# ── Collect components ─────────────────────────────────────────────────────────
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

# ── Load lookup maps ────────────────────────────────────────────────────────────
inv_df = _load_inventory()
inv_map: dict[str, float] = {}
if not inv_df.empty and INV_KEY_COL in inv_df.columns and INV_QTY_COL in inv_df.columns:
    for _, r in inv_df.iterrows():
        k = str(r[INV_KEY_COL]).strip()
        v = pd.to_numeric(r[INV_QTY_COL], errors="coerce")
        if k and k.lower() != "nan" and pd.notna(v):
            inv_map[k] = float(v)

sub_inv_map: dict[str, float] = _load_sub_inventory()
has_sub_inv = bool(sub_inv_map)

price_map: dict[str, float] = _load_price_map()
type_map: dict[str, str]  = _load_type_map()

# ── Build display DataFrame ─────────────────────────────────────────────────────
disp_cols = []
for col in [BOM_FIND_NUM_COL, BOM_LEVEL_COL, BOM_VPN_COL, BOM_DESC_COL,
            BOM_MFR_COL, BOM_MPN_COL, BOM_QTY_COL]:
    if col in combined.columns:
        disp_cols.append(col)

disp = combined[disp_cols].copy()
disp = disp.drop_duplicates(subset=[BOM_VPN_COL])
disp = disp.rename(columns={
    BOM_FIND_NUM_COL: "Find #",
    BOM_LEVEL_COL:    "Level",
    BOM_VPN_COL:      "Heqa P.N",
    BOM_DESC_COL:     "Description",
    BOM_MFR_COL:      "MFR Name",
    BOM_MPN_COL:      "MPN",
    BOM_QTY_COL:      "Qty (BOM)",
})

# ── Enrich with lookups ────────────────────────────────────────────────────────
if "Heqa P.N" in disp.columns:
    disp["In Stock"]   = disp["Heqa P.N"].map(lambda v: inv_map.get(str(v).strip(), 0))
    disp["Unit Price $"] = disp["Heqa P.N"].map(lambda v: price_map.get(str(v).strip()))
    disp["Part Type"]  = disp["Heqa P.N"].map(lambda v: type_map.get(str(v).strip(), "—"))
    if has_sub_inv:
        disp["Sub Stock"] = disp["Heqa P.N"].map(lambda v: sub_inv_map.get(str(v).strip(), 0))

# Total BOM cost per line
disp["Qty (BOM)"] = pd.to_numeric(disp["Qty (BOM)"], errors="coerce").fillna(0)
disp["Total Cost $"] = disp["Unit Price $"] * disp["Qty (BOM)"]


# ── Status ─────────────────────────────────────────────────────────────────────
def _status(row):
    try:
        qty_bom  = float(row.get("Qty (BOM)", 0) or 0)
        in_stock = float(row.get("In Stock",  0) or 0)
        sub_stk  = float(row.get("Sub Stock", 0) or 0) if has_sub_inv else 0.0
        total    = in_stock + sub_stk
        if total >= qty_bom:
            return "✅ In Stock"
        elif total > 0:
            return "🟡 Partial"
        else:
            return "🔴 Missing"
    except Exception:
        return "—"

disp["Status"] = disp.apply(_status, axis=1)

# ── Sort ───────────────────────────────────────────────────────────────────────
disp["Find #"] = pd.to_numeric(disp["Find #"], errors="coerce")
disp = disp.sort_values(["Find #", "Level"], na_position="last").reset_index(drop=True)

# ── Info bar ───────────────────────────────────────────────────────────────────
with info_col:
    _total    = len(disp)
    _missing  = (disp["Status"] == "🔴 Missing").sum()
    _in_stock = (disp["Status"] == "✅ In Stock").sum()
    _partial  = (disp["Status"] == "🟡 Partial").sum()
    _bom_files = ", ".join(brd_assemblies.get(sel_brd, []))
    _sub_note  = f" &nbsp;|&nbsp; 🏭 Sub Inv: **{len(sub_inv_map):,}** parts" if has_sub_inv else ""
    st.markdown(
        f"**{sel_brd}** → **{_total}** components &nbsp;|&nbsp; "
        f"✅ {_in_stock} &nbsp; 🟡 {_partial} &nbsp; 🔴 {_missing}{_sub_note}  \n"
        f"<small>Found in: {_bom_files}</small>",
        unsafe_allow_html=True,
    )

st.markdown("---")

# ── Filters — mirror Main Dashboard ───────────────────────────────────────────
st.markdown("### 🔍 Filters")
_f1, _f2, _f3 = st.columns([2, 2, 3])

# Part Type filter
_all_types = sorted(disp["Part Type"].dropna().unique().tolist()) if "Part Type" in disp.columns else []
_type_options = ["All"] + _all_types
with _f1:
    st.caption("Part Type")
    _default_type = "R" if "R" in _all_types else "All"
    _type_idx = _type_options.index(_default_type) if _default_type in _type_options else 0
    sel_type = st.selectbox(
        "Part Type", _type_options,
        index=_type_idx,
        label_visibility="collapsed",
        key="brd_type_filter",
    )

# Status filter
with _f2:
    st.caption("Status")
    sel_status = st.selectbox(
        "Status",
        ["All", "🔴 Missing", "🟡 Partial", "✅ In Stock"],
        index=1,   # default = Missing
        label_visibility="collapsed",
        key="brd_status_filter",
    )

# Search
with _f3:
    st.caption("🔍 Search (VPN / Description / Manufacturer)")
    search_q = st.text_input(
        "Search", placeholder="Type P/N, description or MFR…",
        label_visibility="collapsed",
        key="brd_search",
    )

# Apply filters
filt = disp.copy()
if sel_type != "All":
    filt = filt[filt["Part Type"] == sel_type]
if sel_status != "All":
    filt = filt[filt["Status"] == sel_status]
if search_q:
    q = search_q.strip().lower()
    mask = (
        filt["Heqa P.N"].astype(str).str.lower().str.contains(q, na=False)
        | filt["Description"].astype(str).str.lower().str.contains(q, na=False)
        | filt["MFR Name"].astype(str).str.lower().str.contains(q, na=False)
        | filt["MPN"].astype(str).str.lower().str.contains(q, na=False)
    )
    filt = filt[mask]

# ── Cost metrics ───────────────────────────────────────────────────────────────
_order_cost = filt.loc[
    filt["Status"].isin(["🔴 Missing", "🟡 Partial"]), "Total Cost $"
].sum(skipna=True)
_total_bom_cost = filt["Total Cost $"].sum(skipna=True)

_mc1, _mc2, _mc3, _save_col = st.columns([2, 2, 2, 1])
with _mc1:
    st.caption(f"Showing **{len(filt)}** of **{len(disp)}** parts")
with _mc2:
    st.metric("🔥 Order Cost (filtered)", f"${_order_cost:,.0f}")
with _mc3:
    st.metric("💰 Total BOM Cost (filtered)", f"${_total_bom_cost:,.0f}")


# ── Color coding ───────────────────────────────────────────────────────────────
def _row_color(row):
    s = row.get("Status", "")
    color = {"🔴 Missing": "#ffd6d6", "🟡 Partial": "#fff3cd", "✅ In Stock": "#d4edda"}.get(s, "white")
    return [f"background-color: {color}"] * len(row)


# ── Column config ──────────────────────────────────────────────────────────────
_col_cfg: dict = {
    "Find #":        st.column_config.NumberColumn("Find #", format="%d", width="small"),
    "Level":         st.column_config.TextColumn("Level", width="small"),
    "Heqa P.N":      st.column_config.TextColumn("Heqa P.N"),
    "Description":   st.column_config.TextColumn("Description", width="large"),
    "MFR Name":      st.column_config.TextColumn("MFR Name"),
    "MPN":           st.column_config.TextColumn("MPN"),
    "Qty (BOM)":     st.column_config.NumberColumn("Qty (BOM)", format="%g", width="small"),
    "In Stock":      st.column_config.NumberColumn("In Stock", format="%g", width="small"),
    "Unit Price $":  st.column_config.NumberColumn("Unit Price $", format="$%.2f"),
    "Total Cost $":  st.column_config.NumberColumn("Total Cost $", format="$%.2f"),
    "Part Type":     st.column_config.TextColumn("Type", width="small"),
    "Status":        st.column_config.TextColumn("Status"),
}
if has_sub_inv:
    _col_cfg["Sub Stock"] = st.column_config.NumberColumn("Sub Stock 🏭", format="%g", width="small")

# Column display order
_display_order = [
    "Find #", "Level", "Heqa P.N", "Description", "MFR Name", "MPN",
    "Part Type", "Qty (BOM)", "In Stock",
]
if has_sub_inv:
    _display_order.append("Sub Stock")
_display_order += ["Unit Price $", "Total Cost $", "Status"]
_display_order = [c for c in _display_order if c in filt.columns]

# ── Table ──────────────────────────────────────────────────────────────────────
st.dataframe(
    filt[_display_order].style.apply(_row_color, axis=1),
    use_container_width=True,
    height=min(len(filt) * 35 + 50, 800),
    hide_index=True,
    column_config=_col_cfg,
)

# ── Export ─────────────────────────────────────────────────────────────────────
st.download_button(
    "⬇️ Export to CSV",
    data=filt[_display_order].to_csv(index=False).encode("utf-8-sig"),
    file_name=f"BRD_{sel_brd}_{datetime.date.today()}.csv",
    mime="text/csv",
)
