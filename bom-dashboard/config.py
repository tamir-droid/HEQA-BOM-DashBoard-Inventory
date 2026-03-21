from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent
DATA_DIR = PROJECT_ROOT.parent / "data"
LOGO_PATH = PROJECT_ROOT / "logo.png"
PCBA_ICON_PATH = PROJECT_ROOT / "pcba_icon.png"

# ── BOM columns ───────────────────────────────────────────────────────────────
BOM_SHEET = "DataSheet"
BOM_LEVEL_COL = "Level"
BOM_VPN_COL = "Vendor Part Number"
BOM_QTY_COL = "Quantity"
BOM_DESC_COL = "Description"
BOM_MFR_COL = "Manufacturer"
BOM_MPN_COL = "Manufacturer Part Number"
BOM_FIND_NUM_COL = "Find Number"

# ── Inventory columns ─────────────────────────────────────────────────────────
INV_SHEET = "Sheet1"
INV_KEY_COL = 'מק"ט חדש\nמדבר'
INV_QTY_COL = "כמות"

# ── Price columns ─────────────────────────────────────────────────────────────
PRICE_SHEET = "DataSheet"
PRICE_KEY_COL = 'מק"ט'
PRICE_USD_COL = "עלות תקן USD"

# ── Type columns ──────────────────────────────────────────────────────────────
TYPE_SHEET = "DataSheet"
TYPE_KEY_COL = 'מק"ט'
TYPE_COL = "טיפוס P/R/O"

# ── Known support file names ──────────────────────────────────────────────────
INV_FILENAME = "Inventory.xlsx"
PRICE_FILENAME = "item cost.xlsx"
TYPE_FILENAME = "Buy & Make.xlsx"
COMBINED_BOM_FILENAME = "ALL_BOMS.xlsx"
BRD_SUB_INV_FILENAME = "BRD_Sub_Inv.xlsx"
SUPPORT_FILES = {INV_FILENAME, PRICE_FILENAME, TYPE_FILENAME, COMBINED_BOM_FILENAME, BRD_SUB_INV_FILENAME,
                 "All Boms.xlsx", "All BOMs.xlsx", "all boms.xlsx"}

# ── Session state keys ────────────────────────────────────────────────────────
SS_DATA = "data"
SS_RESULTS = "results"
SS_AUTH = "authenticated"
SS_MUST_CHANGE_PW = "must_change_pw"
SS_CURRENT_USER = "current_user"
SS_IS_ADMIN = "is_admin"
SS_FOLLOWUP = "followup"
SS_SITE_INV = "site_inventory"
