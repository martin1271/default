# -*- coding: utf-8 -*-
"""
build_roster.py
================
產生一個「互動式員工排更表」Excel 檔 (.xlsx)。

設計重點 (Design notes)
-----------------------
* 全部以「公式 + 下拉選單 + 條件式格式 (顏色)」完成互動效果，**完全不需要 VBA / Macro**。
  因此檔案是純 .xlsx，任何人打開都安全、可用，不會有巨集警告。
* 「真實資料來源」是 `員工更表輸入` 這一頁：你只需要在這裡輸入每位員工每天的
  上班 / 下班 / 飯鐘時間。其餘所有頁面 (主排更表、Summary) 都會用公式自動更新。
* 為何主排更表不是用「人手填下拉選單」而是自動帶出？
  因為需求 1 (格仔可選人) 與需求 2 (由輸入區自動填入主表) 在「沒有 Macro」的前提下
  其實是互相衝突的：一個格仔不能同時是「公式」又是「可手動輸入的下拉選單」。
  自動帶出的做法更強大、更不易出錯，所以主排更表採用「自動計算 + 顏色提示」。
  你只在輸入區用下拉選單選時間即可。

可調整的設定 (在 `設定 Settings` 頁)
-----------------------------------
即時生效 (改完馬上更新，不用重跑程式)：
  - 員工名稱
  - 每個時段最低人手 (預設 1)
  - 特別時段人手規則 (例如午市 / 晚市 / 週末需要 2 人)
需要重跑本程式才會生效 (因為會改變表格的格線數量)：
  - 每日開始 / 結束時間
  - 時間間隔 (15 或 30 分鐘)

執行方式 (How to run)
---------------------
    python3 scripts/build_roster.py
會在專案根目錄產生 `排更表_Roster.xlsx`。
"""

from datetime import time
from openpyxl import Workbook
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.formatting.rule import CellIsRule, FormulaRule
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.utils import get_column_letter

try:
    # 用來標記「陣列公式」(Summary 頁列出無人覆蓋時段時需要)
    from openpyxl.worksheet.formula import ArrayFormula
    HAVE_ARRAY = True
except Exception:  # 舊版 openpyxl 沒有，退而求其次用普通公式 (Excel 365 仍可運作)
    HAVE_ARRAY = False


# ===========================================================================
# 1. 基本設定 (這些值會被「寫入」Settings 頁；改格線需要重跑本程式)
# ===========================================================================
OPEN_MIN   = 9 * 60 + 45     # 每日開始 09:45  -> 以「分鐘」表示
CLOSE_MIN  = 22 * 60 + 15    # 每日結束 22:15
INTERVAL   = 30              # 時間間隔 (分鐘)。選 30 分鐘：9:45~22:15 剛好 25 格，清晰好用。
DEFAULT_MIN_STAFF = 1        # 每個時段預設最低人手

EMPLOYEES = ["菁", "Kerry", "Ice", "Brielle"]   # 預設員工名單 (可在 Settings 改)

# 七天 (這個字串是所有頁面的「對應鍵」，必須完全一致)
DAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
WEEKEND = {"星期六", "星期日"}

OUTPUT = "排更表_Roster.xlsx"


# ===========================================================================
# 2. 顏色 / 樣式
# ===========================================================================
# 每位員工一個代表色 (與下方狀態色刻意分開，避免混淆)
EMP_COLORS = ["9DC3E6", "FFD966", "B4A7D6", "F4B6C2"]  # 藍 / 琥珀 / 紫 / 粉

# 狀態色
C_NOCOVER   = "FF9999"  # 紅：無人覆蓋
C_UNDER     = "FFC000"  # 橙：人手不足
C_OK        = "C6EFCE"  # 淺綠：正常
C_BREAK     = "D9D9D9"  # 灰：飯鐘 / 休息
C_HDR       = "4472C4"  # 表頭 (平日)
C_HDR_WKND  = "1F8A70"  # 表頭 (週末，不同底色)
C_TITLE     = "203864"
C_SECTION   = "D9E1F2"  # 區段標題底色
C_ERR       = "FFC7CE"  # 錯誤提示

THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
LEFT   = Alignment(horizontal="left", vertical="center", wrap_text=True)

TIME_FMT = "h:mm AM/PM"
HOUR_FMT = "0.00"


def fill(hex_color):
    return PatternFill("solid", fgColor=hex_color)


def hdr_font():
    return Font(bold=True, color="FFFFFF", size=11)


def fmt_label(minute):
    """把分鐘轉成 9:45am 這種標籤。"""
    h, m = divmod(minute, 60)
    ap = "am" if h < 12 else "pm"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d}{ap}"


def minute_to_time(minute):
    return time(minute // 60, minute % 60)


# 計算所有時段 (slot) 與所有「邊界時間」(供下拉選單用)
BOUNDARIES = list(range(OPEN_MIN, CLOSE_MIN + 1, INTERVAL))      # 含結束點
SLOT_STARTS = BOUNDARIES[:-1]                                    # 每個時段的開始
SLOT_LABELS = [f"{fmt_label(s)}-{fmt_label(s + INTERVAL)}" for s in SLOT_STARTS]
N_SLOTS = len(SLOT_STARTS)


# ===========================================================================
# 3. 建立 Workbook 與各頁
# ===========================================================================
wb = Workbook()

ws_inst = wb.active
ws_inst.title = "說明 Instructions"
ws_set  = wb.create_sheet("設定 Settings")
ws_in   = wb.create_sheet("員工更表輸入")
ws_sch  = wb.create_sheet("主排更表")
ws_sum  = wb.create_sheet("Summary")
ws_list = wb.create_sheet("Lists")   # 隱藏輔助頁 (下拉選單來源、時段時間值)

# 方便引用的頁名 (含中文，公式內要加單引號)
S_SET = "'設定 Settings'"
S_IN  = "'員工更表輸入'"
S_SCH = "'主排更表'"
S_LST = "Lists"


# ---------------------------------------------------------------------------
# 3a. Lists 頁：下拉選單來源 + 時段時間值 (給公式比較用)
# ---------------------------------------------------------------------------
ws_list["A1"] = "時間邊界 (下拉用)"
for i, b in enumerate(BOUNDARIES):
    c = ws_list.cell(row=2 + i, column=1, value=minute_to_time(b))
    c.number_format = TIME_FMT

ws_list["C1"] = "時段開始 (公式用)"
for i, s in enumerate(SLOT_STARTS):
    c = ws_list.cell(row=2 + i, column=3, value=minute_to_time(s))
    c.number_format = TIME_FMT

ws_list["E1"] = "時段標籤"
for i, lab in enumerate(SLOT_LABELS):
    ws_list.cell(row=2 + i, column=5, value=lab)

ws_list["G1"] = "星期"
for i, d in enumerate(DAYS):
    ws_list.cell(row=2 + i, column=7, value=d)

ws_list["I1"] = "適用對象"
APPLIES = ["全部", "平日", "週末"] + DAYS
for i, a in enumerate(APPLIES):
    ws_list.cell(row=2 + i, column=9, value=a)

# 定義名稱 (Defined Names)，讓跨頁下拉選單更穩定
from openpyxl.workbook.defined_name import DefinedName
def add_name(name, ref):
    try:
        wb.defined_names.add(DefinedName(name, attr_text=ref))
    except Exception:
        wb.defined_names[name] = DefinedName(name, attr_text=ref)

add_name("TimeList",    f"{S_LST}!$A$2:$A${1 + len(BOUNDARIES)}")
add_name("DayList",     f"{S_LST}!$G$2:$G${1 + len(DAYS)}")
add_name("AppliesList", f"{S_LST}!$I$2:$I${1 + len(APPLIES)}")

ws_list.sheet_state = "hidden"


# ---------------------------------------------------------------------------
# 3b. Settings 頁
# ---------------------------------------------------------------------------
def section_title(ws, cell, text):
    ws[cell] = text
    ws[cell].font = Font(bold=True, size=12, color=C_TITLE)
    ws[cell].fill = fill(C_SECTION)


ws_set["A1"] = "設定 Settings — 你可以在這裡修改參數"
ws_set["A1"].font = Font(bold=True, size=14, color="FFFFFF")
ws_set["A1"].fill = fill(C_TITLE)
ws_set.merge_cells("A1:E1")

# --- 員工名單 ---
section_title(ws_set, "A3", "① 員工名單 (可改名 / 即時生效)")
ws_set["A4"] = "員工"
ws_set["B4"] = "代表色"
ws_set["A4"].font = ws_set["B4"].font = Font(bold=True)
EMP_NAME_ROW0 = 5          # 員工名稱由 B5 開始 -> B5..B8
for k, (name, color) in enumerate(zip(EMPLOYEES, EMP_COLORS)):
    r = EMP_NAME_ROW0 + k
    ws_set.cell(row=r, column=1, value=name)               # A5.. 名稱 (可改)
    swatch = ws_set.cell(row=r, column=2, value="")        # B5.. 顏色示意
    swatch.fill = fill(color)
    swatch.border = BORDER
EMP_NAME_REF = [f"{S_SET}!$A${EMP_NAME_ROW0 + k}" for k in range(len(EMPLOYEES))]

# --- 營業時間 (改這裡要重跑程式) ---
section_title(ws_set, "A11", "② 營業 / 排班時間 (改後需重跑 Python 程式)")
ws_set["A12"] = "每日開始時間"
ws_set["B12"] = minute_to_time(OPEN_MIN);  ws_set["B12"].number_format = TIME_FMT
ws_set["A13"] = "每日結束時間"
ws_set["B13"] = minute_to_time(CLOSE_MIN); ws_set["B13"].number_format = TIME_FMT
ws_set["A14"] = "時間間隔 (分鐘)"
ws_set["B14"] = INTERVAL
START_REF = f"{S_SET}!$B$12"
END_REF   = f"{S_SET}!$B$13"

# --- 人手設定 (即時生效) ---
section_title(ws_set, "A16", "③ 人手設定 (即時生效)")
ws_set["A17"] = "預設每時段最低人手"
ws_set["B17"] = DEFAULT_MIN_STAFF
DEFMIN_REF = f"{S_SET}!$B$17"

section_title(ws_set, "A19", "④ 特別時段人手規則 (午市 / 晚市 / 週末等)")
ws_set["A20"] = "適用對象"; ws_set["B20"] = "由"; ws_set["C20"] = "至"; ws_set["D20"] = "最低人手"
for c in "ABCD":
    ws_set[f"{c}20"].font = Font(bold=True)
RULE_ROW0 = 21
N_RULES = 6
# 預設範例規則：午市 2 人、晚市 2 人、週末全日 2 人
preset_rules = [
    ("全部", time(12, 0), time(14, 0), 2),
    ("全部", time(18, 0), time(21, 0), 2),
    ("週末", minute_to_time(OPEN_MIN), minute_to_time(CLOSE_MIN), 2),
]
for i in range(N_RULES):
    r = RULE_ROW0 + i
    if i < len(preset_rules):
        ap, t1, t2, mn = preset_rules[i]
        ws_set.cell(row=r, column=1, value=ap)
        c1 = ws_set.cell(row=r, column=2, value=t1); c1.number_format = TIME_FMT
        c2 = ws_set.cell(row=r, column=3, value=t2); c2.number_format = TIME_FMT
        ws_set.cell(row=r, column=4, value=mn)
    else:
        ws_set.cell(row=r, column=2).number_format = TIME_FMT
        ws_set.cell(row=r, column=3).number_format = TIME_FMT
    for col in range(1, 5):
        ws_set.cell(row=r, column=col).border = BORDER
RULE_APPLY = [f"{S_SET}!$A${RULE_ROW0 + i}" for i in range(N_RULES)]
RULE_FROM  = [f"{S_SET}!$B${RULE_ROW0 + i}" for i in range(N_RULES)]
RULE_TO    = [f"{S_SET}!$C${RULE_ROW0 + i}" for i in range(N_RULES)]
RULE_MIN   = [f"{S_SET}!$D${RULE_ROW0 + i}" for i in range(N_RULES)]

# Settings 的下拉選單 (直接用「頁!範圍」最穩定，Excel/LibreOffice 都支援)
TIME_RANGE = f"{S_LST}!$A$2:$A${1 + len(BOUNDARIES)}"
APPLIES_RANGE = f"{S_LST}!$I$2:$I${1 + len(APPLIES)}"
dv_applies = DataValidation(type="list", formula1=APPLIES_RANGE, allow_blank=True)
ws_set.add_data_validation(dv_applies)
dv_applies.add(f"A{RULE_ROW0}:A{RULE_ROW0 + N_RULES - 1}")
dv_int = DataValidation(type="list", formula1='"15,30"', allow_blank=False)
ws_set.add_data_validation(dv_int)
dv_int.add("B14")
dv_time_set = DataValidation(type="list", formula1=TIME_RANGE, allow_blank=True)
ws_set.add_data_validation(dv_time_set)
dv_time_set.add("B12"); dv_time_set.add("B13")
dv_time_rules = DataValidation(type="list", formula1=TIME_RANGE, allow_blank=True)
ws_set.add_data_validation(dv_time_rules)
dv_time_rules.add(f"B{RULE_ROW0}:C{RULE_ROW0 + N_RULES - 1}")

for col, w in {"A": 22, "B": 14, "C": 14, "D": 12, "E": 12}.items():
    ws_set.column_dimensions[col].width = w


# ---------------------------------------------------------------------------
# 3c. 員工更表輸入 頁
# ---------------------------------------------------------------------------
ws_in["A1"] = "員工更表輸入 — 只需在這裡輸入每天的上班/下班/飯鐘時間"
ws_in["A1"].font = Font(bold=True, size=14, color="FFFFFF")
ws_in["A1"].fill = fill(C_TITLE)
ws_in.merge_cells("A1:H1")
ws_in["A2"] = "提示：時間請用下拉選單選擇；放假的日子留空即可。飯鐘可留空。"
ws_in["A2"].font = Font(italic=True, color="808080")
ws_in.merge_cells("A2:H2")

IN_HDR = 4
headers = ["員工", "星期", "上班", "下班", "飯鐘開始", "飯鐘結束", "每日時數", "檢查 / 錯誤提示"]
for j, h in enumerate(headers):
    c = ws_in.cell(row=IN_HDR, column=1 + j, value=h)
    c.font = hdr_font(); c.fill = fill(C_HDR); c.alignment = CENTER; c.border = BORDER

IN_ROW0 = IN_HDR + 1                       # 第一筆資料列
IN_LAST = IN_ROW0 + len(EMPLOYEES) * len(DAYS) - 1
IN_A = f"{S_IN}!$A${IN_ROW0}:$A${IN_LAST}"
IN_B = f"{S_IN}!$B${IN_ROW0}:$B${IN_LAST}"
IN_C = f"{S_IN}!$C${IN_ROW0}:$C${IN_LAST}"   # 上班
IN_D = f"{S_IN}!$D${IN_ROW0}:$D${IN_LAST}"   # 下班
IN_E = f"{S_IN}!$E${IN_ROW0}:$E${IN_LAST}"   # 飯鐘開始
IN_F = f"{S_IN}!$F${IN_ROW0}:$F${IN_LAST}"   # 飯鐘結束
IN_G = f"{S_IN}!$G${IN_ROW0}:$G${IN_LAST}"   # 每日時數

# 預設示範資料 (讓你打開就看到顏色與運作；可自行修改)
demo = {
    "菁":      {d: (time(9, 45),  time(18, 45), time(13, 0), time(13, 45)) for d in DAYS[:6]},
    "Kerry":   {d: (time(13, 15), time(22, 15), time(17, 30), time(18, 15)) for d in DAYS[:6]},
    "Ice":     {**{d: (time(17, 0), time(22, 15), None, None) for d in DAYS[2:5]},
                **{d: (time(9, 45), time(18, 0), time(13, 0), time(13, 45)) for d in DAYS[5:]}},
    "Brielle": {"星期一": (time(16, 0), time(22, 15), None, None),
                "星期二": (time(16, 0), time(22, 15), None, None),
                "星期日": (time(9, 45), time(22, 15), time(14, 0), time(15, 0))},
}

row = IN_ROW0
for k, emp in enumerate(EMPLOYEES):
    for d in DAYS:
        # 員工欄用公式參照 Settings 名稱 -> 改名會自動同步
        ws_in.cell(row=row, column=1, value=f"={EMP_NAME_REF[k]}")
        ws_in.cell(row=row, column=2, value=d)
        vals = demo.get(emp, {}).get(d, (None, None, None, None))
        for off, v in enumerate(vals):
            cc = ws_in.cell(row=row, column=3 + off, value=v)
            cc.number_format = TIME_FMT
        # 每日時數 = (下班 - 上班 - 飯鐘) * 24，缺上/下班則空白
        cs, ce, bs, be = (f"$C${row}", f"$D${row}", f"$E${row}", f"$F${row}")
        ws_in.cell(row=row, column=7,
                   value=(f'=IF(OR({cs}="",{ce}=""),"",'
                          f'({ce}-{cs}-IF(OR({bs}="",{be}=""),0,{be}-{bs}))*24)'))
        ws_in.cell(row=row, column=7).number_format = HOUR_FMT
        # 檢查欄：逐項驗證並回傳中文錯誤訊息
        ws_in.cell(row=row, column=8, value=(
            f'=IF(AND({cs}<>"",{ce}<>"",{ce}<={cs}),"下班需晚於上班",'
            f'IF(AND({bs}<>"",{be}<>"",{be}<={bs}),"飯鐘結束需晚於開始",'
            f'IF(AND({bs}<>"",{be}<>"",OR({bs}<{cs},{be}>{ce})),"飯鐘超出更時",'
            f'IF(AND({cs}<>"",OR({cs}<{START_REF},{ce}>{END_REF})),"超出營業時間",""))))'))
        for col in range(1, 9):
            ws_in.cell(row=row, column=col).border = BORDER
            ws_in.cell(row=row, column=col).alignment = CENTER
        row += 1

# 時間下拉選單 (上班/下班/飯鐘)
dv_time_in = DataValidation(type="list", formula1=TIME_RANGE, allow_blank=True)
ws_in.add_data_validation(dv_time_in)
dv_time_in.add(f"C{IN_ROW0}:F{IN_LAST}")

# 錯誤提示：檢查欄非空 -> 紅底
ws_in.conditional_formatting.add(
    f"H{IN_ROW0}:H{IN_LAST}",
    FormulaRule(formula=[f'LEN(H{IN_ROW0})>0'], fill=fill(C_ERR)))

for col, w in {"A": 10, "B": 9, "C": 11, "D": 11, "E": 11, "F": 11, "G": 11, "H": 26}.items():
    ws_in.column_dimensions[col].width = w
ws_in.freeze_panes = "A5"


# ---------------------------------------------------------------------------
# 3d. 主排更表 頁
# ---------------------------------------------------------------------------
# 版面 (rows)：
#   覆蓋人數區     : 表頭 4, 資料 5..(4+N)
#   當值名單區     : 表頭 NAMES_HDR, 資料 ...
#   每位員工的彩色更表 : 一個接一個往下排
# 隱藏的「所需人手」格 : 放在右邊 Z 欄起 (與覆蓋區同列，供條件式格式比較)

DAY_COLS = list(range(2, 2 + len(DAYS)))           # B..H
DAY_COL_LETTERS = [get_column_letter(c) for c in DAY_COLS]
REQ_COL0 = 26                                       # Z 欄開始放「所需人手」(隱藏)
REQ_OFFSET = REQ_COL0 - DAY_COLS[0]                 # 覆蓋欄 -> 所需欄 的固定位移

ws_sch["A1"] = "主排更表 (自動產生 — 請在「員工更表輸入」修改班次)"
ws_sch["A1"].font = Font(bold=True, size=14, color="FFFFFF")
ws_sch["A1"].fill = fill(C_TITLE)
ws_sch.merge_cells("A1:H1")
ws_sch["A2"] = ("顏色：紅=無人覆蓋  橙=人手不足  淺綠=正常  灰=飯鐘。 "
                "每格數字 = 當值人數。週末表頭為不同底色。")
ws_sch["A2"].font = Font(italic=True, color="808080")
ws_sch.merge_cells("A2:H2")


def day_header_row(ws, hdr_row, label_a):
    """畫一列『時段 + 星期一..星期日』表頭，週末用不同底色。"""
    a = ws.cell(row=hdr_row, column=1, value=label_a)
    a.font = hdr_font(); a.fill = fill(C_HDR); a.alignment = CENTER; a.border = BORDER
    for j, d in enumerate(DAYS):
        c = ws.cell(row=hdr_row, column=DAY_COLS[j], value=d)
        c.font = hdr_font(); c.alignment = CENTER; c.border = BORDER
        c.fill = fill(C_HDR_WKND if d in WEEKEND else C_HDR)


def write_time_labels(ws, data_row0):
    """在 A 欄寫時段標籤。"""
    for i, lab in enumerate(SLOT_LABELS):
        c = ws.cell(row=data_row0 + i, column=1, value=lab)
        c.font = Font(bold=True, size=9); c.alignment = CENTER; c.border = BORDER
        c.fill = fill("F2F2F2")


# 先決定每位員工彩色更表的位置 (要先知道，因為覆蓋/名單區會參照它們)
COV_HDR = 4
COV_ROW0 = COV_HDR + 1                              # 5
NAMES_HDR = COV_ROW0 + N_SLOTS + 2                  # 覆蓋區之後空兩列
NAMES_ROW0 = NAMES_HDR + 1
EMP_BLOCK_GAP = N_SLOTS + 3
EMP_HDR = [NAMES_ROW0 + N_SLOTS + 2 + k * EMP_BLOCK_GAP for k in range(len(EMPLOYEES))]
EMP_ROW0 = [h + 1 for h in EMP_HDR]


def emp_cell(k, i, col):
    """員工 k、時段 i、星期欄 col 的彩色更表格仔位址 (絕對列、相對欄方便公式)。"""
    return f"{get_column_letter(col)}{EMP_ROW0[k] + i}"


# ---- (A) 每位員工的彩色更表：Work / Break / 空白 ----
for k, emp in enumerate(EMPLOYEES):
    hdr = EMP_HDR[k]
    # 區段標題 (員工名稱，跟著 Settings 改)
    tcell = ws_sch.cell(row=hdr - 1, column=1, value=f"=\"員工更表：\"&{EMP_NAME_REF[k]}")
    tcell.font = Font(bold=True, size=12, color=C_TITLE); tcell.fill = fill(EMP_COLORS[k])
    ws_sch.merge_cells(start_row=hdr - 1, start_column=1, end_row=hdr - 1, end_column=8)

    day_header_row(ws_sch, hdr, "時段＼員工")
    write_time_labels(ws_sch, EMP_ROW0[k])
    for i in range(N_SLOTS):
        slot_ref = f"{S_LST}!$C${2 + i}"
        for j, col in enumerate(DAY_COLS):
            day_hdr_cell = f"{DAY_COL_LETTERS[j]}${hdr}"   # 該欄星期 (相對欄、絕對列)
            # 取該員工該天的上班/下班/飯鐘 (SUMIFS：時間是數值，唯一一筆相加=該值)
            st = f'SUMIFS({IN_C},{IN_A},{EMP_NAME_REF[k]},{IN_B},{day_hdr_cell})'
            en = f'SUMIFS({IN_D},{IN_A},{EMP_NAME_REF[k]},{IN_B},{day_hdr_cell})'
            bs = f'SUMIFS({IN_E},{IN_A},{EMP_NAME_REF[k]},{IN_B},{day_hdr_cell})'
            be = f'SUMIFS({IN_F},{IN_A},{EMP_NAME_REF[k]},{IN_B},{day_hdr_cell})'
            formula = (
                f'=IF(OR({en}<=0,{slot_ref}<{st},{slot_ref}>={en}),"",'
                f'IF(AND({be}>0,{slot_ref}>={bs},{slot_ref}<{be}),"Break","Work"))')
            c = ws_sch.cell(row=EMP_ROW0[k] + i, column=col, value=formula)
            c.alignment = CENTER; c.border = BORDER; c.font = Font(size=9)
    # 條件式格式：Work=員工色、Break=灰
    rng = f"{DAY_COL_LETTERS[0]}{EMP_ROW0[k]}:{DAY_COL_LETTERS[-1]}{EMP_ROW0[k] + N_SLOTS - 1}"
    ws_sch.conditional_formatting.add(
        rng, CellIsRule(operator="equal", formula=['"Work"'], fill=fill(EMP_COLORS[k])))
    ws_sch.conditional_formatting.add(
        rng, CellIsRule(operator="equal", formula=['"Break"'], fill=fill(C_BREAK)))


# ---- (B) 覆蓋人數區 (最上方) ----
sec = ws_sch.cell(row=3, column=1, value="① 人手覆蓋 (每格＝當值人數)")
sec.font = Font(bold=True, size=12, color=C_TITLE); sec.fill = fill(C_SECTION)
ws_sch.merge_cells("A3:H3")
day_header_row(ws_sch, COV_HDR, "時段")
write_time_labels(ws_sch, COV_ROW0)
for i in range(N_SLOTS):
    for j, col in enumerate(DAY_COLS):
        # 當值人數 = 四位員工該格 ="Work" 的數目
        terms = "+".join([f'IF({emp_cell(k, i, col)}="Work",1,0)' for k in range(len(EMPLOYEES))])
        c = ws_sch.cell(row=COV_ROW0 + i, column=col, value=f"={terms}")
        c.alignment = CENTER; c.border = BORDER; c.font = Font(bold=True)
        # 所需人手 (隱藏，放右邊 Z..)
        req_col = col + REQ_OFFSET
        slot_ref = f"{S_LST}!$C${2 + i}"
        day_hdr_cell = f"{DAY_COL_LETTERS[j]}${COV_HDR}"
        is_wknd = f'OR({day_hdr_cell}="星期六",{day_hdr_cell}="星期日")'
        rule_terms = []
        for rr in range(N_RULES):
            match = (f'OR({RULE_APPLY[rr]}="全部",'
                     f'AND({RULE_APPLY[rr]}="平日",NOT({is_wknd})),'
                     f'AND({RULE_APPLY[rr]}="週末",{is_wknd}),'
                     f'{RULE_APPLY[rr]}={day_hdr_cell})')
            rule_terms.append(
                f'IF(AND({match},{slot_ref}>={RULE_FROM[rr]},{slot_ref}<{RULE_TO[rr]}),{RULE_MIN[rr]},0)')
        req_formula = f"=MAX({DEFMIN_REF}," + ",".join(rule_terms) + ")"
        ws_sch.cell(row=COV_ROW0 + i, column=req_col, value=req_formula)

# 覆蓋區條件式格式 (顏色)：紅=0、橙=不足、綠=足夠
cov_rng = f"{DAY_COL_LETTERS[0]}{COV_ROW0}:{DAY_COL_LETTERS[-1]}{COV_ROW0 + N_SLOTS - 1}"
tl = f"{DAY_COL_LETTERS[0]}{COV_ROW0}"                       # 左上格，相對參照基準
req_tl = f"{get_column_letter(DAY_COLS[0] + REQ_OFFSET)}{COV_ROW0}"
ws_sch.conditional_formatting.add(
    cov_rng, FormulaRule(formula=[f"{tl}=0"], fill=fill(C_NOCOVER), stopIfTrue=True))
ws_sch.conditional_formatting.add(
    cov_rng, FormulaRule(formula=[f"AND({tl}>0,{tl}<{req_tl})"], fill=fill(C_UNDER), stopIfTrue=True))
ws_sch.conditional_formatting.add(
    cov_rng, FormulaRule(formula=[f"{tl}>={req_tl}"], fill=fill(C_OK)))

# 隱藏所需人手欄
for c in range(REQ_COL0, REQ_COL0 + len(DAYS)):
    ws_sch.column_dimensions[get_column_letter(c)].hidden = True


# ---- (C) 當值名單區 ----
sec2 = ws_sch.cell(row=NAMES_HDR - 1, column=1, value="② 當值名單 (每格＝該時段在班員工)")
sec2.font = Font(bold=True, size=12, color=C_TITLE); sec2.fill = fill(C_SECTION)
ws_sch.merge_cells(start_row=NAMES_HDR - 1, start_column=1, end_row=NAMES_HDR - 1, end_column=8)
day_header_row(ws_sch, NAMES_HDR, "時段")
write_time_labels(ws_sch, NAMES_ROW0)
for i in range(N_SLOTS):
    for j, col in enumerate(DAY_COLS):
        parts = [f'IF({emp_cell(k, i, col)}="Work",{EMP_NAME_REF[k]},"")'
                 for k in range(len(EMPLOYEES))]
        c = ws_sch.cell(row=NAMES_ROW0 + i, column=col,
                        value=f'=TEXTJOIN(", ",TRUE,{",".join(parts)})')
        c.alignment = CENTER; c.border = BORDER; c.font = Font(size=9)

ws_sch.column_dimensions["A"].width = 15
for cl in DAY_COL_LETTERS:
    ws_sch.column_dimensions[cl].width = 12
ws_sch.freeze_panes = "B5"


# ---------------------------------------------------------------------------
# 3e. Summary 頁 (Dashboard)
# ---------------------------------------------------------------------------
ws_sum["A1"] = "Summary 總覽 Dashboard"
ws_sum["A1"].font = Font(bold=True, size=14, color="FFFFFF")
ws_sum["A1"].fill = fill(C_TITLE)
ws_sum.merge_cells("A1:I1")

# (1) 員工每日 / 每週時數
ws_sum["A3"] = "① 員工工時 (每日 / 每週)"
ws_sum["A3"].font = Font(bold=True, size=12, color=C_TITLE); ws_sum["A3"].fill = fill(C_SECTION)
ws_sum.merge_cells("A3:I3")
hdr_row = 4
ws_sum.cell(row=hdr_row, column=1, value="員工").font = hdr_font()
ws_sum.cell(row=hdr_row, column=1).fill = fill(C_HDR)
for j, d in enumerate(DAYS):
    c = ws_sum.cell(row=hdr_row, column=2 + j, value=d)
    c.font = hdr_font(); c.fill = fill(C_HDR_WKND if d in WEEKEND else C_HDR); c.alignment = CENTER
tot_col = 2 + len(DAYS)
ws_sum.cell(row=hdr_row, column=tot_col, value="每週總計").font = hdr_font()
ws_sum.cell(row=hdr_row, column=tot_col).fill = fill(C_HDR)

emp_row0 = hdr_row + 1
for k, emp in enumerate(EMPLOYEES):
    r = emp_row0 + k
    ws_sum.cell(row=r, column=1, value=f"={EMP_NAME_REF[k]}").font = Font(bold=True)
    for j, d in enumerate(DAYS):
        c = ws_sum.cell(row=r, column=2 + j,
                        value=f'=SUMIFS({IN_G},{IN_A},{EMP_NAME_REF[k]},{IN_B},"{d}")')
        c.number_format = HOUR_FMT; c.alignment = CENTER; c.border = BORDER
    first = get_column_letter(2); last = get_column_letter(1 + len(DAYS))
    ws_sum.cell(row=r, column=tot_col, value=f"=SUM({first}{r}:{last}{r})")
    ws_sum.cell(row=r, column=tot_col).number_format = HOUR_FMT
    ws_sum.cell(row=r, column=tot_col).font = Font(bold=True)
    ws_sum.cell(row=r, column=1).border = BORDER
    ws_sum.cell(row=r, column=tot_col).border = BORDER

emp_last = emp_row0 + len(EMPLOYEES) - 1
tot_letter = get_column_letter(tot_col)
week_rng = f"{tot_letter}{emp_row0}:{tot_letter}{emp_last}"
name_rng = f"A{emp_row0}:A{emp_last}"

# 工時最多 / 最少
ws_sum.cell(row=emp_last + 2, column=1, value="工時最多").font = Font(bold=True)
ws_sum.cell(row=emp_last + 2, column=2,
            value=f"=INDEX({name_rng},MATCH(MAX({week_rng}),{week_rng},0))")
ws_sum.cell(row=emp_last + 2, column=3, value=f"=MAX({week_rng})").number_format = HOUR_FMT
ws_sum.cell(row=emp_last + 3, column=1, value="工時最少").font = Font(bold=True)
ws_sum.cell(row=emp_last + 3, column=2,
            value=f"=INDEX({name_rng},MATCH(MIN({week_rng}),{week_rng},0))")
ws_sum.cell(row=emp_last + 3, column=3, value=f"=MIN({week_rng})").number_format = HOUR_FMT

# (2) 每日人手覆蓋概況
cov_sec = emp_last + 5
ws_sum.cell(row=cov_sec, column=1, value="② 每日人手覆蓋概況").font = Font(bold=True, size=12, color=C_TITLE)
ws_sum.cell(row=cov_sec, column=1).fill = fill(C_SECTION)
ws_sum.merge_cells(start_row=cov_sec, start_column=1, end_row=cov_sec, end_column=9)
chdr = cov_sec + 1
ws_sum.cell(row=chdr, column=1, value="指標").font = hdr_font()
ws_sum.cell(row=chdr, column=1).fill = fill(C_HDR)
for j, d in enumerate(DAYS):
    c = ws_sum.cell(row=chdr, column=2 + j, value=d)
    c.font = hdr_font(); c.fill = fill(C_HDR_WKND if d in WEEKEND else C_HDR); c.alignment = CENTER

# 主排更表覆蓋區 / 所需人手區 的各「天」欄範圍
def sch_cov_col(j):
    L = DAY_COL_LETTERS[j]
    return f"{S_SCH}!${L}${COV_ROW0}:${L}${COV_ROW0 + N_SLOTS - 1}"
def sch_req_col(j):
    L = get_column_letter(DAY_COLS[j] + REQ_OFFSET)
    return f"{S_SCH}!${L}${COV_ROW0}:${L}${COV_ROW0 + N_SLOTS - 1}"

metrics = [
    ("每日總工時", lambda j, d: f'=SUMIFS({IN_G},{IN_B},"{d}")', HOUR_FMT),
    ("無人覆蓋時段數", lambda j, d: f'=COUNTIF({sch_cov_col(j)},0)', "0"),
    ("人手不足時段數", lambda j, d: f'=SUMPRODUCT(({sch_cov_col(j)}>0)*({sch_cov_col(j)}<{sch_req_col(j)}))', "0"),
]
for mi, (label, ffn, nf) in enumerate(metrics):
    r = chdr + 1 + mi
    ws_sum.cell(row=r, column=1, value=label).font = Font(bold=True)
    ws_sum.cell(row=r, column=1).border = BORDER
    for j, d in enumerate(DAYS):
        c = ws_sum.cell(row=r, column=2 + j, value=ffn(j, d))
        c.number_format = nf; c.alignment = CENTER; c.border = BORDER

# (3) 哪些時段無人覆蓋 / 人手不足 (逐日列出)
lst_sec = chdr + 1 + len(metrics) + 2
ws_sum.cell(row=lst_sec, column=1, value="③ 問題時段清單").font = Font(bold=True, size=12, color=C_TITLE)
ws_sum.cell(row=lst_sec, column=1).fill = fill(C_SECTION)
ws_sum.merge_cells(start_row=lst_sec, start_column=1, end_row=lst_sec, end_column=9)
lhdr = lst_sec + 1
for col, t in [(1, "星期"), (2, "無人覆蓋時段"), (5, "人手不足時段")]:
    c = ws_sum.cell(row=lhdr, column=col, value=t)
    c.font = hdr_font(); c.fill = fill(C_HDR)
ws_sum.merge_cells(start_row=lhdr, start_column=2, end_row=lhdr, end_column=4)
ws_sum.merge_cells(start_row=lhdr, start_column=5, end_row=lhdr, end_column=7)

label_rng = f"{S_LST}!$E$2:$E${1 + N_SLOTS}"
for j, d in enumerate(DAYS):
    r = lhdr + 1 + j
    ws_sum.cell(row=r, column=1, value=d).font = Font(bold=True)
    cov = sch_cov_col(j); req = sch_req_col(j)
    f_nocover = f'=TEXTJOIN(", ",TRUE,IF({cov}=0,{label_rng},""))'
    f_under   = f'=TEXTJOIN(", ",TRUE,IF(({cov}>0)*({cov}<{req}),{label_rng},""))'
    cell_no = ws_sum.cell(row=r, column=2)
    cell_un = ws_sum.cell(row=r, column=5)
    if HAVE_ARRAY:
        cell_no.value = ArrayFormula(cell_no.coordinate, f_nocover)
        cell_un.value = ArrayFormula(cell_un.coordinate, f_under)
    else:
        cell_no.value = f_nocover
        cell_un.value = f_under
    ws_sum.merge_cells(start_row=r, start_column=2, end_row=r, end_column=4)
    ws_sum.merge_cells(start_row=r, start_column=5, end_row=r, end_column=7)
    for cc in (cell_no, cell_un):
        cc.alignment = LEFT

# (4) 錯誤總數
err_row = lhdr + 1 + len(DAYS) + 1
ws_sum.cell(row=err_row, column=1, value="排班錯誤總數").font = Font(bold=True)
ws_sum.cell(row=err_row, column=2,
            value=f'=SUMPRODUCT((LEN({S_IN}!$H${IN_ROW0}:$H${IN_LAST})>0)*1)')
ws_sum.conditional_formatting.add(
    f"B{err_row}",
    CellIsRule(operator="greaterThan", formula=["0"], fill=fill(C_ERR)))

ws_sum.column_dimensions["A"].width = 16
for cl in "BCDEFGHI":
    ws_sum.column_dimensions[cl].width = 12


# ---------------------------------------------------------------------------
# 3f. 說明 Instructions 頁
# ---------------------------------------------------------------------------
ws_inst["A1"] = "使用說明 Instructions"
ws_inst["A1"].font = Font(bold=True, size=16, color="FFFFFF")
ws_inst["A1"].fill = fill(C_TITLE)
ws_inst.merge_cells("A1:B1")

lines = [
    ("", ""),
    ("這個檔案是甚麼？", "一個自動化的員工排更表。你只需在『員工更表輸入』填時間，其餘頁面會自動更新。"),
    ("", ""),
    ("① 如何輸入員工更期", ""),
    ("步驟", "到『員工更表輸入』頁，每位員工每天一列。"),
    ("", "用下拉選單選『上班』『下班』時間；有飯鐘就選『飯鐘開始/結束』，沒有就留空。"),
    ("", "放假的日子整列留空即可。『每日時數』與『主排更表』會自動計算。"),
    ("", ""),
    ("② 如何修改員工名單", ""),
    ("步驟", "到『設定 Settings』頁 ①，直接改 A 欄的員工名稱。"),
    ("", "全檔 (輸入頁、主表、Summary) 會自動跟著新名稱更新，即時生效。"),
    ("", ""),
    ("③ 如何改營業時間 / 時間間隔", ""),
    ("步驟", "到『設定 Settings』頁 ②，改開始/結束時間或間隔 (15 或 30 分鐘)。"),
    ("注意", "因為這會改變表格的格線數量，改完後需要重新執行 python3 scripts/build_roster.py 才會生效。"),
    ("", "人手規則 (③④) 及員工名稱則是即時生效，不用重跑。"),
    ("", ""),
    ("④ 如何設定人手要求", ""),
    ("步驟", "『設定 Settings』③ 設預設最低人手；④ 加特別規則 (例：午市 12:00-14:00 需 2 人)。"),
    ("適用對象", "可選『全部 / 平日 / 週末 / 某一天』。多條規則重疊時取最高要求。"),
    ("", ""),
    ("⑤ 如何看錯誤與顏色提示", ""),
    ("輸入頁", "『檢查/錯誤提示』欄會用紅底標示：下班早於上班、飯鐘超時、超出營業時間等。"),
    ("主排更表", "紅=無人覆蓋；橙=人手不足；淺綠=正常；灰=飯鐘。每格數字是當值人數。"),
    ("", ""),
    ("⑥ 如何看每週工時 Summary", ""),
    ("Summary 頁", "① 每位員工每日/每週時數、工時最多/最少；② 每日覆蓋概況；③ 問題時段清單。"),
    ("", ""),
    ("日後可加入的規則", "固定放假日、長短週、兼職每週最低時數、飯鐘規則、分段班次等 (可再請我擴充)。"),
]
r = 2
for a, b in lines:
    ca = ws_inst.cell(row=r, column=1, value=a)
    cb = ws_inst.cell(row=r, column=2, value=b)
    if a and not b:                       # 區段小標題
        ca.font = Font(bold=True, size=12, color=C_TITLE)
        ca.fill = fill(C_SECTION)
        ws_inst.merge_cells(start_row=r, start_column=1, end_row=r, end_column=2)
    else:
        ca.font = Font(bold=True)
        ca.alignment = Alignment(vertical="top")
        cb.alignment = LEFT
    r += 1
ws_inst.column_dimensions["A"].width = 22
ws_inst.column_dimensions["B"].width = 90


# ===========================================================================
# 4. 頁面次序、儲存
# ===========================================================================
wb.move_sheet("說明 Instructions", -wb.index(wb["說明 Instructions"]))  # 放最前
wb.save(OUTPUT)
print(f"已產生：{OUTPUT}")
print(f"時段數：{N_SLOTS} (每格 {INTERVAL} 分鐘，{fmt_label(OPEN_MIN)}~{fmt_label(CLOSE_MIN)})")
