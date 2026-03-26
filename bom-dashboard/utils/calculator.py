import pandas as pd
from utils.bom_parser import get_brd_vpns
from config import (
    BOM_VPN_COL,
    BOM_QTY_COL,
    BOM_DESC_COL,
    BOM_MFR_COL,
    BOM_MPN_COL,
    BOM_LEVEL_COL,
    INV_KEY_COL,
    INV_QTY_COL,
    PRICE_KEY_COL,
    PRICE_USD_COL,
    TYPE_KEY_COL,
    TYPE_COL,
)

# Output column names (stable across merges)
COL_REQUIRED = "Required Qty"
COL_IN_STOCK = "In Stock"
COL_TO_ORDER = "To Order"
COL_UNIT_PRICE = "Unit Price $"
COL_TOTAL_COST = "Total Cost $"
COL_ORDER_COST = "Order Cost $"
COL_STATUS = "Status"
COL_BREAKDOWN = "Product Breakdown"


def aggregate_bom(bom_dfs: dict[str, pd.DataFrame], qty_map: dict[str, int]) -> pd.DataFrame:
    """Sum required quantities across all BOMs weighted by production qty.

    For each BOM file with qty > 0:  part_required += bom_qty * production_qty

    If the same VPN appears twice in a BOM file, the second row is treated as
    an alternative manufacturer (MFR Name 2 / MPN 2).

    Returns a DataFrame with one row per unique Vendor Part Number.
    """
    parts = []
    second_mfr_parts = []
    brd_vpn_set: set = set()

    for bom_name, df in bom_dfs.items():
        prod_qty = int(qty_map.get(bom_name, 0))
        if prod_qty <= 0:
            continue
        brd_vpn_set |= get_brd_vpns(df)

        available_extra = [c for c in [BOM_DESC_COL, BOM_MFR_COL, BOM_MPN_COL] if c in df.columns]
        keep_cols = [BOM_VPN_COL, BOM_QTY_COL] + available_extra
        temp = df[keep_cols].copy()

        # Drop rows with empty VPN
        temp = temp[
            temp[BOM_VPN_COL].notna()
            & (temp[BOM_VPN_COL] != "")
            & (temp[BOM_VPN_COL].str.lower() != "nan")
        ].reset_index(drop=True)

        # Extract second-occurrence rows as alternative manufacturer data
        # Only keep if MFR Name or MPN is different from the first row
        if BOM_MFR_COL in temp.columns and BOM_MPN_COL in temp.columns:
            temp["_rank"] = temp.groupby(BOM_VPN_COL).cumcount()
            first  = temp[temp["_rank"] == 0][[BOM_VPN_COL, BOM_MFR_COL, BOM_MPN_COL]].copy()
            second = temp[temp["_rank"] == 1][[BOM_VPN_COL, BOM_MFR_COL, BOM_MPN_COL]].copy()
            if not second.empty:
                # Only include rows where manufacturer OR MPN differs from first row
                merged_check = second.merge(
                    first.rename(columns={BOM_MFR_COL: "_mfr1", BOM_MPN_COL: "_mpn1"}),
                    on=BOM_VPN_COL, how="left"
                )
                is_different = (
                    (merged_check[BOM_MFR_COL].str.strip() != merged_check["_mfr1"].str.strip()) |
                    (merged_check[BOM_MPN_COL].str.strip() != merged_check["_mpn1"].str.strip())
                )
                second = second[is_different.values]
                if not second.empty:
                    second_mfr_parts.append(second)
            temp = temp[temp["_rank"] == 0].drop(columns=["_rank"])

        temp[COL_REQUIRED] = temp[BOM_QTY_COL] * prod_qty
        label = bom_name.replace(".xlsx", "")
        temp[COL_BREAKDOWN] = f"{label}×{prod_qty}"
        parts.append(temp)

    if not parts:
        return pd.DataFrame(columns=[BOM_VPN_COL, BOM_DESC_COL, BOM_MFR_COL, BOM_MPN_COL,
                                      COL_REQUIRED, COL_BREAKDOWN])

    combined = pd.concat(parts, ignore_index=True)

    agg_dict: dict = {
        COL_REQUIRED: "sum",
        COL_BREAKDOWN: lambda x: " | ".join(x.unique()),
    }
    for col in [BOM_DESC_COL, BOM_MFR_COL, BOM_MPN_COL]:
        if col in combined.columns:
            agg_dict[col] = "first"

    grouped = combined.groupby(BOM_VPN_COL, sort=False).agg(agg_dict).reset_index()

    # Ensure all description/mfr/mpn columns exist
    for col in [BOM_DESC_COL, BOM_MFR_COL, BOM_MPN_COL]:
        if col not in grouped.columns:
            grouped[col] = ""

    # Tag VPNs that are children of BRD assemblies
    grouped["Under BRD"] = grouped[BOM_VPN_COL].isin(brd_vpn_set)

    # Merge alternative manufacturer data (second BOM row per VPN)
    if second_mfr_parts:
        second_mfr_df = (
            pd.concat(second_mfr_parts, ignore_index=True)
            .rename(columns={BOM_MFR_COL: "MFR Name 2", BOM_MPN_COL: "MPN 2"})
            .drop_duplicates(subset=BOM_VPN_COL)
        )
        grouped = grouped.merge(second_mfr_df, on=BOM_VPN_COL, how="left")

    return grouped


def calculate_results(
    required_df: pd.DataFrame,
    inventory_df: pd.DataFrame,
    price_df: pd.DataFrame,
    type_df: pd.DataFrame,
) -> pd.DataFrame:
    """Merge all data sources and compute procurement columns."""
    if required_df.empty:
        return pd.DataFrame()

    df = required_df.copy()
    df[COL_REQUIRED] = pd.to_numeric(df[COL_REQUIRED], errors="coerce").fillna(0)

    # ── Inventory ──────────────────────────────────────────────────────────────
    if not inventory_df.empty and INV_KEY_COL in inventory_df.columns:
        inv = (
            inventory_df[[INV_KEY_COL, INV_QTY_COL]]
            .rename(columns={INV_KEY_COL: BOM_VPN_COL, INV_QTY_COL: COL_IN_STOCK})
            .drop_duplicates(subset=BOM_VPN_COL)
        )
        df = df.merge(inv, on=BOM_VPN_COL, how="left")
    else:
        df[COL_IN_STOCK] = 0.0

    df[COL_IN_STOCK] = pd.to_numeric(df[COL_IN_STOCK], errors="coerce").fillna(0)

    # ── Prices ─────────────────────────────────────────────────────────────────
    if not price_df.empty and PRICE_KEY_COL in price_df.columns:
        prices = (
            price_df[[PRICE_KEY_COL, PRICE_USD_COL]]
            .rename(columns={PRICE_KEY_COL: BOM_VPN_COL, PRICE_USD_COL: COL_UNIT_PRICE})
            .drop_duplicates(subset=BOM_VPN_COL)
        )
        df = df.merge(prices, on=BOM_VPN_COL, how="left")
    else:
        df[COL_UNIT_PRICE] = float("nan")

    # ── Types ──────────────────────────────────────────────────────────────────
    if not type_df.empty and TYPE_KEY_COL in type_df.columns:
        types = (
            type_df[[TYPE_KEY_COL, TYPE_COL]]
            .rename(columns={TYPE_KEY_COL: BOM_VPN_COL, TYPE_COL: "Type"})
            .drop_duplicates(subset=BOM_VPN_COL)
        )
        df = df.merge(types, on=BOM_VPN_COL, how="left")
    else:
        df["Type"] = "—"

    df["Type"] = df["Type"].fillna("—")

    # ── Calculations ───────────────────────────────────────────────────────────
    df[COL_TO_ORDER] = (df[COL_REQUIRED] - df[COL_IN_STOCK]).clip(lower=0)

    has_price = df[COL_UNIT_PRICE].notna() & (df[COL_UNIT_PRICE] > 0)
    df[COL_TOTAL_COST] = float("nan")
    df[COL_ORDER_COST] = float("nan")
    df.loc[has_price, COL_TOTAL_COST] = (
        df.loc[has_price, COL_UNIT_PRICE] * df.loc[has_price, COL_REQUIRED]
    )
    df.loc[has_price, COL_ORDER_COST] = (
        df.loc[has_price, COL_UNIT_PRICE] * df.loc[has_price, COL_TO_ORDER]
    )

    # ── Status ─────────────────────────────────────────────────────────────────
    def _status(row: pd.Series) -> str:
        missing = row[COL_TO_ORDER] > 0
        no_price = pd.isna(row[COL_UNIT_PRICE]) or row[COL_UNIT_PRICE] <= 0
        if missing and no_price:
            return "🔴 Missing ⚠️ No Price"
        elif missing:
            return "🔴 Missing"
        elif no_price:
            return "⚠️ No Price"
        else:
            return "✅ In Stock"

    df[COL_STATUS] = df.apply(_status, axis=1)

    # ── Column order ───────────────────────────────────────────────────────────
    ordered_cols = [
        BOM_VPN_COL,
        BOM_DESC_COL,
        BOM_MFR_COL,
        BOM_MPN_COL,
        "MFR Name 2",
        "MPN 2",
        "Type",
        COL_REQUIRED,
        COL_IN_STOCK,
        COL_TO_ORDER,
        COL_UNIT_PRICE,
        COL_TOTAL_COST,
        COL_ORDER_COST,
        COL_STATUS,
        COL_BREAKDOWN,
        "Under BRD",
    ]
    existing = [c for c in ordered_cols if c in df.columns]
    return df[existing].reset_index(drop=True)


def get_kpis(results_df: pd.DataFrame) -> dict:
    """Derive summary KPIs from the results DataFrame."""
    if results_df.empty:
        return {
            "total_parts": 0,
            "in_stock_count": 0,
            "missing_count": 0,
            "availability_pct": 0.0,
            "no_price_count": 0,
            "total_procurement_cost": 0.0,
            "order_cost": 0.0,
        }

    total = len(results_df)
    missing = int((results_df[COL_TO_ORDER] > 0).sum())
    in_stock = total - missing

    has_price = results_df[COL_UNIT_PRICE].notna() & (results_df[COL_UNIT_PRICE] > 0)
    no_price = int((~has_price).sum())

    total_cost = float(results_df.loc[has_price, COL_TOTAL_COST].sum())
    order_cost = float(results_df.loc[has_price, COL_ORDER_COST].sum())

    return {
        "total_parts": total,
        "in_stock_count": in_stock,
        "missing_count": missing,
        "availability_pct": round(in_stock / total * 100, 1) if total > 0 else 0.0,
        "no_price_count": no_price,
        "total_procurement_cost": total_cost,
        "order_cost": order_cost,
    }


def get_brd_order_summary(
    bom_dfs: dict,
    qty_map: dict,
    inventory_df,
    price_df,
):
    """Calculate per-BRD order cost (missing parts only) and total BOM cost.

    Walks the level hierarchy inside each SYS-* BOM to extract components
    that sit under each BRD row — same approach as the BRD Assembly page.
    No separate BRD sub-BOM files are required.

    Returns a DataFrame with columns:
        BRD P/N, Description, Systems, Total BRD Qty,
        Order Cost $, Total BOM Cost $, Note
    """
    import pandas as _pd

    def _parse_level(val) -> int:
        s = str(val).strip().lstrip(".")
        try:
            return int(float(s))
        except (ValueError, TypeError):
            return 999

    def _extract_brd_components(sys_df, brd_vpn: str):
        """Return all rows nested under brd_vpn in sys_df (by level hierarchy)."""
        rows = []
        in_brd = False
        brd_level = None
        for _, row in sys_df.iterrows():
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
        return _pd.DataFrame(rows).reset_index(drop=True) if rows else _pd.DataFrame()

    # ── Build fast lookups ────────────────────────────────────────────────────
    # Build inv_lookup by iterating rows (same approach as BRD Assembly page)
    # to avoid silent failures that can occur with groupby on mixed-type columns.
    inv_lookup: dict = {}
    if not inventory_df.empty and INV_KEY_COL in inventory_df.columns and INV_QTY_COL in inventory_df.columns:
        for _, _r in inventory_df.iterrows():
            _k = str(_r[INV_KEY_COL]).strip()
            _v = _pd.to_numeric(_r.get(INV_QTY_COL, 0), errors="coerce")
            if _k and _k.lower() not in ("nan", "none", "") and _pd.notna(_v):
                inv_lookup[_k] = inv_lookup.get(_k, 0) + float(_v)

    price_lookup: dict = {}
    if not price_df.empty and PRICE_KEY_COL in price_df.columns:
        _pr = price_df[[PRICE_KEY_COL, PRICE_USD_COL]].copy()
        _pr[PRICE_KEY_COL] = _pr[PRICE_KEY_COL].astype(str).str.strip()
        _pr[PRICE_USD_COL] = _pd.to_numeric(_pr[PRICE_USD_COL], errors="coerce").fillna(0)
        _pr = _pr[_pr[PRICE_USD_COL] > 0].drop_duplicates(subset=PRICE_KEY_COL)
        price_lookup = _pr.set_index(PRICE_KEY_COL)[PRICE_USD_COL].to_dict()

    rows = []

    for sys_name, sys_df in bom_dfs.items():
        if not str(sys_name).upper().startswith("SYS-"):
            continue
        sys_qty = int(qty_map.get(sys_name, 0))
        if sys_qty <= 0:
            continue

        brd_mask = (
            sys_df[BOM_VPN_COL].astype(str).str.strip().str.upper().str.startswith("BRD")
        )
        brd_rows_in_sys = sys_df[brd_mask]

        seen_brd: set = set()
        for _, brd_row in brd_rows_in_sys.iterrows():
            brd_vpn = str(brd_row[BOM_VPN_COL]).strip()
            # Only BRD VPNs: "BRD" + 6 digits + optional letter suffix
            # e.g. BRD100700, BRD400004A, BRD400004B  (min 9 chars, max 10)
            # Exclude VPNs ending in T (test/template boards)
            import re as _re
            if not _re.match(r'^BRD\d{6}[A-Za-z]?$', brd_vpn):
                continue
            if brd_vpn.upper().endswith('T'):
                continue
            if brd_vpn in seen_brd:
                continue
            seen_brd.add(brd_vpn)

            brd_qty_in_sys = float(
                _pd.to_numeric(brd_row.get(BOM_QTY_COL, 1), errors="coerce") or 1
            )
            total_brd_qty = brd_qty_in_sys * sys_qty
            brd_desc = str(brd_row.get(BOM_DESC_COL, ""))

            comp_df = _extract_brd_components(sys_df, brd_vpn)

            if comp_df.empty:
                rows.append({
                    "System": sys_name,
                    "BRD P/N": brd_vpn,
                    "Description": brd_desc,
                    "Qty/System": brd_qty_in_sys,
                    "Total BRD Qty": total_brd_qty,
                    "Order Cost $": 0.0,
                    "Total BOM Cost $": 0.0,
                    "Note": "⚠️ No components found",
                })
                continue

            brd_order_cost = 0.0
            brd_total_cost = 0.0

            for _, comp in comp_df.iterrows():
                comp_vpn = str(comp.get(BOM_VPN_COL, "")).strip()
                if not comp_vpn or comp_vpn.lower() == "nan":
                    continue
                comp_qty = float(
                    _pd.to_numeric(comp.get(BOM_QTY_COL, 0), errors="coerce") or 0
                )
                required_qty = comp_qty * total_brd_qty
                price = float(price_lookup.get(comp_vpn, 0))
                if price <= 0:
                    continue
                stock = float(inv_lookup.get(comp_vpn, 0))
                to_order = max(0.0, required_qty - stock)
                brd_order_cost += to_order * price
                brd_total_cost += required_qty * price

            rows.append({
                "System": sys_name,
                "BRD P/N": brd_vpn,
                "Description": brd_desc,
                "Qty/System": brd_qty_in_sys,
                "Total BRD Qty": total_brd_qty,
                "Order Cost $": brd_order_cost,
                "Total BOM Cost $": brd_total_cost,
                "Note": "✅",
            })

    if not rows:
        return _pd.DataFrame()

    df = _pd.DataFrame(rows)

    # Group by BRD P/N — each BRD appears only once, totals summed across systems
    grouped = (
        df.groupby("BRD P/N", sort=False)
        .agg(
            Description=("Description", "first"),
            Systems=("System", lambda x: " | ".join(sorted(x.unique()))),
            Total_BRD_Qty=("Total BRD Qty", "sum"),
            Order_Cost=("Order Cost $", "sum"),
            Total_BOM_Cost=("Total BOM Cost $", "sum"),
            Note=("Note", lambda x: next((v for v in x if "⚠️" in str(v)), "✅")),
        )
        .reset_index()
        .rename(columns={
            "Total_BRD_Qty": "Total BRD Qty",
            "Order_Cost": "Order Cost $",
            "Total_BOM_Cost": "Total BOM Cost $",
        })
    )

    return grouped[["BRD P/N", "Description", "Systems", "Total BRD Qty", "Order Cost $", "Total BOM Cost $", "Note"]]


def get_brd_components_detail(
    bom_dfs: dict,
    qty_map: dict,
    inventory_df,
    price_df,
) -> dict:
    """Return a dict {brd_vpn: DataFrame} — component rows for each BRD assembly.

    Each DataFrame has columns:
        VPN, Description, Manufacturer, MPN,
        Qty/BRD, Required Qty, In Stock, To Order,
        Unit Price $, Order Cost $, Total Cost $, Status
    """
    import pandas as _pd
    import re as _re

    def _parse_level(val) -> int:
        s = str(val).strip().lstrip(".")
        try:
            return int(float(s))
        except (ValueError, TypeError):
            return 999

    def _extract_brd_components(sys_df, brd_vpn: str):
        rows = []
        in_brd = False
        brd_level = None
        for _, row in sys_df.iterrows():
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
        return _pd.DataFrame(rows).reset_index(drop=True) if rows else _pd.DataFrame()

    # ── Lookups ───────────────────────────────────────────────────────────────
    inv_lookup: dict = {}
    if not inventory_df.empty and INV_KEY_COL in inventory_df.columns:
        for _, _r in inventory_df.iterrows():
            _k = str(_r[INV_KEY_COL]).strip()
            _v = _pd.to_numeric(_r.get(INV_QTY_COL, 0), errors="coerce")
            if _k and _k.lower() not in ("nan", "none", "") and _pd.notna(_v):
                inv_lookup[_k] = inv_lookup.get(_k, 0) + float(_v)

    price_lookup: dict = {}
    if not price_df.empty and PRICE_KEY_COL in price_df.columns:
        _pr = price_df[[PRICE_KEY_COL, PRICE_USD_COL]].copy()
        _pr[PRICE_KEY_COL] = _pr[PRICE_KEY_COL].astype(str).str.strip()
        _pr[PRICE_USD_COL] = _pd.to_numeric(_pr[PRICE_USD_COL], errors="coerce").fillna(0)
        _pr = _pr[_pr[PRICE_USD_COL] > 0].drop_duplicates(subset=PRICE_KEY_COL)
        price_lookup = _pr.set_index(PRICE_KEY_COL)[PRICE_USD_COL].to_dict()

    brd_comp_rows: dict = {}  # brd_vpn -> list of row dicts

    for sys_name, sys_df in bom_dfs.items():
        if not str(sys_name).upper().startswith("SYS-"):
            continue
        sys_qty = int(qty_map.get(sys_name, 0))
        if sys_qty <= 0:
            continue

        brd_mask = sys_df[BOM_VPN_COL].astype(str).str.strip().str.upper().str.startswith("BRD")
        seen_brd: set = set()

        for _, brd_row in sys_df[brd_mask].iterrows():
            brd_vpn = str(brd_row[BOM_VPN_COL]).strip()
            if not _re.match(r'^BRD\d{6}[A-Za-z]?$', brd_vpn):
                continue
            if brd_vpn.upper().endswith('T'):
                continue
            if brd_vpn in seen_brd:
                continue
            seen_brd.add(brd_vpn)

            brd_qty_in_sys = float(_pd.to_numeric(brd_row.get(BOM_QTY_COL, 1), errors="coerce") or 1)
            total_brd_qty = brd_qty_in_sys * sys_qty

            comp_df = _extract_brd_components(sys_df, brd_vpn)
            if comp_df.empty:
                continue

            for _, comp in comp_df.iterrows():
                comp_vpn = str(comp.get(BOM_VPN_COL, "")).strip()
                if not comp_vpn or comp_vpn.lower() == "nan":
                    continue
                comp_qty = float(_pd.to_numeric(comp.get(BOM_QTY_COL, 0), errors="coerce") or 0)
                required_qty = comp_qty * total_brd_qty
                price = float(price_lookup.get(comp_vpn, 0))
                stock = float(inv_lookup.get(comp_vpn, 0))
                to_order = max(0.0, required_qty - stock)
                order_cost = to_order * price if price > 0 else float("nan")
                total_cost = required_qty * price if price > 0 else float("nan")

                if to_order > 0 and price <= 0:
                    status = "🔴 Missing ⚠️ No Price"
                elif to_order > 0:
                    status = "🔴 Missing"
                elif price <= 0:
                    status = "⚠️ No Price"
                else:
                    status = "✅ In Stock"

                brd_comp_rows.setdefault(brd_vpn, []).append({
                    "VPN": comp_vpn,
                    "Description": str(comp.get(BOM_DESC_COL, "")),
                    "Manufacturer": str(comp.get(BOM_MFR_COL, "")),
                    "MPN": str(comp.get(BOM_MPN_COL, "")),
                    "Qty/BRD": comp_qty,
                    "Required Qty": required_qty,
                    "In Stock": stock,
                    "To Order": to_order,
                    "Unit Price $": price if price > 0 else float("nan"),
                    "Order Cost $": order_cost,
                    "Total Cost $": total_cost,
                    "Status": status,
                })

    # Convert lists → DataFrames, aggregate duplicate VPNs
    result: dict = {}
    for brd_vpn, rows in brd_comp_rows.items():
        df = _pd.DataFrame(rows)
        agg = (
            df.groupby("VPN", sort=False)
            .agg(
                Description=("Description", "first"),
                Manufacturer=("Manufacturer", "first"),
                MPN=("MPN", "first"),
                Qty_BRD=("Qty/BRD", "first"),
                Required_Qty=("Required Qty", "sum"),
                In_Stock=("In Stock", "first"),
                To_Order=("To Order", "sum"),
                Unit_Price=("Unit Price $", "first"),
                Order_Cost=("Order Cost $", "sum"),
                Total_Cost=("Total Cost $", "sum"),
                Status=("Status", "first"),
            )
            .reset_index()
            .rename(columns={
                "Qty_BRD": "Qty/BRD",
                "Required_Qty": "Required Qty",
                "In_Stock": "In Stock",
                "To_Order": "To Order",
                "Unit_Price": "Unit Price $",
                "Order_Cost": "Order Cost $",
                "Total_Cost": "Total Cost $",
            })
        )
        result[brd_vpn] = agg

    return result
