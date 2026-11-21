"""
plot_strong_wind.py  (12주차 실습 5: 시간 그래프로 보기)

classification_predictions.csv에서 정답 시각이 2024-12-01 ~ 12-07인 행을 골라
  위쪽: 실제 풍속과 4.0 m/s 기준선
  아래쪽: 실제 강풍, 로지스틱 0.50·0.20의 강풍 예측을 시각별 점으로 표시
두 그래프는 같은 정답 시각(KST)을 가로축으로 쓴다.
strong_wind_december.png로 저장하고 12월 2일의 틀린 사례(놓침·오경보)를 출력한다.

실행: python classify_wind.py 를 먼저 실행한 뒤  python plot_strong_wind.py
"""
import sys
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

BASE_DIR = Path(__file__).resolve().parent
PRED = BASE_DIR / "classification_predictions.csv"
OUT = BASE_DIR / "strong_wind_december.png"

STRONG_WS = 4.0
WEEK_START = pd.Timestamp("2024-12-01 00:00")
WEEK_END = pd.Timestamp("2024-12-07 23:00")
CASE_DAY = pd.Timestamp("2024-12-02")
RULES = [("pred_logit_050", "0.50"), ("pred_logit_020", "0.20")]

INK, INK2, GRID, BAND = "#0b0b0b", "#52514e", "#e4e3df", "#ecebe7"
COLOR = {"pred_logit_050": "#2a78d6", "pred_logit_020": "#eb6834"}   # 검증한 2색 (blue, orange)


def load_week():
    if not PRED.exists():
        sys.exit(f"[중단] {PRED.name}이 없습니다. classify_wind.py를 먼저 실행하세요.")
    df = pd.read_csv(PRED, encoding="utf-8-sig", parse_dates=["forecast_time", "target_time"])
    week = df[(df["target_time"] >= WEEK_START) & (df["target_time"] <= WEEK_END)].set_index("target_time")
    grid = pd.date_range(WEEK_START, WEEK_END, freq=pd.Timedelta(hours=1))
    print(f"정답 시각 {WEEK_START:%m-%d %H시} ~ {WEEK_END:%m-%d %H시}: {len(week)}/{len(grid)}행")
    return week.reindex(grid)          # 빠진 시각이 있으면 선이 끊어지도록 1시간 격자에 맞춤


def outcome(actual, pred):
    if actual == 1:
        return "적중 (1을 1로)" if pred == 1 else "놓침 (1을 0으로)"
    return "오경보 (0을 1로)" if pred == 1 else "정상 판정"


def report(week):
    w = week.dropna(subset=["strong_actual"])
    y = w["strong_actual"].astype(int)
    print(f"이번 주 실제 강풍: {int(y.sum())}시간")
    for col, t in RULES:
        p = w[col].astype(int)
        print(f"  판정 {t}: 적중 {int(((y == 1) & (p == 1)).sum())}, 놓침 {int(((y == 1) & (p == 0)).sum())},"
              f" 오경보 {int(((y == 0) & (p == 1)).sum())}")

    day = w[w.index.normalize() == CASE_DAY]
    print(f"\n--- {CASE_DAY:%m월 %d일} 틀린 사례 (정답 시각 기준) ---")
    for col, t in RULES:
        wrong = day[day["strong_actual"] != day[col]]
        print(f"판정 {t}: {len(wrong)}건")
        for ts, r in wrong.iterrows():
            print(f"  {ts:%H}시  실제 {r['actual_ws_ms']:.1f} m/s(정답 {int(r['strong_actual'])}),"
                  f" 강풍 확률 {r['prob_strong'] * 100:.1f}% → {outcome(r['strong_actual'], r[col])},"
                  f" 예측 시각 {r['forecast_time']:%H}시 풍속 {r['ws_now_ms']:.1f} m/s")

    # 대표 사례: 이 날 실제 강풍인데 확률이 가장 낮았던 시각 (두 판정 모두 놓침)
    missed = day[day["strong_actual"] == 1].sort_values("prob_strong")
    case = (missed.index[0], missed.iloc[0]) if len(missed) else None
    if case:
        ts, r = case
        print(f"\n찾은 사례: {ts:%m-%d %H시} 놓침 — {r['forecast_time']:%H}시 풍속 {r['ws_now_ms']:.1f} m/s에서"
              f" {ts:%H}시 {r['actual_ws_ms']:.1f} m/s로 급증. 강풍 확률 {r['prob_strong'] * 100:.1f}%라"
              f" 0.50·0.20 모두 0으로 판정.")
    return case


def draw(week, case):
    fig, (ax1, ax2) = plt.subplots(2, 1, sharex=True, figsize=(12, 6.4),
                                   gridspec_kw={"height_ratios": [2.3, 1]})
    t = week.index
    strong_hours = t[week["strong_actual"] == 1]

    # 두 그래프에 같은 실제 강풍 시각 띠: 띠 위에 예측 점이 없으면 놓침
    for ax in (ax1, ax2):
        for h in strong_hours:
            ax.axvspan(h - pd.Timedelta(minutes=30), h + pd.Timedelta(minutes=30),
                       color=BAND, lw=0, zorder=0)
        ax.grid(axis="y", color=GRID, lw=0.8)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)

    # 위쪽: 실제 풍속과 4.0 m/s 기준선
    ax1.plot(t, week["actual_ws_ms"], color=INK, lw=1.6, label="Actual wind speed")
    ax1.axhline(STRONG_WS, color=INK2, ls="--", lw=1.2, label=f"{STRONG_WS} m/s threshold")
    ax1.set_ylim(0, max(6.0, week["actual_ws_ms"].max() * 1.15))
    ax1.set_ylabel("Wind speed (m/s)")
    ax1.set_title("Seoul ASOS 108 · strong wind (≥ 4.0 m/s) one hour ahead, 2024-12-01 ~ 12-07 (KST)",
                  loc="left", fontsize=11)
    if case:
        ts, r = case
        ax1.scatter([ts], [r["actual_ws_ms"]], s=70, facecolor="none", edgecolor=INK, lw=1.4, zorder=4)
        ax1.annotate(f"{ts:%m-%d %H}h missed\n{r['actual_ws_ms']:.1f} m/s, p = {r['prob_strong'] * 100:.1f}%",
                     xy=(ts, r["actual_ws_ms"]), xytext=(ts + pd.Timedelta(hours=6), 5.5),
                     fontsize=9, color=INK2, arrowprops=dict(arrowstyle="-", color=INK2, lw=0.8))
    ax1.legend(loc="upper right", frameon=False, ncol=2, fontsize=9)

    # 아래쪽: 시각별 점 (채운 점 = 적중, 빈 점 = 오경보)
    actual = week["strong_actual"] == 1
    ax2.scatter(t[actual], [2] * int(actual.sum()), s=26, color=INK, zorder=3)
    for y_pos, (col, _) in zip((1, 0), RULES):
        pred1 = week[col] == 1
        hit, fa = pred1 & actual, pred1 & ~actual
        ax2.scatter(t[hit], [y_pos] * int(hit.sum()), s=26, color=COLOR[col], zorder=3)
        ax2.scatter(t[fa], [y_pos] * int(fa.sum()), s=26, facecolor="white",
                    edgecolor=COLOR[col], lw=1.3, zorder=3)
    ax2.set_yticks([2, 1, 0], ["Actual strong", "Logistic p ≥ 0.50", "Logistic p ≥ 0.20"])
    ax2.set_ylim(-0.6, 2.6)
    ax2.set_xlabel("Target time (KST)")
    handles = [Patch(color=BAND, label="Actual strong hour (band without a dot = miss)"),
               Line2D([], [], ls="", marker="o", color=INK2, label="Hit"),
               Line2D([], [], ls="", marker="o", markerfacecolor="white", markeredgecolor=INK2,
                      label="False alarm")]
    ax2.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.42), ncol=3,
               frameon=False, fontsize=9)

    ax2.set_xlim(WEEK_START - pd.Timedelta(hours=2), WEEK_END + pd.Timedelta(hours=2))
    ax2.xaxis.set_major_locator(mdates.DayLocator())
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    ax2.xaxis.set_minor_locator(mdates.HourLocator(byhour=[6, 12, 18]))
    fig.tight_layout()
    fig.savefig(OUT, dpi=150)
    print(f"\n그림 저장: {OUT.name}")


def main():
    week = load_week()
    case = report(week)
    draw(week, case)
    plt.show()                       # 그래프 창을 닫아야 터미널로 돌아옴


if __name__ == "__main__":
    main()
