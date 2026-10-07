# load_analyzer.py
"""하중(Load) 데이터 분석기

load_data.csv(열: time_s, force_N)를 읽어 힘-시간 그래프와 주요 통계를
tkinter 창에 보여준다. force_converter.py는 그대로 두고, 그 안의 색상
상수와 숫자 서식 함수만 재사용한다.
 - 최대/최소 힘과 그 시각
 - 평균 힘
 - 충격량(힘을 시간에 대해 적분한 값, 사다리꼴 적분)
 - 힘-시간 곡선을 캔버스에 직접 그린 그래프(외부 패키지 없음)
 - 단면적을 이용해 응력(σ=F/A)을 계산하고 시간-응력 그래프를 stress_plot.png로 저장
 - 계산 결과(time_s, force_N, stress_MPa)를 load_result.csv로 저장 (원본 CSV는 수정하지 않음)
 - 기준 응력을 초과한 데이터 개수를 출력
"""

import csv
import os
import sys
import tkinter as tk
from tkinter import ttk

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from force_converter import BG, CARD, HEADER, LINE, TEXT, format_number

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "load_data.csv")
RESULT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "load_result.csv")
STRESS_PLOT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stress_plot.png")

# 시험편 단면적(mm^2). 응력(MPa) = 힘(N) / 단면적(mm^2)
CROSS_SECTION_AREA_MM2 = 100.0

# 기준 응력(MPa). 이 값을 초과하는 데이터 개수를 출력한다.
STRESS_THRESHOLD_MPA = 6.0

CHART_LINE = "#1e3a8a"
CHART_POINT = "#3b82f6"
CHART_GRID = "#e2e8f0"
CHART_AXIS = "#94a3b8"


# ---------------------------------------------------------------- 데이터 로딩
def resolve_path(path):
    """상대 경로면 이 스크립트가 있는 폴더를 기준으로 절대 경로를 만든다."""
    if os.path.isabs(path):
        return path
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), path)


def parse_number(raw_value):
    """문자열을 실수로 바꾼다. 빈칸이거나 숫자가 아니면 None을 돌려준다."""
    text = raw_value.strip() if raw_value is not None else ""
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def load_records(path):
    """CSV 파일을 읽어 (time_s, force_N) 튜플 목록과 제외된 행 목록을 돌려준다.

    time_s 또는 force_N이 비어있거나 숫자로 해석할 수 없는 행은 계산과
    그래프에서 제외하고, (행 번호, [(열 이름, 원본 값), ...])으로
    skipped에 담는다. 원본 CSV 파일은 읽기만 하며 수정하지 않는다.
    """
    records = []
    skipped = []
    with open(path, newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        for row_number, row in enumerate(reader, start=2):  # 2: 헤더 다음 줄부터
            raw_time = row.get("time_s", "")
            raw_force = row.get("force_N", "")
            time_s = parse_number(raw_time)
            force_n = parse_number(raw_force)

            problems = []
            if time_s is None:
                problems.append(("time_s", raw_time))
            if force_n is None:
                problems.append(("force_N", raw_force))

            if problems:
                skipped.append((row_number, problems))
                continue
            records.append((time_s, force_n))
    records.sort(key=lambda record: record[0])
    return records, skipped


def describe_skip(row_number, problems):
    """제외된 행을 '행 번호 - 문제 값' 형태의 안내 문구로 만든다."""
    details = ", ".join(
        f"{column}={value!r}" if value else f"{column}=(빈칸)"
        for column, value in problems
    )
    return f"[제외] {row_number}행: {details} — 숫자가 아니어서 계산에서 제외합니다."


def format_plain_number(value):
    """정수면 소수점 없이, 아니면 그대로 문자열로 바꾼다. (예: 5.0 -> '5')"""
    return str(int(value)) if float(value).is_integer() else str(value)


# ---------------------------------------------------------------- 통계 계산
def analyze(records):
    """힘-시간 데이터에서 주요 통계를 계산한다."""
    if not records:
        raise ValueError("데이터가 없습니다.")

    times = [time_s for time_s, _ in records]
    forces = [force_n for _, force_n in records]

    max_time, max_force = max(records, key=lambda record: record[1])
    min_time, min_force = min(records, key=lambda record: record[1])

    impulse = 0.0
    for (t1, f1), (t2, f2) in zip(records, records[1:]):
        impulse += (f1 + f2) / 2 * (t2 - t1)

    return {
        "count": len(records),
        "duration": times[-1] - times[0],
        "max_force": max_force,
        "max_time": max_time,
        "min_force": min_force,
        "min_time": min_time,
        "avg_force": sum(forces) / len(forces),
        "impulse": impulse,
    }


def compute_stress(records, area_mm2):
    """힘(N) 데이터를 단면적(mm^2)으로 나눠 (time_s, stress_MPa) 목록을 만든다."""
    return [(time_s, force_n / area_mm2) for time_s, force_n in records]


def stress_stats(stress_records):
    """최대 응력과 그 시각을 돌려준다."""
    max_time, max_stress = max(stress_records, key=lambda record: record[1])
    return max_stress, max_time


def count_exceeding(stress_records, threshold):
    """threshold(MPa)를 초과하는 데이터 개수를 센다."""
    return sum(1 for _, stress_mpa in stress_records if stress_mpa > threshold)


def save_result_csv(records, stress_records, output_path):
    """time_s, force_N, stress_MPa 결과를 새 CSV로 저장한다. 원본은 건드리지 않는다."""
    with open(output_path, "w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["time_s", "force_N", "stress_MPa"])
        for (time_s, force_n), (_, stress_mpa) in zip(records, stress_records):
            writer.writerow([format_plain_number(time_s), format_plain_number(force_n), stress_mpa])


def save_stress_plot(stress_records, output_path, max_point=None):
    """시간-응력 그래프를 그려 PNG 파일로 저장한다. max_point가 있으면 최대 응력 점에 값을 표시한다."""
    times = [time_s for time_s, _ in stress_records]
    stresses = [stress_mpa for _, stress_mpa in stress_records]

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(times, stresses, marker="o", linestyle="-", color=CHART_LINE)
    if max_point is not None:
        max_time, max_stress = max_point
        ax.scatter([max_time], [max_stress], color="#dc2626", zorder=5)
        ax.annotate(f"{max_stress} MPa", xy=(max_time, max_stress), xytext=(6, 8),
                    textcoords="offset points", color="#dc2626", fontweight="bold")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Stress (MPa)")
    ax.set_title("Time - Stress")
    ax.grid(True, linestyle="--", alpha=0.4)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------- 화면 구성
def draw_chart(canvas, records):
    canvas.delete("all")
    width = canvas.winfo_width()
    height = canvas.winfo_height()
    if width <= 1 or height <= 1 or not records:
        return

    pad_left, pad_right, pad_top, pad_bottom = 56, 20, 20, 36
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom

    times = [time_s for time_s, _ in records]
    forces = [force_n for _, force_n in records]
    t_min, t_max = min(times), max(times)
    f_min, f_max = min(0.0, min(forces)), max(forces)
    t_span = (t_max - t_min) or 1.0
    f_span = (f_max - f_min) or 1.0

    def to_xy(time_s, force_n):
        x = pad_left + (time_s - t_min) / t_span * plot_w
        y = pad_top + (1 - (force_n - f_min) / f_span) * plot_h
        return x, y

    # 격자 및 축
    for i in range(5):
        y = pad_top + plot_h * i / 4
        value = f_max - f_span * i / 4
        canvas.create_line(pad_left, y, width - pad_right, y, fill=CHART_GRID)
        canvas.create_text(pad_left - 8, y, text=format_number(value), fill=CHART_AXIS,
                            font=("Arial", 9), anchor="e")

    for time_s in times:
        x, _ = to_xy(time_s, f_min)
        canvas.create_text(x, height - pad_bottom + 14, text=format_number(time_s),
                            fill=CHART_AXIS, font=("Arial", 9))

    canvas.create_line(pad_left, pad_top, pad_left, height - pad_bottom, fill=CHART_AXIS)
    canvas.create_line(pad_left, height - pad_bottom, width - pad_right, height - pad_bottom,
                        fill=CHART_AXIS)

    # 힘-시간 곡선
    points = [to_xy(time_s, force_n) for time_s, force_n in records]
    canvas.create_line(*[coord for point in points for coord in point],
                        fill=CHART_LINE, width=2, smooth=False)
    for x, y in points:
        canvas.create_oval(x - 3, y - 3, x + 3, y + 3, fill=CHART_POINT, outline="")


def build_gui(records, stats):
    root = tk.Tk()
    root.title("하중 데이터 분석기")
    root.geometry("860x560")
    root.minsize(700, 480)
    root.configure(bg=BG)

    style = ttk.Style()
    style.theme_use("clam")
    style.configure("CardLabel.TLabel", font=("Arial", 11, "bold"), background=CARD,
                    foreground="#64748b")
    style.configure("Stat.TLabel", font=("Arial", 13, "bold"), background=CARD, foreground=TEXT)

    header = tk.Frame(root, bg=HEADER, height=70)
    header.pack(fill="x")
    header.pack_propagate(False)
    tk.Label(header, text="📈  하중 데이터 분석기", bg=HEADER, fg="white",
             font=("Arial", 20, "bold")).pack(side="left", padx=24)
    tk.Label(header, text=f"{stats['count']}개 샘플  ·  {format_number(stats['duration'])} s",
             bg=HEADER, fg="#a5b4fc", font=("Arial", 12)).pack(side="right", padx=24)

    body = tk.Frame(root, bg=BG)
    body.pack(fill="both", expand=True, padx=18, pady=16)

    chart_card = tk.Frame(body, bg=CARD, padx=12, pady=12,
                          highlightbackground=LINE, highlightthickness=1)
    chart_card.pack(side="left", fill="both", expand=True)
    ttk.Label(chart_card, text="힘 - 시간 그래프 (N vs s)", style="CardLabel.TLabel").pack(anchor="w")

    canvas = tk.Canvas(chart_card, bg="white", highlightthickness=0)
    canvas.pack(fill="both", expand=True, pady=(8, 0))
    canvas.bind("<Configure>", lambda event: draw_chart(canvas, records))

    stats_card = tk.Frame(body, bg=CARD, padx=16, pady=14, width=260,
                          highlightbackground=LINE, highlightthickness=1)
    stats_card.pack(side="right", fill="y", padx=(16, 0))
    stats_card.pack_propagate(False)
    ttk.Label(stats_card, text="요약 통계", style="CardLabel.TLabel").pack(anchor="w", pady=(0, 10))

    rows = [
        ("최대 힘", f"{format_number(stats['max_force'])} N  (t={format_number(stats['max_time'])}s)"),
        ("최소 힘", f"{format_number(stats['min_force'])} N  (t={format_number(stats['min_time'])}s)"),
        ("평균 힘", f"{format_number(stats['avg_force'])} N"),
        ("측정 시간", f"{format_number(stats['duration'])} s"),
        ("충격량", f"{format_number(stats['impulse'])} N·s"),
    ]
    for label, value in rows:
        row = tk.Frame(stats_card, bg=CARD)
        row.pack(fill="x", pady=6)
        tk.Label(row, text=label, bg=CARD, fg="#64748b", font=("Arial", 11)).pack(anchor="w")
        ttk.Label(row, text=value, style="Stat.TLabel").pack(anchor="w")

    root.mainloop()


def main():
    path = resolve_path(sys.argv[1]) if len(sys.argv) > 1 else DATA_FILE
    print(f"입력 파일: {os.path.basename(path)}")

    records, skipped = load_records(path)

    for row_number, problems in skipped:
        print(describe_skip(row_number, problems))
    print(f"제외한 행 수: {len(skipped)}개")
    print(f"유효한 데이터 수: {len(records)}개")

    if not records:
        print("유효한 데이터가 없어 분석을 진행할 수 없습니다. CSV 내용을 확인해주세요.")
        return

    stats = analyze(records)
    print(f"데이터 개수: {stats['count']}개")
    print(f"최대 하중: {format_plain_number(stats['max_force'])} N")
    print(f"최대 하중 시간: {format_plain_number(stats['max_time'])} s")

    stress_records = compute_stress(records, CROSS_SECTION_AREA_MM2)
    max_stress, max_stress_time = stress_stats(stress_records)
    print(f"단면적: {format_plain_number(CROSS_SECTION_AREA_MM2)} mm^2")
    print(f"최대 응력: {max_stress} MPa")
    print(f"최대 응력 시간: {format_plain_number(max_stress_time)} s")

    save_result_csv(records, stress_records, RESULT_FILE)
    print(f"결과 저장: {os.path.basename(RESULT_FILE)}")

    exceed_count = count_exceeding(stress_records, STRESS_THRESHOLD_MPA)
    print(f"기준 응력 {format_plain_number(STRESS_THRESHOLD_MPA)} MPa 초과 데이터: {exceed_count}개")

    save_stress_plot(stress_records, STRESS_PLOT_FILE, max_point=(max_stress_time, max_stress))
    print(f"그래프 저장: {os.path.basename(STRESS_PLOT_FILE)}")

    build_gui(records, stats)


if __name__ == "__main__":
    main()
