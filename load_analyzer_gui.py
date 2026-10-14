"""CSV 하중 분석과 단면 응력 계산을 위한 Tkinter GUI."""

import csv
import math
import os
import tkinter as tk
from tkinter import filedialog, ttk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure


BG = "#e8edf5"
HEADER = "#1e3a8a"
CARD = "#ffffff"
TEXT = "#111827"
MUTED = "#64748b"
LINE = "#cbd5e1"
BLUE = "#1e3a8a"
RED = "#dc2626"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CSV = os.path.join(BASE_DIR, "load_data.csv")

SECTIONS = {
    "사각형": (("b", "폭 b (mm)"), ("h", "높이 h (mm)")),
    "원형봉": (("d", "지름 d (mm)"),),
    "원형관": (("D", "외경 D (mm)"), ("t", "두께 t (mm)")),
    "사각형관": (("B", "외측 폭 B (mm)"), ("H", "외측 높이 H (mm)"), ("t", "두께 t (mm)")),
    "H형강": (("H", "전체 높이 H (mm)"), ("B", "플랜지 폭 B (mm)"),
              ("tw", "웨브 두께 tw (mm)"), ("tf", "플랜지 두께 tf (mm)")),
}

DEFAULT_DIMENSIONS = {
    "b": "10", "h": "10", "d": "20", "D": "40", "t": "5",
    "B": "40", "H": "60", "tw": "5", "tf": "8",
}


def parse_finite_number(raw):
    """빈칸, 숫자 아님, 무한대/NaN이면 None을 반환한다."""
    text = (raw or "").strip()
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def read_csv_records(path):
    """CSV를 읽어 유효 레코드와 제외 행 정보를 돌려준다.

    반환값은 (records, skipped)이며 records는 시간순 (time_s, force_N)
    튜플 목록, skipped는 (행 번호, 문제 열과 원문 값) 목록이다.
    원본 CSV 파일은 읽기만 한다.
    """
    records = []
    skipped = []
    with open(path, newline="", encoding="utf-8-sig") as csv_file:
        reader = csv.DictReader(csv_file)
        if not reader.fieldnames:
            raise ValueError("CSV 헤더가 없습니다. time_s와 force_N 열이 필요합니다.")
        reader.fieldnames = [name.strip() if name else "" for name in reader.fieldnames]
        missing = [name for name in ("time_s", "force_N") if name not in reader.fieldnames]
        if missing:
            raise ValueError(
                "필수 열이 없습니다: " + ", ".join(missing) + " (필요한 열: time_s, force_N)"
            )

        for row_number, row in enumerate(reader, start=2):
            raw_time = row.get("time_s", "") or ""
            raw_force = row.get("force_N", "") or ""
            time_s = parse_finite_number(raw_time)
            force_n = parse_finite_number(raw_force)
            problems = []
            if time_s is None:
                problems.append(("time_s", raw_time))
            if force_n is None:
                problems.append(("force_N", raw_force))
            if problems:
                skipped.append((row_number, problems))
            else:
                records.append((time_s, force_n))

    records.sort(key=lambda record: record[0])
    return records, skipped


def calculate_area(section, dimensions):
    """단면 형상과 치수 문자열을 검증하고 면적(mm²)을 계산한다."""
    values = {}
    for key, _label in SECTIONS[section]:
        raw = dimensions[key].strip()
        value = parse_finite_number(raw)
        if value is None:
            raise ValueError(f"{key} 치수는 비어 있거나 숫자가 아닙니다.")
        if value <= 0:
            raise ValueError(f"{key} 치수는 0보다 커야 합니다.")
        values[key] = value

    if section == "사각형":
        return values["b"] * values["h"]
    if section == "원형봉":
        return math.pi * values["d"] ** 2 / 4
    if section == "원형관":
        diameter, thickness = values["D"], values["t"]
        if 2 * thickness >= diameter:
            raise ValueError("원형관은 2t < D여야 내부 공간이 있습니다.")
        inner_diameter = diameter - 2 * thickness
        return math.pi * (diameter ** 2 - inner_diameter ** 2) / 4
    if section == "사각형관":
        width, height, thickness = values["B"], values["H"], values["t"]
        if 2 * thickness >= width or 2 * thickness >= height:
            raise ValueError("사각형관은 2t < B, 2t < H여야 내부 공간이 있습니다.")
        return width * height - (width - 2 * thickness) * (height - 2 * thickness)
    if section == "H형강":
        height, width = values["H"], values["B"]
        web, flange = values["tw"], values["tf"]
        if 2 * flange >= height:
            raise ValueError("H형강은 2tf < H여야 합니다.")
        if web >= width:
            raise ValueError("H형강은 tw < B여야 합니다.")
        return 2 * width * flange + (height - 2 * flange) * web
    raise ValueError("지원하지 않는 단면 형상입니다.")


def format_number(value, decimals=4):
    """숫자를 천 단위 구분과 불필요한 소수점 없이 표시한다."""
    if value != 0 and abs(value) < 10 ** (-decimals):
        return f"{value:.{decimals}e}"
    return f"{value:,.{decimals}f}".rstrip("0").rstrip(".")


class LoadAnalyzerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("CSV 하중 · 단면 응력 분석기")
        self.root.geometry("1050x760")
        self.root.minsize(860, 650)
        self.root.configure(bg=BG)

        self.csv_path = ""
        self.records = []
        self.skipped = []
        self.analysis_valid = False
        self.dimension_vars = {
            key: tk.StringVar(value=value) for key, value in DEFAULT_DIMENSIONS.items()
        }
        self.section_var = tk.StringVar(value="사각형")
        self.csv_path_var = tk.StringVar()
        self.count_var = tk.StringVar(value="CSV를 선택하세요.")
        self.detail_var = tk.StringVar(value="")
        self.area_var = tk.StringVar(value="—")
        self.max_force_var = tk.StringVar(value="—")
        self.stress_var = tk.StringVar(value="—")
        self.stress_time_var = tk.StringVar(value="—")
        self.status_var = tk.StringVar(value="CSV를 선택하고 단면 치수를 확인하세요.")

        self._build_ui()
        for variable in self.dimension_vars.values():
            variable.trace_add("write", self._condition_changed)
        self.section_var.trace_add("write", self._section_changed)
        if os.path.isfile(DEFAULT_CSV):
            self._load_csv(DEFAULT_CSV)

    def _build_ui(self):
        self.root.bind("<Return>", lambda _event: self._analyze())
        self.root.bind("<F5>", lambda _event: self._analyze())
        header = tk.Frame(self.root, bg=HEADER, height=66)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text="CSV 하중 · 단면 응력 분석기", bg=HEADER, fg="white",
                 font=("Arial", 20, "bold")).pack(side="left", padx=24)
        tk.Label(header, text="Force → Stress", bg=HEADER, fg="#bfdbfe",
                 font=("Arial", 12, "bold")).pack(side="right", padx=24)

        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=18, pady=14)

        file_card = self._card(body)
        file_card.pack(fill="x")
        tk.Label(file_card, text="CSV 데이터", bg=CARD, fg=MUTED,
                 font=("Arial", 10, "bold")).pack(anchor="w")
        path_row = tk.Frame(file_card, bg=CARD)
        path_row.pack(fill="x", pady=(7, 4))
        self.path_entry = ttk.Entry(path_row, textvariable=self.csv_path_var, state="readonly")
        self.path_entry.pack(side="left", fill="x", expand=True, ipady=5)
        ttk.Button(path_row, text="찾아보기…", command=self._browse).pack(side="left", padx=(8, 0))
        tk.Label(file_card, textvariable=self.count_var, bg=CARD, fg=TEXT,
                 font=("Arial", 11, "bold")).pack(anchor="w", pady=(3, 0))
        tk.Label(file_card, textvariable=self.detail_var, bg=CARD, fg=RED,
                 font=("Arial", 9), justify="left", anchor="w", wraplength=960).pack(
                     fill="x", anchor="w", pady=(3, 0))

        controls = tk.Frame(body, bg=BG)
        controls.pack(fill="x", pady=(12, 0))
        section_card = self._card(controls)
        section_card.pack(side="left", fill="both", expand=True)
        tk.Label(section_card, text="단면 형상과 치수 (mm)", bg=CARD, fg=MUTED,
                 font=("Arial", 10, "bold")).pack(anchor="w")
        self.section_combo = ttk.Combobox(
            section_card, textvariable=self.section_var, values=list(SECTIONS),
            state="readonly", width=16
        )
        self.section_combo.pack(anchor="w", pady=(7, 8))
        self.dimension_frame = tk.Frame(section_card, bg=CARD)
        self.dimension_frame.pack(fill="x")
        self._refresh_dimension_fields()

        result_card = self._card(controls)
        result_card.pack(side="left", fill="both", expand=True, padx=(12, 0))
        tk.Label(result_card, text="분석 결과", bg=CARD, fg=MUTED,
                 font=("Arial", 10, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")
        self._result_row(result_card, 1, "단면적", self.area_var, "mm²")
        self._result_row(result_card, 2, "최대 하중", self.max_force_var, "N")
        self._result_row(result_card, 3, "최대 응력", self.stress_var, "MPa")
        self._result_row(result_card, 4, "발생 시간", self.stress_time_var, "s")
        ttk.Button(result_card, text="분석", command=self._analyze).grid(
            row=5, column=0, columnspan=2, sticky="ew", pady=(10, 0), ipady=4
        )
        result_card.columnconfigure(1, weight=1)

        graph_card = self._card(body)
        graph_card.pack(fill="both", expand=True, pady=(12, 0))
        tk.Label(graph_card, text="시계열 그래프", bg=CARD, fg=MUTED,
                 font=("Arial", 10, "bold")).pack(anchor="w")
        self.figure = Figure(figsize=(7, 3.6), dpi=100, facecolor=CARD)
        self.axes = self.figure.add_subplot(111)
        self.chart = FigureCanvasTkAgg(self.figure, master=graph_card)
        self.chart.get_tk_widget().pack(fill="both", expand=True, pady=(4, 0))
        self._draw_chart()

        footer = tk.Label(body, textvariable=self.status_var, bg=BG, fg=MUTED,
                          font=("Arial", 10), anchor="w")
        footer.pack(fill="x", pady=(8, 0))

    @staticmethod
    def _card(parent):
        return tk.Frame(parent, bg=CARD, padx=14, pady=11,
                        highlightbackground=LINE, highlightthickness=1)

    @staticmethod
    def _result_row(parent, row, label, variable, unit):
        tk.Label(parent, text=label, bg=CARD, fg=MUTED,
                 font=("Arial", 10)).grid(row=row, column=0, sticky="w", pady=3, padx=(0, 10))
        tk.Label(parent, textvariable=variable, bg=CARD, fg=TEXT,
                 font=("Arial", 12, "bold")).grid(row=row, column=1, sticky="w", pady=3)
        tk.Label(parent, text=unit, bg=CARD, fg=MUTED,
                 font=("Arial", 9)).grid(row=row, column=2, sticky="w", padx=(5, 0))

    def _refresh_dimension_fields(self):
        for child in self.dimension_frame.winfo_children():
            child.destroy()
        for index, (key, label) in enumerate(SECTIONS[self.section_var.get()]):
            row, column = divmod(index, 2)
            cell = tk.Frame(self.dimension_frame, bg=CARD)
            cell.grid(row=row, column=column, sticky="ew", padx=(0, 12), pady=3)
            tk.Label(cell, text=label, bg=CARD, fg=TEXT,
                     font=("Arial", 9)).pack(anchor="w")
            ttk.Entry(cell, textvariable=self.dimension_vars[key], width=17).pack(
                anchor="w", fill="x", pady=(2, 0)
            )
        for column in range(2):
            self.dimension_frame.columnconfigure(column, weight=1)

    def _browse(self):
        path = filedialog.askopenfilename(
            title="하중 데이터 CSV 선택",
            initialdir=os.path.dirname(self.csv_path) if self.csv_path else BASE_DIR,
            filetypes=(("CSV 파일", "*.csv"), ("모든 파일", "*.*")),
        )
        if path:
            self._load_csv(path)

    def _clear_analysis(self):
        self.analysis_valid = False
        self.area_var.set("—")
        self.stress_var.set("—")
        self.stress_time_var.set("—")

    def _load_csv(self, path):
        self.csv_path = path
        self.csv_path_var.set(path)
        self._clear_analysis()
        self.detail_var.set("")
        try:
            records, skipped = read_csv_records(path)
        except (OSError, UnicodeError, csv.Error, ValueError) as error:
            self.records, self.skipped = [], []
            self.max_force_var.set("—")
            self.count_var.set("CSV를 읽지 못했습니다.")
            self.detail_var.set(str(error))
            self.status_var.set("파일 경로와 CSV 열 이름(time_s, force_N)을 확인하세요.")
            self._draw_chart()
            return

        self.records, self.skipped = records, skipped
        self.count_var.set(f"유효 데이터 {len(records)}개 · 제외 데이터 {len(skipped)}개")
        if skipped:
            details = []
            for row_number, problems in skipped:
                values = ", ".join(
                    f"{name}={'(빈칸)' if not value.strip() else repr(value)}"
                    for name, value in problems
                )
                details.append(f"{row_number}행 {values}")
            self.detail_var.set("제외: " + "; ".join(details))

        if records:
            _time, max_force = max(records, key=lambda item: item[1])
            self.max_force_var.set(format_number(max_force))
            self.status_var.set("CSV를 불러왔습니다. 단면 치수를 확인하고 분석을 누르세요.")
        else:
            self.max_force_var.set("—")
            self.status_var.set("유효 데이터가 없어 분석할 수 없습니다.")
        self._draw_chart()

    def _section_changed(self, *_args):
        self._refresh_dimension_fields()
        self._condition_changed()

    def _condition_changed(self, *_args):
        if not self.analysis_valid:
            return
        self._clear_analysis()
        self.status_var.set("조건 변경됨: 다시 분석 필요")
        self._draw_chart()

    def _analyze(self):
        self._clear_analysis()
        if not self.csv_path:
            self.status_var.set("먼저 CSV 파일을 선택하세요.")
            self._draw_chart()
            return
        if not self.records:
            self.status_var.set("유효 데이터가 없어 분석을 진행할 수 없습니다.")
            self._draw_chart()
            return
        try:
            dimensions = {key: variable.get() for key, variable in self.dimension_vars.items()}
            area = calculate_area(self.section_var.get(), dimensions)
        except (KeyError, ValueError) as error:
            self.status_var.set(f"입력 오류: {error}")
            self._draw_chart()
            return

        stresses = [(time_s, force_n / area) for time_s, force_n in self.records]
        max_time, max_stress = max(stresses, key=lambda item: item[1])
        self.area_var.set(format_number(area, 2))
        self.stress_var.set(format_number(max_stress, 4))
        self.stress_time_var.set(format_number(max_time))
        self.analysis_valid = True
        self.status_var.set("분석 완료")
        self._draw_chart(stresses, (max_time, max_stress))

    def _draw_chart(self, stress_records=None, max_point=None):
        self.axes.clear()
        if not self.records:
            self.axes.set_title("Select a CSV file")
            self.axes.set_xlabel("Time (s)")
            self.axes.set_ylabel("Force (N)")
        elif stress_records is not None and self.analysis_valid:
            times = [time_s for time_s, _ in stress_records]
            values = [stress for _, stress in stress_records]
            self.axes.plot(times, values, marker="o", color=BLUE, linewidth=2)
            self.axes.set_title("Time - Stress")
            self.axes.set_xlabel("Time (s)")
            self.axes.set_ylabel("Stress (MPa)")
            if max_point is not None:
                max_time, max_value = max_point
                self.axes.scatter([max_time], [max_value], color=RED, zorder=4)
                self.axes.annotate(f"{format_number(max_value, 4)} MPa",
                                   xy=(max_time, max_value), xytext=(7, 8),
                                   textcoords="offset points", color=RED, fontweight="bold")
        else:
            times = [time_s for time_s, _ in self.records]
            forces = [force_n for _, force_n in self.records]
            self.axes.plot(times, forces, marker="o", color=BLUE, linewidth=2)
            self.axes.set_title("Time - Force")
            self.axes.set_xlabel("Time (s)")
            self.axes.set_ylabel("Force (N)")
        self.axes.grid(True, linestyle="--", alpha=0.35)
        self.figure.tight_layout()
        self.chart.draw_idle()


def main():
    root = tk.Tk()
    LoadAnalyzerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
