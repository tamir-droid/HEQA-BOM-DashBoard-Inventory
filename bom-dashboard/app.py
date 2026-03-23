"""BOM & Inventory Procurement Dashboard — HEQA (local file version)."""

import datetime
import pandas as pd
import streamlit as st

from config import (
    DATA_DIR,
    BOM_VPN_COL,
    BOM_LEVEL_COL,
    BOM_QTY_COL,
    BOM_DESC_COL,
    BOM_MFR_COL,
    BOM_FIND_NUM_COL,
    INV_FILENAME,
    INV_KEY_COL,
    INV_QTY_COL,
    PRICE_FILENAME,
    TYPE_FILENAME,
    COMBINED_BOM_FILENAME,
    TYPE_KEY_COL,
    TYPE_COL,
    SUPPORT_FILES,
    SS_DATA,
    SS_RESULTS,
    SS_AUTH,
    SS_MUST_CHANGE_PW,
    SS_CURRENT_USER,
    SS_FOLLOWUP,
    SS_SITE_INV,
    SS_IS_ADMIN,
    LOGO_PATH,
    INV_KEY_COL,
    INV_QTY_COL,
)
from utils.bom_loader import load_all_boms
from utils.combined_bom_parser import is_combined_bom_filename
from utils.inventory_parser import load_inventory
from utils.price_parser import load_prices
from utils.type_parser import load_types
from utils.followup import load_followup, save_followup
from utils.kits import load_kits, save_kits
from utils.site_inventory import load_site_inventory
from utils.calculator import (
    aggregate_bom,
    calculate_results,
    get_kpis,
    get_brd_order_summary,
    COL_REQUIRED,
    COL_IN_STOCK,
    COL_TO_ORDER,
    COL_UNIT_PRICE,
    COL_TOTAL_COST,
    COL_ORDER_COST,
    COL_STATUS,
)

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="BOM & Inventory Dashboard — HEQA",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Global CSS ────────────────────────────────────────────────────────────────
st.markdown(
    """
    <style>
    /* Hide default Streamlit sidebar page navigation */
    [data-testid="stSidebarNav"] { display: none; }
    /* Metric card borders */
    [data-testid="metric-container"] {
        border: 1px solid #e0e0e0;
        border-radius: 8px;
        padding: 10px 14px;
    }
    /* Right-align Hebrew text inside dataframe cells */
    [data-testid="stDataFrame"] td {
        direction: rtl;
        text-align: right;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ── Auth helpers ─────────────────────────────────────────────────────────────
from utils.user_store import read_users, write_users as _write_users


def _save_new_password(username: str, new_password: str):
    """Update password in user store and clear must_change_password flag."""
    users = read_users()
    if username in users:
        users[username] = dict(users[username])
        users[username]["password"] = new_password
        users[username]["must_change_password"] = False
    _write_users(users)


def _show_login():
    _, col, _ = st.columns([1, 1.2, 1])
    with col:
        if LOGO_PATH.exists():
            st.image(LOGO_PATH.read_bytes(), use_container_width=True)
            st.markdown("")
        st.markdown("## 🔒 Login")
        st.markdown("Please enter your credentials to continue.")
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login", use_container_width=True)
        if submitted:
            users = read_users()
            if not users:
                st.error("⚠️ No users configured — add [users.USERNAME] blocks to Streamlit Cloud Secrets")
                return
            user_data = users.get(username)
            if user_data and password == user_data["password"]:
                st.session_state[SS_AUTH] = True
                st.session_state[SS_CURRENT_USER] = username
                must_change = bool(user_data.get("must_change_password", False))
                st.session_state[SS_MUST_CHANGE_PW] = must_change
                st.session_state[SS_IS_ADMIN] = user_data.get("role", "user") == "admin"
                st.rerun()
            else:
                st.error("❌ Invalid username or password")


def _show_change_password():
    _, col, _ = st.columns([1, 1.2, 1])
    with col:
        if LOGO_PATH.exists():
            st.image(LOGO_PATH.read_bytes(), use_container_width=True)
            st.markdown("")
        st.markdown("## 🔑 Set New Password")
        st.info("First login detected — please choose a new password before continuing.")
        with st.form("change_pw_form"):
            new_pw = st.text_input("New Password", type="password")
            confirm_pw = st.text_input("Confirm New Password", type="password")
            submitted = st.form_submit_button("Set Password", use_container_width=True)
        if submitted:
            if len(new_pw) < 6:
                st.error("Password must be at least 6 characters.")
                return
            if new_pw != confirm_pw:
                st.error("Passwords do not match.")
                return
            current_user = st.session_state.get(SS_CURRENT_USER, "")
            _save_new_password(current_user, new_pw)
            st.session_state[SS_MUST_CHANGE_PW] = False
            st.success("✅ Password updated! Loading dashboard…")
            st.rerun()


# ── BOM drill-down helpers ────────────────────────────────────────────────────
_BULK_PREFIXES = ("SCR", "SPC", "NUT", "WAS", "WIR")


def _normalize_level(val) -> int:
    """Convert BOM Level cell (int OR '.....8' string) to a plain integer."""
    s = str(val).strip().lstrip(".")
    try:
        return int(float(s))
    except Exception:
        return 999


def _get_assembly_children(bom_dfs: dict, vpn: str) -> pd.DataFrame:
    """Return all BOM rows that are descendants of *vpn* across every BOM file.

    Traverses the Level hierarchy: collects every row below the parent row
    whose level is strictly deeper, stopping when the level returns to the
    parent level or higher.
    """
    frames: list[pd.DataFrame] = []

    for bom_name, df in bom_dfs.items():
        if BOM_VPN_COL not in df.columns or BOM_LEVEL_COL not in df.columns:
            continue

        vpn_series = df[BOM_VPN_COL].astype(str).str.strip()
        levels = [_normalize_level(v) for v in df[BOM_LEVEL_COL]]
        n = len(df)

        for i in range(n):
            if vpn_series.iloc[i] != vpn:
                continue
            parent_level = levels[i]
            rows = []
            for j in range(i + 1, n):
                if levels[j] <= parent_level:
                    break
                row = df.iloc[j].to_dict()
                row["_bom_source"] = bom_name.replace(".xlsx", "")
                row["_depth"] = levels[j] - parent_level   # 1 = direct child
                rows.append(row)
            if rows:
                frames.append(pd.DataFrame(rows))

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    # Drop rows with empty VPN (assembly header rows, notes, etc.)
    if BOM_VPN_COL in combined.columns:
        combined = combined[
            combined[BOM_VPN_COL].notna()
            & (combined[BOM_VPN_COL].str.strip() != "")
            & (combined[BOM_VPN_COL].str.lower() != "nan")
        ]
    return combined.reset_index(drop=True)


# ── Login gate ────────────────────────────────────────────────────────────────
if not st.session_state.get(SS_AUTH):
    _show_login()
    st.stop()

# ── Forced password-change gate ───────────────────────────────────────────────
if st.session_state.get(SS_MUST_CHANGE_PW):
    _show_change_password()
    st.stop()


# ── Data loading ──────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def _load_all_local() -> dict:
    """Read every xlsx in DATA_DIR. Returns dict with bom, inventory, prices, types, errors."""
    result: dict = {"bom": {}, "inventory": None, "prices": None, "types": None, "errors": []}

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not any(DATA_DIR.glob("*.xlsx")):
        result["errors"].append("No data files uploaded yet — go to 📤 Upload Files to add your Excel files.")
        return result

    # ── Support files (inventory, prices, types) ──────────────────────────────
    for _fname, _loader, _key in [
        (INV_FILENAME,   load_inventory, "inventory"),
        (PRICE_FILENAME, load_prices,    "prices"),
        (TYPE_FILENAME,  load_types,     "types"),
    ]:
        _p = DATA_DIR / _fname
        if _p.exists():
            try:
                _df, _err = _loader(_p.read_bytes())
                if _err:
                    result["errors"].append(_err)
                else:
                    result[_key] = _df
            except Exception as exc:
                result["errors"].append(f"Cannot read '{_fname}': {exc}")

    # ── BOM files (combined or individual) ────────────────────────────────────
    _bom_dict, _bom_errors = load_all_boms()
    result["bom"].update(_bom_dict)
    result["errors"].extend(_bom_errors)
    if _bom_dict:
        result["combined_bom_loaded"] = any(
            is_combined_bom_filename(f.name) for f in DATA_DIR.glob("*.xlsx")
        )

    return result


def _do_refresh():
    st.cache_data.clear()
    st.session_state.pop(SS_DATA, None)
    st.session_state.pop(SS_RESULTS, None)


# ── Session state init ────────────────────────────────────────────────────────
# Always assign — @st.cache_data handles efficiency; no stale session state.
st.session_state[SS_DATA] = _load_all_local()

# Always reload followup from disk so all users see latest PO changes immediately
st.session_state[SS_FOLLOWUP] = load_followup(DATA_DIR)
st.session_state[SS_SITE_INV] = load_site_inventory(DATA_DIR)

data = st.session_state[SS_DATA]
bom_files: dict[str, pd.DataFrame] = data.get("bom", {})
_inv = data.get("inventory")
inventory_df: pd.DataFrame = _inv if _inv is not None else pd.DataFrame()
_prices = data.get("prices")
prices_df: pd.DataFrame = _prices if _prices is not None else pd.DataFrame()
_types = data.get("types")
types_df: pd.DataFrame = _types if _types is not None else pd.DataFrame()
load_errors: list[str] = data.get("errors", [])


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🗂️ Navigation")
    st.button("🏠 Main Dashboard", use_container_width=True, disabled=True)
    if st.button("🔌 BRD Assembly", use_container_width=True, key="nav_brd"):
        st.switch_page("pages/4_BRD_Assembly.py")
    if st.button("📦 System Inventory", use_container_width=True, key="nav_sys"):
        st.switch_page("pages/2_System_Inventory.py")
    if st.button("📤 Upload Files", use_container_width=True, key="nav_site"):
        st.switch_page("pages/1_Site_Inventory.py")
    if st.session_state.get(SS_IS_ADMIN):
        if st.button("👥 Users", use_container_width=True, key="nav_users"):
            st.switch_page("pages/3_User_Management.py")

    st.markdown("---")
    st.title("⚙️ Settings")

    current_user = st.session_state.get(SS_CURRENT_USER, "")
    if current_user:
        st.caption(f"👤 Logged in as **{current_user}**")

    if st.button("🚪 Logout", use_container_width=True):
        st.session_state.pop(SS_AUTH, None)
        st.session_state.pop(SS_CURRENT_USER, None)
        st.rerun()

    st.markdown("---")

    if st.button("🔄 Refresh Data", use_container_width=True, help="Re-read all files from disk"):
        _do_refresh()
        st.rerun()

    st.markdown("---")
    st.caption(f"📁 `{DATA_DIR.name}/`")
    _combined_loaded = data.get("combined_bom_loaded", False)
    _bom_src = " *(combined)*" if _combined_loaded else ""
    st.caption(f"📊 BOMs: **{len(bom_files)}** system(s){_bom_src}")
    st.caption(f"🗃️ System inventory: **{len(inventory_df):,}** rows")
    _site_count = len(st.session_state.get(SS_SITE_INV, {}))
    st.caption(f"🏭 Site inventory: **{_site_count:,}** parts")
    st.caption(f"💲 Price rows: **{len(prices_df):,}**")
    st.caption(f"🏷️ Type rows: **{len(types_df):,}**")


# ── Systems Quantity (above title) ───────────────────────────────────────
# Persist quantities across page navigation
if "_qty_persist" not in st.session_state:
    st.session_state["_qty_persist"] = {}

# ── Kits Order (shown first, above quantities) ───────────────────────────
_kits = load_kits(DATA_DIR)
_kit_names = list(_kits.keys())

st.markdown("### 📦 Kits Order")

# Single row: [multiselect] [kit name input] [Save] [Load] [Rename input] [Rename] [Delete]
_kc1, _kc2, _kc3, _kc4, _kc5, _kc6, _kc7 = st.columns([3, 2, 1.5, 1.5, 2, 1.5, 1.5])

with _kc1:
    _checked_kits = st.multiselect(
        "Kits", options=_kit_names,
        placeholder="Select kit(s)…",
        label_visibility="collapsed",
    )

with _kc2:
    _new_kit_name = st.text_input("Kit name", placeholder="New kit name…",
                                   label_visibility="collapsed")

with _kc3:
    if st.button("💾 Save", use_container_width=True):
        _name = _new_kit_name.strip()
        if not _name:
            st.warning("Enter a name.")
        else:
            _kits[_name] = dict(st.session_state.get("_qty_persist", {}))
            save_kits(DATA_DIR, _kits)
            st.success(f"✅ Saved '{_name}'")
            st.rerun()

with _kc4:
    if st.button("⬆️ Load", use_container_width=True):
        if not _checked_kits:
            st.warning("Select a kit.")
        else:
            _combined: dict[str, int] = {}
            for _kn in _checked_kits:
                for bom_name, qty in _kits[_kn].items():
                    _combined[bom_name] = _combined.get(bom_name, 0) + int(qty)
            for bom_name, qty in _combined.items():
                st.session_state["_qty_persist"][bom_name] = qty
                st.session_state[f"qty_{bom_name}"] = qty
            st.success(f"✅ Loaded: {', '.join(_checked_kits)}")
            st.rerun()

_ren_disabled = len(_checked_kits) != 1
with _kc5:
    _ren_val = st.text_input(
        "Rename to",
        value=_checked_kits[0] if not _ren_disabled else "",
        placeholder="New name…" if not _ren_disabled else "Select 1 kit…",
        disabled=_ren_disabled,
        label_visibility="collapsed",
        key="rename_kit_input",
    )

with _kc6:
    if st.button("✏️ Rename", use_container_width=True, disabled=_ren_disabled):
        _new_rn = _ren_val.strip()
        if _new_rn and _new_rn != _checked_kits[0]:
            _kits[_new_rn] = _kits.pop(_checked_kits[0])
            save_kits(DATA_DIR, _kits)
            st.success(f"✅ Renamed to '{_new_rn}'")
            st.rerun()

with _kc7:
    if st.button("🗑️ Delete", use_container_width=True, disabled=not _checked_kits):
        for _kn in _checked_kits:
            _kits.pop(_kn, None)
        save_kits(DATA_DIR, _kits)
        st.success(f"🗑️ Deleted!")
        st.rerun()

st.divider()

st.markdown("""<style>
.qty-label { font-size: 1.15rem; font-weight: 700; color: #1a1a2e; margin-bottom: 2px; }
</style>""", unsafe_allow_html=True)

qty_map: dict[str, int] = {}
if bom_files:
    st.markdown("### ⚙️ Systems Quantity")

    _bom_names = sorted(n for n in bom_files.keys() if str(n).upper().startswith("SYS-"))

    def _short(name: str) -> str:
        return (name.replace(".xlsx", "")
                    .replace("SYS-SP1-1-", "SP1-")
                    .replace("SYS-", ""))

    # Categories are mutually exclusive — a name lands in the first bucket it matches
    _names_br3   = sorted([n for n in _bom_names if "BR3" in n.upper()])
    _br3_set     = set(_names_br3)
    _names_1550  = sorted([n for n in _bom_names if "1550" in n and n not in _br3_set])
    _names_1310  = sorted([n for n in _bom_names if "1310" in n and n not in _br3_set])
    _assigned    = _br3_set | set(_names_1550) | set(_names_1310)
    _names_other = [n for n in _bom_names if n not in _assigned]

    def _qty_input(col, bom_name):
        with col:
            st.markdown(f'<p class="qty-label">{_short(bom_name)}</p>',
                        unsafe_allow_html=True)
            default_val = st.session_state["_qty_persist"].get(bom_name, 0)
            qty = st.number_input("qty", min_value=0, value=default_val, step=1,
                                  key=f"qty_{bom_name}", label_visibility="collapsed")
        qty_map[bom_name] = int(qty)
        st.session_state["_qty_persist"][bom_name] = int(qty)

    # Column layout: [1550-D, 1550-L, gap, BR3]
    _n_left = max(len(_names_1550), len(_names_1310), 1)
    _col_spec = [2] * _n_left + ([0.4, 2] if _names_br3 else [])

    # Row 1 — 1550 systems (left) + BR3 (right)
    _r1 = st.columns(_col_spec)
    for _i, _n in enumerate(_names_1550):
        _qty_input(_r1[_i], _n)
    if _names_br3:
        _qty_input(_r1[-1], _names_br3[0])

    # Row 2 — 1310 systems (left), BR3 column left empty
    if _names_1310:
        _r2 = st.columns(_col_spec)
        for _i, _n in enumerate(_names_1310):
            _qty_input(_r2[_i], _n)

    # Any other BOM files
    if _names_other:
        _ro = st.columns(min(3, len(_names_other)))
        for _col, _n in zip(_ro, _names_other):
            _qty_input(_col, _n)
else:
    qty_map = {}

st.markdown("---")

# ── Header ────────────────────────────────────────────────────────────────────
_logo_bytes = None
if LOGO_PATH.exists():
    try:
        _logo_bytes = LOGO_PATH.read_bytes()
    except Exception:
        pass

if _logo_bytes:
    logo_col, title_col = st.columns([1, 3])
    with logo_col:
        st.image(_logo_bytes, width=180)
    with title_col:
        st.markdown("# 📦 BOM & Inventory Procurement Dashboard")
        st.caption("Component Procurement Analysis")
else:
    st.title("📦 BOM & Inventory Procurement Dashboard")
    st.caption("HEQA — Component Procurement Analysis")

st.markdown("---")

# ── Main ──────────────────────────────────────────────────────────────────────
# Load errors
if load_errors:
    with st.expander(f"⚠️ {len(load_errors)} file load error(s) — click to expand", expanded=True):
        for err in load_errors:
            st.error(err)

# Calculate button
col_btn, _ = st.columns([1, 5])
with col_btn:
    calc_clicked = st.button("🔢 Calculate", type="primary", use_container_width=True)

if calc_clicked:
    if not any(q > 0 for q in qty_map.values()):
        st.warning("Set at least one production quantity before calculating.")
    else:
        with st.spinner("Calculating procurement requirements…"):
            required_df = aggregate_bom(bom_files, qty_map)

            # Merge system inventory + site inventory
            site_inv_data = st.session_state.get(SS_SITE_INV, {})
            if site_inv_data:
                site_rows = [
                    {INV_KEY_COL: vpn, INV_QTY_COL: d.get("qty", 0)}
                    for vpn, d in site_inv_data.items()
                ]
                site_inv_df = pd.DataFrame(site_rows)
                if inventory_df.empty:
                    combined_inv = site_inv_df
                else:
                    combined_inv = pd.concat(
                        [inventory_df[[INV_KEY_COL, INV_QTY_COL]], site_inv_df],
                        ignore_index=True,
                    )
                    combined_inv = (
                        combined_inv.groupby(INV_KEY_COL, as_index=False)[INV_QTY_COL].sum()
                    )
            else:
                combined_inv = inventory_df

            results = calculate_results(required_df, combined_inv, prices_df, types_df)
            st.session_state["_combined_inv"] = combined_inv
            # MFR Name 2 / MPN 2 come from BOM second rows (extracted in aggregate_bom)
            st.session_state[SS_RESULTS] = results

results: pd.DataFrame | None = st.session_state.get(SS_RESULTS)

if results is None:
    st.info("Set systems quantity in the sidebar and press **Calculate** to see results.")
    st.stop()

if results.empty:
    st.warning("No parts found after calculation. Verify BOM files have rows at levels > 1.")
    st.stop()

# ── KPI Row ───────────────────────────────────────────────────────────────────
kpis = get_kpis(results)
st.markdown("### 📊 Summary")
c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Total Parts", f"{kpis['total_parts']:,}")
c2.metric("✅ In Stock", f"{kpis['in_stock_count']:,}")
c3.metric("🔴 Missing", f"{kpis['missing_count']:,}")
c4.metric("Availability", f"{kpis['availability_pct']:.1f}%")
c5.metric("⚠️ No Price", f"{kpis['no_price_count']:,}")
c6.metric("Order Cost $", f"${kpis['order_cost']:,.2f}")

st.markdown("---")

_tab_comp, _tab_brd = st.tabs(["📊 Components", "🔌 BRD Assemblies"])

with _tab_comp:
    # ── Filters ───────────────────────────────────────────────────────────────
    st.markdown("### 🔍 Filters")
    fc1, fc2, fc3 = st.columns([2, 2, 3])

    with fc1:
        type_vals = sorted(results["Type"].dropna().unique().tolist()) if "Type" in results.columns else []
        if "BULK" not in type_vals:
            type_vals = sorted(type_vals + ["BULK"])
        type_options = ["All"] + type_vals
        _default_type_idx = type_options.index("R") if "R" in type_options else 0
        sel_type = st.selectbox("Part Type", type_options, index=_default_type_idx)

    with fc2:
        status_options = ["All", "🔴 Missing", "🟠 Tracking", "✅ In Stock", "⚠️ No Price"]
        sel_status = st.selectbox(
            "Status",
            status_options,
            index=status_options.index("🔴 Missing"),
        )

    with fc3:
        search = st.text_input("🔎 Search (VPN / Description / Manufacturer)", "")

    # BRD sub-components are always excluded from main dashboard (visible only in 🔌 BRD Assembly page)

    # Apply filters
    df_show = results.copy()

    # ── Inject Order Status, PO #, Due Date, Qty Ordered from followup ────────
    _followup = st.session_state.get(SS_FOLLOWUP, {})
    def _order_status(v):
        if v not in _followup:
            return "—"
        po = str(_followup[v].get("po", "")).strip().upper()
        if po == "NA":
            return "⬜ Ignored"
        return "🔵 Ordered"

    df_show["Order Status"] = df_show[BOM_VPN_COL].map(_order_status)
    df_show["PO #"] = df_show[BOM_VPN_COL].map(
        lambda v: _followup[v].get("po", "") if v in _followup else ""
    )
    def _parse_date(s):
        try:
            # Handle "2024-06-15" and "2024-06-15T00:00:00" (Timestamp isoformat)
            return datetime.date.fromisoformat(str(s)[:10]) if s else None
        except (ValueError, TypeError):
            return None

    df_show["Due Date"] = df_show[BOM_VPN_COL].map(
        lambda v: _parse_date(_followup[v].get("due_date", "")) if v in _followup else None
    )
    df_show["Qty Ordered"] = pd.to_numeric(
        df_show[BOM_VPN_COL].map(lambda v: _followup[v].get("qty_ordered") if v in _followup else None),
        errors="coerce",
    )

    # Override Type to BULK for parts whose VPN starts with a known BULK prefix
    _bulk_mask = df_show[BOM_VPN_COL].str.upper().str.startswith(_BULK_PREFIXES)
    df_show.loc[_bulk_mask, "Type"] = "BULK"

    # ── NA logic: if PO # == "NA", zero out Order Cost and To Order ───────────
    _na_mask = df_show["PO #"].str.strip().str.upper() == "NA"
    if _na_mask.any():
        if COL_ORDER_COST in df_show.columns:
            df_show.loc[_na_mask, COL_ORDER_COST] = 0
        if COL_TO_ORDER in df_show.columns:
            df_show.loc[_na_mask, COL_TO_ORDER] = 0

    if sel_type != "All" and "Type" in df_show.columns:
        df_show = df_show[df_show["Type"] == sel_type]
        # Always exclude BULK-prefixed items from non-BULK type views
        if sel_type != "BULK":
            df_show = df_show[~df_show[BOM_VPN_COL].str.upper().str.startswith(_BULK_PREFIXES)]

    if sel_status != "All":
        if sel_status == "🔴 Missing" and COL_STATUS in df_show.columns:
            # All missing parts — both unordered (red) and ordered-in-tracking (orange)
            df_show = df_show[df_show[COL_STATUS].str.contains("Missing", na=False)]
        elif sel_status == "🟠 Tracking" and COL_STATUS in df_show.columns:
            # Only missing parts where an order has been placed
            df_show = df_show[
                df_show[COL_STATUS].str.contains("Missing", na=False)
                & (df_show["Order Status"] == "🔵 Ordered")
            ]
        elif sel_status == "✅ In Stock" and COL_STATUS in df_show.columns:
            df_show = df_show[df_show[COL_STATUS] == "✅ In Stock"]
        elif sel_status == "⚠️ No Price" and COL_STATUS in df_show.columns:
            df_show = df_show[df_show[COL_STATUS].str.contains("No Price", na=False)]

    if search:
        s = search.lower()
        mask = pd.Series([False] * len(df_show), index=df_show.index)
        for col in [BOM_VPN_COL, "Description", BOM_MFR_COL, "Heqa P.N", "MFR Name"]:
            if col in df_show.columns:
                mask |= df_show[col].astype(str).str.lower().str.contains(s, na=False)
        df_show = df_show[mask]

    # Always exclude BRD sub-components from main dashboard
    if "Under BRD" in df_show.columns:
        df_show = df_show[~df_show["Under BRD"]]

    _cap_col, _cost_col1, _cost_col2, _save_btn_col = st.columns([3, 2, 2, 1])
    with _cap_col:
        st.caption(f"Showing **{len(df_show):,}** of **{len(results):,}** parts")
    with _cost_col1:
        if COL_ORDER_COST in df_show.columns:
            _order_cost = pd.to_numeric(df_show[COL_ORDER_COST], errors="coerce").sum()
            st.metric("💰 Order Cost (filtered)", f"${_order_cost:,.2f}")
    with _cost_col2:
        if COL_TOTAL_COST in df_show.columns:
            _total_cost = pd.to_numeric(df_show[COL_TOTAL_COST], errors="coerce").sum()
            st.metric("📦 Total BOM Cost (filtered)", f"${_total_cost:,.2f}")
    with _save_btn_col:
        st.markdown("<div style='margin-top:1.6rem'></div>", unsafe_allow_html=True)
        if st.button("💾 Save Changes", use_container_width=True, key="save_top"):
            st.session_state["_do_save_main"] = True

    # Sort by MFR Name
    if "MFR Name" in df_show.columns:
        df_show = df_show.sort_values("MFR Name", ascending=True, na_position="last").reset_index(drop=True)

    # Rename VPN column and Manufacturer for display
    df_show = df_show.rename(columns={BOM_VPN_COL: "Heqa P.N", "Manufacturer": "MFR Name"})

    _table_height = max(200, len(df_show) * 35 + 50)

    # ── Status emoji indicator column ─────────────────────────────────────────
    def _status_emoji(row: pd.Series) -> str:
        po = str(row.get("PO #", "")).strip().lower()
        if po == "ignore":
            return "⬜"
        if po == "na":
            return "🚫"  # NA = excluded from order cost, shown grey with "Ignored"
        is_ordered = row.get("Order Status", "—") == "🔵 Ordered"
        status = str(row.get(COL_STATUS, ""))
        if is_ordered and "Missing" in status:
            return "🟠"
        elif "Missing" in status:
            return "🔴"
        elif "In Stock" in status:
            return "🟢"
        else:
            return "🟡"

    df_show.insert(0, "●", df_show.apply(_status_emoji, axis=1))

    # ── Reorder columns: MFR Name 2 + MPN 2 right after MPN ──────────────────
    _col_order = [
        "●", "Heqa P.N", "Description", "MFR Name",
        "Manufacturer Part Number",
        "MFR Name 2", "MPN 2",
        "Type",
        COL_REQUIRED, COL_IN_STOCK, COL_TO_ORDER,
        COL_UNIT_PRICE, COL_TOTAL_COST, COL_ORDER_COST,
        "Order Status", "PO #", "Due Date", "Qty Ordered",
        COL_STATUS, "Product Breakdown",
    ]
    _ordered = [c for c in _col_order if c in df_show.columns]
    _extra   = [c for c in df_show.columns if c not in _col_order]
    df_show  = df_show[_ordered + _extra]

    # ── Column config ──────────────────────────────────────────────────────────
    _view_col_cfg = {
        "●":            st.column_config.TextColumn("●", width="small"),
        "Heqa P.N":     st.column_config.TextColumn("Heqa P.N"),
        "Description":  st.column_config.TextColumn("Description"),
        "MFR Name":     st.column_config.TextColumn("MFR Name"),
        "Manufacturer Part Number": st.column_config.TextColumn("MPN"),
        "MFR Name 2": st.column_config.TextColumn("MFR Name 2"),
        "MPN 2":      st.column_config.TextColumn("MPN 2"),
        "Type":         st.column_config.TextColumn("Type", width="small"),
        COL_REQUIRED:   st.column_config.NumberColumn("Required", format="%d"),
        COL_IN_STOCK:   st.column_config.NumberColumn("In Stock", format="%d"),
        COL_TO_ORDER:   st.column_config.NumberColumn("To Order", format="%d"),
        COL_UNIT_PRICE: st.column_config.NumberColumn("Unit $", format="$%.4f"),
        COL_TOTAL_COST: st.column_config.NumberColumn("Total Cost $", format="$%.4f"),
        COL_ORDER_COST: st.column_config.NumberColumn("Order Cost $", format="$%.4f"),
        COL_STATUS:     st.column_config.TextColumn("Status"),
        "Order Status": st.column_config.TextColumn("Order Status", width="small"),
        "PO #":         st.column_config.TextColumn("PO #", help="Type 'NA' to exclude from Order Cost. Type 'Ignore' to mark as ignored."),
        "Due Date":     st.column_config.DateColumn("Due Date", format="DD/MM/YYYY"),
        "Qty Ordered":  st.column_config.NumberColumn("Qty Ordered", min_value=0, step=0.1, format="%.1f"),
    }

    # ── Color legend ──────────────────────────────────────────────────────────
    st.caption(
        "🔴 Missing &nbsp;|&nbsp; "
        "🟠 Ordered / tracking &nbsp;|&nbsp; "
        "🟢 In stock &nbsp;|&nbsp; "
        "🟡 Partial &nbsp;|&nbsp; "
        "⬜ Ignored &nbsp;— edit **PO #**, **Due Date**, **Qty Ordered** directly, then click **Save Changes**."
    )

    # ── Editable results table ─────────────────────────────────────────────────
    _editable_cols = {"PO #", "Due Date", "Qty Ordered", COL_IN_STOCK}
    _disabled_cols = [c for c in df_show.columns if c not in _editable_cols]

    edited_df = st.data_editor(
        df_show,
        column_config=_view_col_cfg,
        disabled=_disabled_cols,
        use_container_width=True,
        height=_table_height,
        hide_index=True,
        key="main_table",
    )

    if st.session_state.pop("_do_save_main", False):
        _fup = dict(st.session_state.get(SS_FOLLOWUP, {}))

        for _, row in edited_df.iterrows():
            vpn = str(row.get("Heqa P.N", ""))
            po = str(row.get("PO #", "") or "").strip()
            _due_raw = row.get("Due Date")
            due = ""
            try:
                if _due_raw is not None and not (isinstance(_due_raw, float) and pd.isna(_due_raw)):
                    _d = str(_due_raw)[:10]
                    datetime.date.fromisoformat(_d)   # validate
                    due = _d
            except (ValueError, TypeError):
                due = ""
            qty_ord = row.get("Qty Ordered")
            qty_ord_val = round(float(qty_ord), 1) if pd.notna(qty_ord) and qty_ord else None

            was_tracked = vpn in _fup
            manually_marked = was_tracked and _fup[vpn].get("manually_marked", False)
            existing = _fup.get(vpn, {})
            if po or due or qty_ord_val:
                if vpn not in _fup:
                    _fup[vpn] = {
                        "date": datetime.date.today().isoformat(),
                        "user": st.session_state.get(SS_CURRENT_USER, ""),
                        "notes": "",
                        "manually_marked": False,
                    }
                _fup[vpn]["po"] = po
                # Preserve existing due_date if user didn't change it (came back empty)
                _fup[vpn]["due_date"] = due if due else existing.get("due_date", "")
                _fup[vpn]["qty_ordered"] = qty_ord_val
            elif was_tracked and not manually_marked:
                del _fup[vpn]

        st.session_state[SS_FOLLOWUP] = _fup
        save_followup(DATA_DIR, _fup)

        # ── Update Inventory.xlsx for any In Stock qty changes ─────────────────
        _inv_path = DATA_DIR / "Inventory.xlsx"
        try:
            _inv_df = pd.read_excel(_inv_path, sheet_name="Sheet1", dtype=str) if _inv_path.exists() else pd.DataFrame()
        except Exception:
            _inv_df = pd.DataFrame()
        if not _inv_df.empty and INV_KEY_COL in _inv_df.columns and INV_QTY_COL in _inv_df.columns:
            _inv_updated = False
            for _, _row in edited_df.iterrows():
                _vpn = str(_row.get("Heqa P.N", "")).strip()
                _new_qty = _row.get(COL_IN_STOCK)
                if not _vpn or pd.isna(_new_qty):
                    continue
                _orig_rows = df_show[df_show["Heqa P.N"] == _vpn][COL_IN_STOCK]
                if _orig_rows.empty:
                    continue
                _orig_val = float(_orig_rows.iloc[0]) if pd.notna(_orig_rows.iloc[0]) else 0.0
                _new_val = float(_new_qty)
                if _orig_val != _new_val:
                    _mask = _inv_df[INV_KEY_COL].astype(str).str.strip() == _vpn
                    if _mask.any():
                        _inv_df.loc[_mask, INV_QTY_COL] = _new_val
                        _inv_updated = True
            if _inv_updated:
                try:
                    with pd.ExcelWriter(DATA_DIR / "Inventory.xlsx", engine="openpyxl") as _w:
                        _inv_df.to_excel(_w, sheet_name="Sheet1", index=False)
                    st.cache_data.clear()
                except Exception as _e:
                    st.warning(f"⚠️ Could not update Inventory.xlsx: {_e}")

        # Clear data_editor widget state so it reloads fresh from disk
        st.session_state.pop("main_table", None)
        st.success("✅ Saved!")
        st.rerun()

    # ── Exports ───────────────────────────────────────────────────────────────
    st.markdown("### 📥 Export")
    ec1, ec2, ec3 = st.columns(3)

    today = datetime.date.today().isoformat()

    with ec1:
        to_order_df = df_show[df_show[COL_TO_ORDER] > 0].copy() if COL_TO_ORDER in df_show.columns else pd.DataFrame()
        if not to_order_df.empty:
            st.download_button(
                "⬇️ Order List (CSV)",
                data=to_order_df.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"order_list_{today}.csv",
                mime="text/csv",
                use_container_width=True,
            )
        else:
            st.success("Nothing to order in current view.")

    with ec2:
        no_price_df = (
            df_show[df_show[COL_UNIT_PRICE].isna()].copy()
            if COL_UNIT_PRICE in df_show.columns
            else pd.DataFrame()
        )
        if not no_price_df.empty:
            st.download_button(
                "⬇️ No-Price List (CSV)",
                data=no_price_df.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"no_price_{today}.csv",
                mime="text/csv",
                use_container_width=True,
            )
        else:
            st.success("All parts have prices.")

    with ec3:
        st.download_button(
            "⬇️ Full View (CSV)",
            data=df_show.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"bom_results_{today}.csv",
            mime="text/csv",
            use_container_width=True,
        )

with _tab_brd:
    _combined_inv_brd = st.session_state.get("_combined_inv", inventory_df)
    _brd_summary = get_brd_order_summary(bom_files, qty_map, _combined_inv_brd, prices_df)
    if _brd_summary.empty:
        st.info("No BRD sub-assemblies found in the selected systems, or no BRD sub-BOMs are loaded.")
        st.caption("To see BRD cost breakdown, include BRD assembly BOMs in your combined BOM file.")
    else:
        _brd_total = _brd_summary["Order Cost $"].fillna(0).sum()
        _brd_count = _brd_summary["BRD P/N"].nunique()
        _bc1, _bc2 = st.columns(2)
        _bc1.metric("BRD Assemblies", f"{_brd_count}")
        _bc2.metric("💰 Total BRD Order Cost", f"${_brd_total:,.2f}")
        st.markdown("---")
        st.dataframe(
            _brd_summary,
            column_config={
                "System":          st.column_config.TextColumn("System"),
                "BRD P/N":         st.column_config.TextColumn("BRD P/N"),
                "Description":     st.column_config.TextColumn("Description"),
                "Qty/System":      st.column_config.NumberColumn("Qty/System", format="%.0f"),
                "Total BRD Qty":   st.column_config.NumberColumn("Total BRD Qty", format="%d"),
                "Order Cost $":    st.column_config.NumberColumn("Order Cost $", format="$%.2f"),
                "Note":            st.column_config.TextColumn("Note"),
            },
            hide_index=True,
            use_container_width=True,
        )

# ── Assembly Drill-Down (P-type parts) ───────────────────────────────────────
st.markdown("---")
st.markdown("### 🔩 Assembly Drill-Down")
st.caption("Select a manufactured assembly (P-type) to view all its sub-components from the BOM hierarchy.")

# Build list of P-type VPNs from full results (exclude BULK prefixes)
if "Type" in results.columns:
    _p_mask = results["Type"] == "P"
    _bulk_vpn_mask = results[BOM_VPN_COL].str.upper().str.startswith(_BULK_PREFIXES)
    _p_vpns = sorted(
        results.loc[_p_mask & ~_bulk_vpn_mask, BOM_VPN_COL].dropna().unique().tolist()
    )
else:
    _p_vpns = []

if not _p_vpns:
    st.info("No P-type assemblies found in the current results.")
else:
    _dd_col1, _dd_col2, _dd_col3 = st.columns([3, 3, 1])
    with _dd_col1:
        _sel_assy = st.selectbox(
            "Assembly (P-type)",
            options=["— Select an assembly —"] + _p_vpns,
            key="assembly_drilldown_select",
        )
    with _dd_col2:
        if not _sel_assy.startswith("—"):
            # Look up description from results or BOM files
            _assy_desc = ""
            if "Description" in results.columns:
                _desc_match = results.loc[
                    results[BOM_VPN_COL].astype(str).str.strip() == _sel_assy, "Description"
                ]
                if not _desc_match.empty:
                    _assy_desc = str(_desc_match.iloc[0])
            if not _assy_desc:
                for _bf in bom_files.values():
                    if BOM_VPN_COL in _bf.columns and BOM_DESC_COL in _bf.columns:
                        _m = _bf.loc[_bf[BOM_VPN_COL].astype(str).str.strip() == _sel_assy, BOM_DESC_COL]
                        if not _m.empty:
                            _assy_desc = str(_m.iloc[0])
                            break
            if _assy_desc:
                st.markdown(f"**Description:** {_assy_desc}")
    with _dd_col3:
        _direct_only = st.checkbox("Direct children only", value=False,
                                   help="Show only the first level of children (depth = 1).\n"
                                        "Uncheck to see all descendants at every level.")

    if not _sel_assy.startswith("—"):
        _children = _get_assembly_children(bom_files, _sel_assy)

        if _children.empty:
            st.info(f"No sub-components found in the BOM for **{_sel_assy}**.")
        else:
            if _direct_only:
                _children = _children[_children["_depth"] == 1]

            # ── Enrich children with Type and Inventory ───────────────────────
            if not types_df.empty and TYPE_KEY_COL in types_df.columns:
                _type_map = types_df.set_index(TYPE_KEY_COL)[TYPE_COL].to_dict()
                _children["Type"] = (
                    _children[BOM_VPN_COL].map(_type_map).fillna("—")
                )
            else:
                _children["Type"] = "—"

            # Override BULK prefixes
            _c_bulk = _children[BOM_VPN_COL].str.upper().str.startswith(_BULK_PREFIXES)
            _children.loc[_c_bulk, "Type"] = "BULK"

            if not inventory_df.empty and INV_KEY_COL in inventory_df.columns:
                _inv_map = (
                    inventory_df
                    .drop_duplicates(subset=INV_KEY_COL)
                    .set_index(INV_KEY_COL)[INV_QTY_COL]
                )
                _children["In Stock"] = pd.to_numeric(
                    _children[BOM_VPN_COL].map(_inv_map), errors="coerce"
                ).fillna(0).astype(int)
            else:
                _children["In Stock"] = 0

            # ── Build display DataFrame ───────────────────────────────────────
            _disp_cols_ordered = [
                "_depth", BOM_FIND_NUM_COL, BOM_VPN_COL,
                BOM_DESC_COL, BOM_QTY_COL, BOM_MFR_COL,
                "Type", "In Stock", "_bom_source",
            ]
            _disp_cols = [c for c in _disp_cols_ordered if c in _children.columns]
            _child_disp = _children[_disp_cols].rename(columns={
                "_depth":        "Depth",
                BOM_VPN_COL:     "Heqa P.N",
                BOM_DESC_COL:    "Description",
                BOM_QTY_COL:     "Qty / Assembly",
                BOM_MFR_COL:     "Manufacturer",
                "_bom_source":   "BOM File",
            })

            # ── Deduplicate: 1 row per P.N ───────────────────────────────────
            if "Heqa P.N" in _child_disp.columns:
                _agg_map = {c: "first" for c in _child_disp.columns if c != "Heqa P.N"}
                if "BOM File" in _child_disp.columns:
                    _agg_map["BOM File"] = lambda x: " | ".join(x.dropna().astype(str).unique())
                _child_disp = (
                    _child_disp
                    .groupby("Heqa P.N", sort=False)
                    .agg(_agg_map)
                    .reset_index()
                )

            _n_unique = _child_disp["Heqa P.N"].nunique() if "Heqa P.N" in _child_disp.columns else len(_child_disp)
            _n_boms   = _child_disp["BOM File"].nunique() if "BOM File" in _child_disp.columns else 1
            st.caption(
                f"Assembly **{_sel_assy}** → "
                f"**{len(_child_disp):,}** rows · "
                f"**{_n_unique}** unique P/Ns · "
                f"across **{_n_boms}** BOM file(s)"
            )

            # Colour rows: red if 0 in stock, green if in stock
            def _color_child_row(row: pd.Series) -> list[str]:
                try:
                    stock = int(row.get("In Stock", 0))
                except Exception:
                    stock = 0
                if stock <= 0:
                    return ["background-color: #ffd6d6"] * len(row)
                return ["background-color: #d6f5d6"] * len(row)

            _styled_children = _child_disp.style.apply(_color_child_row, axis=1)
            st.dataframe(_styled_children, use_container_width=True, height=420)

            # Export children list
            _exp_col, _ = st.columns([1, 4])
            with _exp_col:
                st.download_button(
                    "⬇️ Export Sub-Components (CSV)",
                    data=_child_disp.to_csv(index=False).encode("utf-8-sig"),
                    file_name=f"children_{_sel_assy}_{datetime.date.today().isoformat()}.csv",
                    mime="text/csv",
                    use_container_width=True,
                )

# ── Follow-up — Track Placed Orders ──────────────────────────────────────────
st.markdown("---")
followup: dict = st.session_state.get(SS_FOLLOWUP, {})
ordered_count = len(followup)
label = f"📦 Follow-up — Orders Placed ({ordered_count} part{'s' if ordered_count != 1 else ''})"

with st.expander(label, expanded=False):

    # ── Mark new orders ───────────────────────────────────────────────────────
    st.markdown("#### ✅ Mark Parts as Ordered")

    # Only offer missing parts that are not already tracked
    all_missing_vpns = (
        results.loc[results[COL_TO_ORDER] > 0, BOM_VPN_COL].tolist()
        if COL_TO_ORDER in results.columns else []
    )
    unordered_vpns = [v for v in all_missing_vpns if v not in followup]

    if unordered_vpns:
        with st.form("mark_ordered_form"):
            to_mark = st.multiselect(
                "Select parts to mark as ordered",
                options=unordered_vpns,
                help="Only missing & not-yet-tracked parts are shown here",
            )
            po_col, notes_col = st.columns(2)
            with po_col:
                po_number = st.text_input("PO Number (optional)")
            with notes_col:
                notes = st.text_input("Notes (optional, e.g. expected delivery)")
            submitted = st.form_submit_button("✅ Mark as Ordered", use_container_width=True)

        if submitted:
            if to_mark:
                for vpn in to_mark:
                    followup[vpn] = {
                        "po": po_number.strip(),
                        "notes": notes.strip(),
                        "date": datetime.date.today().isoformat(),
                        "user": st.session_state.get(SS_CURRENT_USER, ""),
                        "manually_marked": True,
                        "due_date": "",
                        "qty_ordered": None,
                    }
                st.session_state[SS_FOLLOWUP] = followup
                save_followup(DATA_DIR, followup)
                st.rerun()
            else:
                st.warning("Select at least one part.")
    else:
        st.info("All missing parts are already tracked as ordered.")

    # ── View & delete ──────────────────────────────────────────────────────────
    if followup:
        st.markdown(f"#### 📋 Already Ordered ({len(followup)} parts)")
        st.caption("Check the **Delete** box on any row then click **Delete Selected** to remove it.")

        fo_rows = []
        for vpn, d in followup.items():
            # Skip NA items — not shown in Already Ordered section
            if str(d.get("po", "")).strip().upper() == "NA":
                continue
            desc = ""
            match = results.loc[results[BOM_VPN_COL] == vpn, "Description"]
            if not match.empty:
                desc = str(match.iloc[0])
            fo_rows.append({
                "Delete": False,
                "Heqa P.N": vpn,
                "Description": desc,
                "PO #": d.get("po", ""),
                "Due Date": _parse_date(d.get("due_date", "")),
                "Qty Ordered": d.get("qty_ordered") or None,
                "Order Date": d.get("date", ""),
                "By": d.get("user", ""),
                "Notes": d.get("notes", ""),
            })

        fo_df = pd.DataFrame(fo_rows)
        edited_fo = st.data_editor(
            fo_df,
            column_config={
                "Delete":      st.column_config.CheckboxColumn("Delete", help="Check to delete this entry"),
                "Heqa P.N":    st.column_config.Column(disabled=True),
                "Description": st.column_config.Column(disabled=True),
                "PO #":        st.column_config.TextColumn("PO #"),
                "Due Date":    st.column_config.DateColumn("Due Date", format="DD/MM/YYYY"),
                "Qty Ordered": st.column_config.NumberColumn("Qty Ordered", min_value=0, step=0.1, format="%.1f"),
                "Order Date":  st.column_config.Column(disabled=True),
                "By":          st.column_config.Column(disabled=True),
                "Notes":       st.column_config.Column(disabled=True),
            },
            hide_index=True,
            use_container_width=True,
            key="followup_table",
        )

        del_col, save_col, _ = st.columns([1, 1, 3])
        with save_col:
            if st.button("💾 Save Changes", use_container_width=True, key="save_fo_edits"):
                _fup = dict(st.session_state.get(SS_FOLLOWUP, {}))
                for _, row in edited_fo.iterrows():
                    vpn = str(row.get("Heqa P.N", ""))
                    if vpn not in _fup:
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
                    _fup[vpn]["po"] = po
                    # Preserve existing due_date if user didn't change it (came back empty)
                    _fup[vpn]["due_date"] = due if due else _fup[vpn].get("due_date", "")
                    _fup[vpn]["qty_ordered"] = qty_ord_val
                st.session_state[SS_FOLLOWUP] = _fup
                save_followup(DATA_DIR, _fup)
                # Clear data_editor widget state so it reloads fresh from disk
                st.session_state.pop("followup_table", None)
                st.success("✅ Saved!")
                st.rerun()
        with del_col:
            if st.button("🗑️ Delete Selected", use_container_width=True):
                to_delete = edited_fo.loc[edited_fo["Delete"] == True, "Heqa P.N"].tolist()
                if to_delete:
                    for vpn in to_delete:
                        followup.pop(vpn, None)
                    st.session_state[SS_FOLLOWUP] = followup
                    save_followup(DATA_DIR, followup)
                    st.rerun()
                else:
                    st.warning("No rows checked for deletion.")
