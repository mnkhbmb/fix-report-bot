"""
sheets.py — Google Sheets клиент (3 tab)

[Repairs]   — Засварлаж байгаа REP бүртгэл
[Fixed]     — Дууссан REP бүртгэл (тайлбартай)
[Shipments] — SHP багцын бүртгэл

Repairs баганууд:
  A: REP ID   B: SHP ID   C: Салбар   D: Зүйл   E: Тоо
  F: Бүртгэсэн   G: Огноо   H: Статус

Fixed баганууд:
  A: REP ID   B: SHP ID   C: Салбар   D: Зүйл   E: Тоо
  F: Бүртгэсэн   G: Бүртгэсэн огноо
  H: Засварласан хүн   I: Засварласан огноо   J: Тайлбар

Shipments баганууд:
  A: SHP ID   B: Салбар   C: Бүртгэсэн   D: Огноо
  E: Статус   F: Хүлээж авсан хүн   G: Хүлээж авсан огноо   H: Тайлбар
"""

import os
import re
from datetime import datetime
from typing import Optional
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import os
from dotenv import load_dotenv  # ← нэмнэ

load_dotenv()  # ← нэмнэ


SCOPES     = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_ID   = os.environ["GOOGLE_SHEET_ID"]
CREDS_FILE = os.environ.get("GOOGLE_CREDS_FILE", "credentials.json")

TAB_REP = "Repairs"
TAB_FIX = "Fixed"
TAB_SHP = "Shipments"

REP_HEADERS = [
    "REP ID", "SHP ID", "Салбар", "Зүйл", "Тоо",
    "Бүртгэсэн", "Огноо", "Статус"
]
FIX_HEADERS = [
    "REP ID", "SHP ID", "Салбар", "Зүйл", "Тоо",
    "Бүртгэсэн", "Бүртгэсэн огноо",
    "Засварласан хүн", "Засварласан огноо", "Тайлбар"
]
SHP_HEADERS = [
    "SHP ID", "Салбар", "Бүртгэсэн", "Огноо",
    "Статус", "Хүлээж авсан хүн", "Хүлээж авсан огноо", "Тайлбар"
]

# Repairs баганы индекс
R_ID, R_SHP, R_BRANCH, R_ITEM, R_QTY, R_BY, R_DATE, R_STATUS = range(8)

# Fixed баганы индекс
F_ID, F_SHP, F_BRANCH, F_ITEM, F_QTY, F_BY, F_DATE, F_FIX_BY, F_FIX_DATE, F_NOTES = range(10)

# Shipments баганы индекс
S_ID, S_BRANCH, S_BY, S_DATE, S_STATUS, S_REC_BY, S_REC_DATE, S_NOTES = range(8)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")

def _safe(row: list, idx: int) -> str:
    return row[idx] if len(row) > idx else ""


class SheetsClient:
    def __init__(self):
        creds = Credentials.from_service_account_file(CREDS_FILE, scopes=SCOPES)
        svc = build("sheets", "v4", credentials=creds)
        self.svc = svc.spreadsheets()
        self._ensure_tabs()

    # ── Дотоод тусламж ────────────────────────────────────────────────────────

    def _ensure_tabs(self):
        meta = self.svc.get(spreadsheetId=SHEET_ID).execute()
        existing = {s["properties"]["title"] for s in meta["sheets"]}
        new_tabs = [
            t for t in [TAB_REP, TAB_FIX, TAB_SHP] if t not in existing
        ]
        if new_tabs:
            self.svc.batchUpdate(
                spreadsheetId=SHEET_ID,
                body={"requests": [
                    {"addSheet": {"properties": {"title": t}}} for t in new_tabs
                ]}
            ).execute()
        for tab, headers in [(TAB_REP, REP_HEADERS), (TAB_FIX, FIX_HEADERS), (TAB_SHP, SHP_HEADERS)]:
            self._ensure_header(tab, headers)

    def _ensure_header(self, tab: str, headers: list):
        rows = self._get_rows(tab)
        if not rows or rows[0] != headers:
            self.svc.values().update(
                spreadsheetId=SHEET_ID,
                range=f"{tab}!A1",
                valueInputOption="RAW",
                body={"values": [headers]}
            ).execute()

    def _get_rows(self, tab: str) -> list:
        result = self.svc.values().get(
            spreadsheetId=SHEET_ID,
            range=f"{tab}!A:Z"
        ).execute()
        return result.get("values", [])

    def _append_row(self, tab: str, row: list):
        self.svc.values().append(
            spreadsheetId=SHEET_ID,
            range=f"{tab}!A:A",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]}
        ).execute()

    def _update_cell(self, tab: str, row_num: int, col: str, value: str):
        self.svc.values().update(
            spreadsheetId=SHEET_ID,
            range=f"{tab}!{col}{row_num}",
            valueInputOption="RAW",
            body={"values": [[value]]}
        ).execute()

    def _delete_row(self, tab: str, row_num: int):
        """Sheet-ийн тухайн мөрийг устгана (1-based)."""
        meta = self.svc.get(spreadsheetId=SHEET_ID).execute()
        sheet_id = next(
            s["properties"]["sheetId"]
            for s in meta["sheets"]
            if s["properties"]["title"] == tab
        )
        self.svc.batchUpdate(
            spreadsheetId=SHEET_ID,
            body={"requests": [{
                "deleteDimension": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "ROWS",
                        "startIndex": row_num - 1,   # 0-based
                        "endIndex":   row_num         # exclusive
                    }
                }
            }]}
        ).execute()

    def _next_id(self, tab: str, prefix: str) -> str:
        rows = self._get_rows(tab)
        max_n = 0
        pattern = re.compile(rf"^{prefix}-(\d+)$")
        for row in rows[1:]:
            if row:
                m = pattern.match(row[0])
                if m:
                    max_n = max(max_n, int(m.group(1)))

        # Fixed tab-д ч REP ID байж болно → хоёуланг шалгана
        if prefix == "REP":
            fix_rows = self._get_rows(TAB_FIX)
            for row in fix_rows[1:]:
                if row:
                    m = pattern.match(row[0])
                    if m:
                        max_n = max(max_n, int(m.group(1)))

        return f"{prefix}-{(max_n + 1):04d}"

    def _find_row(self, tab: str, col_idx: int, value: str) -> Optional[int]:
        """Тухайн утгатай мөрийн дугаарыг буцаана (1-based)."""
        rows = self._get_rows(tab)
        for i, row in enumerate(rows):
            if len(row) > col_idx and row[col_idx] == value:
                return i + 1
        return None

    # ── Нийтийн методууд ──────────────────────────────────────────────────────

    def create_shipment(self, branch: str, items: list[dict],
                        reported_by: str, notes: str = "") -> tuple[str, list[dict]]:
        """SHP үүсгэж, зүйл бүрт REP үүсгэнэ."""
        shp_id = self._next_id(TAB_SHP, "SHP")
        now    = _now()

        self._append_row(TAB_SHP, [
            shp_id, branch, reported_by, now,
            "Илгээсэн", "", "", notes
        ])

        created = []
        for it in items:
            rep_id = self._next_id(TAB_REP, "REP")
            self._append_row(TAB_REP, [
                rep_id, shp_id, branch,
                it["item"], str(it["qty"]),
                reported_by, now,
                "Хүлээгдэж байна"
            ])
            created.append({"rep_id": rep_id, "qty": it["qty"], "item": it["item"]})

        return shp_id, created

    def mark_received(self, shp_id: str, received_by: str) -> Optional[dict]:
        """SHP + бүх холбоотой REP → 'Хүлээж авсан'."""
        shp_row = self._find_row(TAB_SHP, S_ID, shp_id)
        if shp_row is None:
            return None

        shp_data = self._get_rows(TAB_SHP)[shp_row - 1]
        now = _now()

        self._update_cell(TAB_SHP, shp_row, "E", "Хүлээж авсан")
        self._update_cell(TAB_SHP, shp_row, "F", received_by)
        self._update_cell(TAB_SHP, shp_row, "G", now)

        rep_rows = self._get_rows(TAB_REP)
        reps_info = []
        for i, row in enumerate(rep_rows[1:], start=2):
            if _safe(row, R_SHP) == shp_id:
                self._update_cell(TAB_REP, i, "H", "Хүлээж авсан")
                reps_info.append({
                    "rep_id": _safe(row, R_ID),
                    "qty":    _safe(row, R_QTY),
                    "item":   _safe(row, R_ITEM)
                })

        return {"branch": _safe(shp_data, S_BRANCH), "reps": reps_info}

    def mark_fixed(self, rep_id: str, fixed_by: str, notes: str = "") -> Optional[dict]:
        """
        REP-ийг Repairs tab-аас устгаж Fixed tab-д нэмнэ.
        SHP дотор бүх REP дуусвал SHP → 'Дууссан'.
        """
        rep_row_num = self._find_row(TAB_REP, R_ID, rep_id)
        if rep_row_num is None:
            return None   # аль хэдийн fixed эсвэл олдсонгүй

        rep_rows   = self._get_rows(TAB_REP)
        rep_data   = rep_rows[rep_row_num - 1]
        shp_id     = _safe(rep_data, R_SHP)
        branch     = _safe(rep_data, R_BRANCH)
        item       = _safe(rep_data, R_ITEM)
        qty        = _safe(rep_data, R_QTY)
        orig_by    = _safe(rep_data, R_BY)
        orig_date  = _safe(rep_data, R_DATE)
        now        = _now()

        # 1. Fixed tab-д нэмнэ
        self._append_row(TAB_FIX, [
            rep_id, shp_id, branch, item, qty,
            orig_by, orig_date,
            fixed_by, now, notes
        ])

        # 2. Repairs tab-аас устгана
        self._delete_row(TAB_REP, rep_row_num)

        # 3. SHP дууссан эсэхийг шалгана
        remaining = self._count_active_reps(shp_id)
        shp_status = "done" if remaining == 0 else "partial"

        if remaining == 0:
            shp_row = self._find_row(TAB_SHP, S_ID, shp_id)
            if shp_row:
                self._update_cell(TAB_SHP, shp_row, "E", "Дууссан")

        return {
            "item":       item,
            "qty":        qty,
            "branch":     branch,
            "shp_id":     shp_id,
            "shp_status": shp_status,
            "remaining":  remaining
        }

    def _count_active_reps(self, shp_id: str) -> int:
        """Repairs tab-д тухайн SHP-ийн үлдсэн REP тоо."""
        rows = self._get_rows(TAB_REP)
        return sum(1 for row in rows[1:] if _safe(row, R_SHP) == shp_id)

    def get_shipment_status(self, shp_id: str) -> Optional[dict]:
        shp_row = self._find_row(TAB_SHP, S_ID, shp_id)
        if shp_row is None:
            return None

        shp_data = self._get_rows(TAB_SHP)[shp_row - 1]
        reps = []

        # Repairs tab (идэвхтэй)
        for row in self._get_rows(TAB_REP)[1:]:
            if _safe(row, R_SHP) == shp_id:
                reps.append({
                    "rep_id":   _safe(row, R_ID),
                    "item":     _safe(row, R_ITEM),
                    "qty":      _safe(row, R_QTY),
                    "status":   _safe(row, R_STATUS),
                    "location": "repair"
                })

        # Fixed tab (дууссан)
        for row in self._get_rows(TAB_FIX)[1:]:
            if _safe(row, F_SHP) == shp_id:
                reps.append({
                    "rep_id":   _safe(row, F_ID),
                    "item":     _safe(row, F_ITEM),
                    "qty":      _safe(row, F_QTY),
                    "status":   "Засварласан",
                    "location": "fixed"
                })

        return {
            "shp_id":       shp_id,
            "branch":       _safe(shp_data, S_BRANCH),
            "status":       _safe(shp_data, S_STATUS),
            "created_date": _safe(shp_data, S_DATE),
            "reps":         reps
        }

    def get_repair_status(self, rep_id: str) -> Optional[dict]:
        # Эхлээд Repairs tab-аас хайна
        row_num = self._find_row(TAB_REP, R_ID, rep_id)
        if row_num is not None:
            row = self._get_rows(TAB_REP)[row_num - 1]
            return {
                "rep_id":   rep_id,
                "shp_id":   _safe(row, R_SHP),
                "branch":   _safe(row, R_BRANCH),
                "item":     _safe(row, R_ITEM),
                "qty":      _safe(row, R_QTY),
                "status":   _safe(row, R_STATUS),
                "location": "repair",
                "notes":    ""
            }

        # Fixed tab-аас хайна
        row_num = self._find_row(TAB_FIX, F_ID, rep_id)
        if row_num is not None:
            row = self._get_rows(TAB_FIX)[row_num - 1]
            return {
                "rep_id":   rep_id,
                "shp_id":   _safe(row, F_SHP),
                "branch":   _safe(row, F_BRANCH),
                "item":     _safe(row, F_ITEM),
                "qty":      _safe(row, F_QTY),
                "status":   "Засварласан",
                "location": "fixed",
                "notes":    _safe(row, F_NOTES)
            }

        return None
