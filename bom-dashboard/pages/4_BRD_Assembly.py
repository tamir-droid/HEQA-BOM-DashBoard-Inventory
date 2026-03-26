"""BRD Assembly Viewer — HEQA.

Select one or more BRD assemblies (with individual quantities) and view all
sub-components from the BOM hierarchy, including cost, inventory status,
subcontractor stock and PO / followup tracking.
"""

import datetime
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import streamlit as st

from config import (
    DATA_DIR, LOGO_PATH, PCBA_ICON_PATH,
    SS_AUTH, SS_IS_ADMIN, SS_CURRENT_USER, SS_FOLLOWUP,
    BOM_LEVEL_COL, BOM_VPN_COL, BOM_QTY_COL, BOM_DESC_COL,
    BOM_MFR_COL, BOM_MPN_COL, BOM_FIND_NUM_COL,
    INV_FILENAME, INV_KEY_COL, INV_QTY_COL,
    PRICE_FILENAME, PRICE_KEY_COL, PRICE_USD_COL,
    TYPE_FILENAME, TYPE_KEY_COL, TYPE_COL,
    BRD_SUB_INV_FILENAME, SUPPORT_FILES,
)
from utils.bom_loader import load_all_boms
from utils.price_parser import load_prices
from utils.type_parser import load_types
from utils.followup import load_followup, save_followup

# ── Page config ────────────────────────────────────────────────────────────────
try:
    from PIL import Image as _PILImage
    _pcba_icon = _PILImage.open(PCBA_ICON_PATH) if PCBA_ICON_PATH.exists() else "🖥️"
except Exception:
    _pcba_icon = "🖥️"

st.set_page_config(
    page_title="BRD Assembly — HEQA",
    page_icon=_pcba_icon,
    layout="wide",
)

st.markdown(
    "<style>[data-testid=\"stSidebarNav\"] { display: none; }</style>",
    unsafe_allow_html=True,
)

# ── Persist UI state across navigation (must be before any st.stop()) ──────────
for _pkey, _pdef in [
    ("brd_sel_brds",     []),
    ("brd_type_filter",  "All"),
    ("brd_status_filter","All"),
    ("brd_search",       ""),
]:
    if _pkey not in st.session_state:
        st.session_state[_pkey] = _pdef

# ── Navigation ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🗂️ Navigation")
    if st.button("🏠 Main Dashboard", use_container_width=True, key="nav_main"):
        st.switch_page("app.py")
    st.button("🔌 BRD Assembly", use_container_width=True, disabled=True)
    if st.button("📦 System Inventory", use_container_width=True, key="nav_inv"):
        st.switch_page("pages/2_System_Inventory.py")
    if st.button("📤 Upload Files", use_container_width=True, key="nav_site"):
        st.switch_page("pages/1_Site_Inventory.py")
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
        f"**`{INV_KEY_COL}`** (Heqa P.N) and **`{INV_QTY_COL}`** (Qty)"
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

# ── Always reload followup so all users see latest PO data ────────────────────
st.session_state[SS_FOLLOWUP] = load_followup(DATA_DIR)

# ── Header ─────────────────────────────────────────────────────────────────────
import base64 as _b64

def _pcba_title_html() -> str:
    if PCBA_ICON_PATH.exists():
        _img_b64 = _b64.b64encode(PCBA_ICON_PATH.read_bytes()).decode()
        return (
            f'<div style="display:flex;align-items:center;gap:12px">'
            f'<img src="data:image/png;base64,{_img_b64}" style="height:52px;width:auto">'
            f'<span style="font-size:2rem;font-weight:700">BRD Assembly Viewer</span>'
            f'</div>'
        )
    return "<h1>🖥️ BRD Assembly Viewer</h1>"

if LOGO_PATH.exists():
    logo_col, title_col = st.columns([1, 3])
    with logo_col:
        st.image(LOGO_PATH.read_bytes(), width=180)
    with title_col:
        st.markdown(_pcba_title_html(), unsafe_allow_html=True)
        st.caption("Select one or more BRD assemblies and set quantities to view combined sub-components.")
else:
    st.markdown(_pcba_title_html(), unsafe_allow_html=True)
    st.caption("Select one or more BRD assemblies and set quantities to view combined sub-components.")


# ── Helpers ────────────────────────────────────────────────────────────────────
def _parse_level(val) -> int:
    try:
        s = str(val).strip().lstrip(".")
        return int(float(s))
    except (ValueError, TypeError):
        return 999


def _parse_date(s):
    try:
        return datetime.date.fromisoformat(str(s)[:10]) if s else None
    except (ValueError, TypeError):
        return None


@st.cache_data(show_spinner=False)
def _load_all_boms() -> dict[str, pd.DataFrame]:
    bom_dict, _ = load_all_boms()
    return bom_dict


@st.cache_data(show_spinner=False)
def _load_price_map() -> dict[str, float]:
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


def _get_brd_description(bom_files: dict, brd_vpn: str) -> str:
    for df in bom_files.values():
        if BOM_VPN_COL not in df.columns or BOM_DESC_COL not in df.columns:
            continue
        match = df[df[BOM_VPN_COL].astype(str).str.strip() == brd_vpn]
        if not match.empty:
            desc = str(match.iloc[0][BOM_DESC_COL]).strip()
            if desc and desc.lower() != "nan":
                return desc
    return ""


def _get_brd_assemblies(bom_files: dict) -> dict[str, list[str]]:
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

# ── Multi-select BRD ───────────────────────────────────────────────────────────
st.caption("Select BRD Assemblies")
_all_brd_opts = sorted(brd_assemblies.keys())
if "brd_sel_brds" not in st.session_state:
    st.session_state["brd_sel_brds"] = _all_brd_opts[:1] if _all_brd_opts else []
sel_brds: list[str] = st.multiselect(
    "Select BRD Assemblies",
    options=_all_brd_opts,
    label_visibility="collapsed",
    help="Select one or more BRD assemblies. Set individual quantities below.",
    key="brd_sel_brds",
)

if not sel_brds:
    st.info("👆 Select one or more BRD assemblies above.")
    st.stop()

# ── Per-BRD Qty inputs ─────────────────────────────────────────────────────────
brd_qty_map: dict[str, int] = {}
_n = len(sel_brds)
_qty_cols_ui = st.columns(min(_n, 4))
for _i, _bvpn in enumerate(sel_brds):
    with _qty_cols_ui[_i % min(_n, 4)]:
        _desc = _get_brd_description(bom_files, _bvpn)
        _short = (_desc[:38] + "…") if len(_desc) > 38 else _desc
        st.caption(f"**{_bvpn}**" + (f"  {_short}" if _short else ""))
        _qty_key = f"brd_qty_{_bvpn}"
        if _qty_key not in st.session_state:
            st.session_state[_qty_key] = 1
        brd_qty_map[_bvpn] = st.number_input(
            f"Qty {_bvpn}", min_value=1, step=1,
            label_visibility="collapsed",
            key=_qty_key,
            help="Number of this BRD to build — multiplies all quantities and costs.",
        )

# ── Collect components across all selected BRDs ────────────────────────────────
# Use only the FIRST BOM file that has components for each BRD to avoid
# counting the same sub-components multiple times (BRD appears in N system BOMs).
all_components: list[pd.DataFrame] = []
for _sbrd in sel_brds:
    _sbrd_qty = brd_qty_map[_sbrd]
    for bom_name in brd_assemblies.get(_sbrd, []):
        df = bom_files[bom_name]
        comp_df = _get_components(df, _sbrd)
        if not comp_df.empty:
            comp_df = comp_df.copy()
            comp_df["BOM File"]  = bom_name
            comp_df["_sel_brd"]  = _sbrd
            comp_df["_brd_qty"]  = _sbrd_qty
            all_components.append(comp_df)
            break  # stop after first BOM file with components — prevents duplicate counting

if not all_components:
    st.info(f"No sub-components found under the selected BRD(s) in any BOM file.")
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
type_map:  dict[str, str]   = _load_type_map()
followup:  dict              = st.session_state.get(SS_FOLLOWUP, {})

# ── Build display DataFrame ─────────────────────────────────────────────────────
disp_cols = []
for col in [BOM_FIND_NUM_COL, BOM_LEVEL_COL, BOM_VPN_COL, BOM_DESC_COL,
            BOM_MFR_COL, BOM_MPN_COL, BOM_QTY_COL]:
    if col in combined.columns:
        disp_cols.append(col)

raw = combined[disp_cols + ["_sel_brd", "_brd_qty"]].copy()
raw = raw.rename(columns={
    BOM_FIND_NUM_COL: "Find #",
    BOM_LEVEL_COL:    "Level",
    BOM_VPN_COL:      "Heqa P.N",
    BOM_DESC_COL:     "Description",
    BOM_MFR_COL:      "MFR Name",
    BOM_MPN_COL:      "MPN",
    BOM_QTY_COL:      "Qty (BOM)",
})

raw["Qty (BOM)"] = pd.to_numeric(raw["Qty (BOM)"], errors="coerce").fillna(0)
raw["_row_req"]  = raw["Qty (BOM)"] * raw["_brd_qty"]

# Aggregate duplicate VPNs (same part used in multiple BRDs or BOM files)
disp = (
    raw.groupby("Heqa P.N", sort=False)
    .agg(
        **{
            "Find #":      ("Find #",    "first"),
            "Level":       ("Level",     "first"),
            "Description": ("Description","first"),
            "MFR Name":    ("MFR Name",  "first"),
            "MPN":         ("MPN",       "first"),
            "Qty (BOM)":   ("Qty (BOM)", "first"),
            "Qty Required":("_row_req",  "sum"),
            "BRD(s)":      ("_sel_brd",  lambda x: ", ".join(sorted(x.unique()))),
        }
    )
    .reset_index()
)

# ── Enrich columns ─────────────────────────────────────────────────────────────
disp["In Stock"]     = disp["Heqa P.N"].map(lambda v: inv_map.get(str(v).strip(), 0))
disp["Unit Price $"] = disp["Heqa P.N"].map(lambda v: price_map.get(str(v).strip()))
disp["Part Type"]    = disp["Heqa P.N"].map(lambda v: type_map.get(str(v).strip(), "—"))
if has_sub_inv:
    disp["Sub Stock"] = disp["Heqa P.N"].map(lambda v: sub_inv_map.get(str(v).strip(), 0))

# ── PO / Followup columns ──────────────────────────────────────────────────────
def _order_status(vpn: str) -> str:
    if vpn not in followup:
        return "—"
    po = str(followup[vpn].get("po", "")).strip().upper()
    if po == "NA":
        return "⬜ Ignored"
    return "🔵 Ordered"

disp["Order Status"] = disp["Heqa P.N"].map(_order_status)
disp["PO #"]         = disp["Heqa P.N"].map(
    lambda v: followup[v].get("po", "") if v in followup else ""
)
disp["Due Date"]     = disp["Heqa P.N"].map(
    lambda v: _parse_date(followup[v].get("due_date", "")) if v in followup else None
)
disp["Qty Ordered"]  = pd.to_numeric(
    disp["Heqa P.N"].map(lambda v: followup[v].get("qty_ordered") if v in followup else None),
    errors="coerce",
)

# ── Cost columns ───────────────────────────────────────────────────────────────
disp["Total Cost $"] = disp["Unit Price $"] * disp["Qty Required"]

_na_mask = disp["PO #"].str.strip().str.upper() == "NA"
disp.loc[_na_mask, "Total Cost $"] = 0


# ── Status ─────────────────────────────────────────────────────────────────────
def _status(row) -> str:
    try:
        qty_req  = float(row.get("Qty Required", 0) or 0)
        in_stock = float(row.get("In Stock",     0) or 0)
        sub_stk  = float(row.get("Sub Stock",    0) or 0) if has_sub_inv else 0.0
        total    = in_stock + sub_stk
        if total >= qty_req:
            return "✅ In Stock"
        elif total > 0:
            return "🟡 Partial"
        else:
            return "🔴 Missing"
    except Exception:
        return "—"

disp["Status"] = disp.apply(_status, axis=1)


# ── Status dot (with PO awareness) ────────────────────────────────────────────
def _dot(row) -> str:
    po = str(row.get("PO #", "")).strip().upper()
    if po == "NA":
        return "⬜"
    status = row.get("Status", "")
    ordered = row.get("Order Status", "") == "🔵 Ordered"
    if "Missing" in status and ordered:
        return "🟠"
    elif "Missing" in status:
        return "🔴"
    elif "In Stock" in status:
        return "🟢"
    else:
        return "🟡"

disp.insert(0, "●", disp.apply(_dot, axis=1))

# ── Sort ───────────────────────────────────────────────────────────────────────
disp["Find #"] = pd.to_numeric(disp["Find #"], errors="coerce")
disp = disp.sort_values(["Find #", "Level"], na_position="last").reset_index(drop=True)

# ── Info bar ───────────────────────────────────────────────────────────────────
_total    = len(disp)
_missing  = (disp["Status"] == "🔴 Missing").sum()
_in_stock = (disp["Status"] == "✅ In Stock").sum()
_partial  = (disp["Status"] == "🟡 Partial").sum()
_sub_note  = f" &nbsp;|&nbsp; 🏭 Sub: **{len(sub_inv_map):,}** parts" if has_sub_inv else ""
_brd_summary_str = "  |  ".join(
    f"**{b}** ×{brd_qty_map[b]}" for b in sel_brds
)
st.markdown(
    f"{_brd_summary_str}  \n"
    f"**{_total}** components &nbsp;|&nbsp; "
    f"✅ {_in_stock} &nbsp; 🟡 {_partial} &nbsp; 🔴 {_missing}{_sub_note}",
    unsafe_allow_html=True,
)

st.markdown("---")

# ── Filters ────────────────────────────────────────────────────────────────────
st.markdown("### 🔍 Filters")
_f1, _f2, _f3 = st.columns([2, 2, 3])

_all_types    = sorted(disp["Part Type"].dropna().unique().tolist()) if "Part Type" in disp.columns else []
_type_options = ["All"] + _all_types

with _f1:
    st.caption("Part Type")
    sel_type = st.selectbox(
        "Part Type", _type_options,
        label_visibility="collapsed", key="brd_type_filter",
    )

with _f2:
    st.caption("Status")
    sel_status = st.selectbox(
        "Status",
        ["All", "🔴 Missing", "🟠 Tracking", "🟡 Partial", "✅ In Stock"],
        label_visibility="collapsed", key="brd_status_filter",
    )

with _f3:
    st.caption("🔍 Search (VPN / Description / Manufacturer)")
    search_q = st.text_input(
        "Search", placeholder="Type P/N, description or MFR…",
        label_visibility="collapsed", key="brd_search",
    )

# Apply filters
filt = disp.copy()
if sel_type != "All":
    filt = filt[filt["Part Type"] == sel_type]
if sel_status == "🔴 Missing":
    filt = filt[filt["Status"] == "🔴 Missing"]
elif sel_status == "🟠 Tracking":
    filt = filt[(filt["Status"] == "🔴 Missing") & (filt["Order Status"] == "🔵 Ordered")]
elif sel_status == "🟡 Partial":
    filt = filt[filt["Status"] == "🟡 Partial"]
elif sel_status == "✅ In Stock":
    filt = filt[filt["Status"] == "✅ In Stock"]
if search_q:
    q = search_q.strip().lower()
    mask = (
        filt["Heqa P.N"].astype(str).str.lower().str.contains(q, na=False)
        | filt["Description"].astype(str).str.lower().str.contains(q, na=False)
        | filt["MFR Name"].astype(str).str.lower().str.contains(q, na=False)
        | filt["MPN"].astype(str).str.lower().str.contains(q, na=False)
    )
    filt = filt[mask]

# ── Cost metrics + Save button ─────────────────────────────────────────────────
_order_cost     = filt.loc[
    filt["Status"].isin(["🔴 Missing", "🟡 Partial"]) &
    ~_na_mask.reindex(filt.index, fill_value=False),
    "Total Cost $"
].sum(skipna=True)
_total_bom_cost = disp["Total Cost $"].sum(skipna=True)   # always unfiltered

_mc1, _mc2, _mc3, _save_col = st.columns([2, 2, 2, 1])
with _mc1:
    st.caption(f"Showing **{len(filt)}** of **{len(disp)}** parts")
with _mc2:
    st.metric("🔥 Order Cost (filtered)", f"${_order_cost:,.2f}")
with _mc3:
    st.metric("💰 Total BOM Cost", f"${_total_bom_cost:,.2f}")
with _save_col:
    st.markdown("<div style='margin-top:1.6rem'></div>", unsafe_allow_html=True)
    if st.button("💾 Save Changes", use_container_width=True, key="brd_save_top"):
        st.session_state["_brd_do_save"] = True

# ── Legend ─────────────────────────────────────────────────────────────────────
st.caption(
    "🔴 Missing &nbsp;|&nbsp; 🟠 Ordered / tracking &nbsp;|&nbsp; "
    "🟢 In stock &nbsp;|&nbsp; 🟡 Partial &nbsp;|&nbsp; ⬜ Ignored (NA)  "
    "— edit **PO #**, **Due Date**, **Qty Ordered** directly in the table, then click **Save Changes**."
)

# ── Column order ───────────────────────────────────────────────────────────────
_col_order = [
    "●", "Find #", "Level", "Heqa P.N", "Description", "MFR Name", "MPN",
    "Part Type", "BRD(s)", "Qty (BOM)", "Qty Required", "In Stock",
    "Sub Stock",
    "Unit Price $", "Total Cost $",
    "Order Status", "PO #", "Due Date", "Qty Ordered",
    "Status",
]
_display_cols = [c for c in _col_order if c in filt.columns]

# ── Column config ──────────────────────────────────────────────────────────────
_col_cfg: dict = {
    "●":            st.column_config.TextColumn("●", width="small"),
    "Find #":       st.column_config.NumberColumn("Find #", format="%d", width="small"),
    "Level":        st.column_config.TextColumn("Level", width="small"),
    "Heqa P.N":     st.column_config.TextColumn("Heqa P.N"),
    "Description":  st.column_config.TextColumn("Description", width="large"),
    "MFR Name":     st.column_config.TextColumn("MFR Name"),
    "MPN":          st.column_config.TextColumn("MPN"),
    "Part Type":    st.column_config.TextColumn("Type", width="small"),
    "BRD(s)":       st.column_config.TextColumn("BRD(s)", help="BRD assemblies that use this component"),
    "Qty (BOM)":    st.column_config.NumberColumn("Qty (BOM)", format="%g", width="small"),
    "Qty Required": st.column_config.NumberColumn("Qty Required", format="%g", width="small"),
    "In Stock":     st.column_config.NumberColumn("In Stock", format="%g", width="small"),
    "Sub Stock":    st.column_config.NumberColumn("Sub Stock 🏭", format="%g", width="small", min_value=0, step=1),
    "Unit Price $": st.column_config.NumberColumn("Unit Price $", format="$%.4f"),
    "Total Cost $": st.column_config.NumberColumn("Total Cost $", format="$%.4f"),
    "Order Status": st.column_config.TextColumn("Order Status", width="small"),
    "PO #":         st.column_config.TextColumn("PO #", help="Type 'NA' to exclude from Order Cost."),
    "Due Date":     st.column_config.DateColumn("Due Date", format="DD/MM/YYYY"),
    "Qty Ordered":  st.column_config.NumberColumn("Qty Ordered", min_value=0, step=1, format="%g"),
    "Status":       st.column_config.TextColumn("Status"),
}

# ── Editable table ─────────────────────────────────────────────────────────────
_editable = {"PO #", "Due Date", "Qty Ordered", "Sub Stock"}
_disabled  = [c for c in _display_cols if c not in _editable]

edited_df = st.data_editor(
    filt[_display_cols],
    column_config=_col_cfg,
    disabled=_disabled,
    use_container_width=True,
    height=min(len(filt) * 35 + 50, 800),
    hide_index=True,
    key="brd_table",
)

# ── Save logic ─────────────────────────────────────────────────────────────────
if st.session_state.pop("_brd_do_save", False):
    _fup = dict(st.session_state.get(SS_FOLLOWUP, {}))

    for _, row in edited_df.iterrows():
        vpn = str(row.get("Heqa P.N", "")).strip()
        if not vpn or vpn.lower() == "nan":
            continue

        po = str(row.get("PO #", "") or "").strip()

        _due_raw = row.get("Due Date")
        due = ""
        try:
            if _due_raw is not None and not (isinstance(_due_raw, float) and pd.isna(_due_raw)):
                _d = str(_due_raw)[:10]
                datetime.date.fromisoformat(_d)
                due = _d
        except (ValueError, TypeError):
            due = ""

        qty_ord = row.get("Qty Ordered")
        qty_ord_val = round(float(qty_ord), 1) if pd.notna(qty_ord) and qty_ord else None

        existing = _fup.get(vpn, {})
        if po or due or qty_ord_val:
            if vpn not in _fup:
                _fup[vpn] = {
                    "date": datetime.date.today().isoformat(),
                    "user": st.session_state.get(SS_CURRENT_USER, ""),
                    "notes": "",
                }
            _fup[vpn]["po"] = po
            _fup[vpn]["due_date"] = due if due else existing.get("due_date", "")
            _fup[vpn]["qty_ordered"] = qty_ord_val
        elif vpn in _fup and not _fup[vpn].get("manually_marked", False):
            del _fup[vpn]

    st.session_state[SS_FOLLOWUP] = _fup
    save_followup(DATA_DIR, _fup)

    # ── Update Sub Stock (Subcontractor Inventory) ────────────────────────────
    if "Sub Stock" in edited_df.columns:
        _sub_path = DATA_DIR / BRD_SUB_INV_FILENAME
        _current_sub = dict(sub_inv_map)
        _sub_changed = False
        for _, _row in edited_df.iterrows():
            _vpn = str(_row.get("Heqa P.N", "")).strip()
            if not _vpn or _vpn.lower() == "nan":
                continue
            _new_sub = pd.to_numeric(_row.get("Sub Stock", None), errors="coerce")
            _old_sub = float(sub_inv_map.get(_vpn, 0))
            if pd.notna(_new_sub) and float(_new_sub) != _old_sub:
                _current_sub[_vpn] = float(_new_sub)
                _sub_changed = True
        if _sub_changed:
            _sub_df = pd.DataFrame([
                {INV_KEY_COL: k, INV_QTY_COL: v}
                for k, v in _current_sub.items()
                if v > 0
            ])
            try:
                DATA_DIR.mkdir(parents=True, exist_ok=True)
                with pd.ExcelWriter(_sub_path, engine="openpyxl") as _w:
                    _sub_df.to_excel(_w, sheet_name="Sheet1", index=False)
                st.cache_data.clear()
            except Exception as _sub_err:
                st.warning(f"⚠️ Could not update subcontractor inventory: {_sub_err}")

    st.session_state.pop("brd_table", None)
    st.success("✅ Saved!")
    st.rerun()

# ── Export ─────────────────────────────────────────────────────────────────────
_export_name = "_".join(sel_brds)
st.download_button(
    "⬇️ Export to CSV",
    data=filt[_display_cols].to_csv(index=False).encode("utf-8-sig"),
    file_name=f"BRD_{_export_name}_{datetime.date.today()}.csv",
    mime="text/csv",
)
