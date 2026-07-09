"""_find_haalt_row-ийн блок+өдөр олох логикийн шалгалт (Google API хүрэхгүй)."""
import os
os.environ.setdefault("GOOGLE_SHEET_ID", "x")
os.environ.setdefault("GOOGLE_CREDS_FILE", "none")

from sheets import SheetsClient, TOO_HEADERS

rows = [
    ["Өглөө"], TOO_HEADERS, ["2026.7.1"], ["2026.7.2"],
    ["Орой"],  TOO_HEADERS, ["2026.7.1"], ["2026.7.2"],
]
assert SheetsClient._find_haalt_row(rows, "Өглөө", "2026.7.1") == 3
assert SheetsClient._find_haalt_row(rows, "Орой",  "2026.7.2") == 8
assert SheetsClient._find_haalt_row(rows, "Орой",  "2026.7.9") is None
print("ok")
