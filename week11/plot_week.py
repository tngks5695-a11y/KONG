"""
plot_week.py  (실습 4: 일주일치 예측 그래프)
predictions.csv에서 정답 시각 2024-12-01 00시 ~ 12-07 23시를 골라
실제값(검정), 현재 풍속 유지(회색 점선), 선형회귀(파랑)를 한 그림에 그린다.
MAE는 12월 1~31일 전체로 계산하고, 크게 틀린 시각도 출력한다.

실행: python plot_week.py
"""
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
PRED = BASE_DIR / "predictions.csv"
OUT = BASE_DIR / "prediction_week.png"


def main():
    df = pd.read_csv(PRED, encoding="utf-8-sig", parse_dates=["forecast_time", "target_time"])
    df = df.sort_values("target_time")

    # MAE: 12월 전체
    mae_base = (df["actual_ms"] - df["persistence_ms"]).abs().mean()
    mae_lr = (df["actual_ms"] - df["linear_ms"]).abs().mean()
    print(f"12월 전체 {len(df)}건 MAE — 현재 풍속 유지 {mae_base:.3f} / 선형회귀 {mae_lr:.3f} m/s")

    week = df[(df["target_time"] >= "2024-12-01 00:00") & (df["target_time"] <= "2024-12-07 23:00")]
    week = week.set_index("target_time")
    # 1시간 격자로 맞춰 빠진 시각이 있으면 선을 끊는다
    grid = pd.date_range("2024-12-01 00:00", "2024-12-07 23:00", freq=pd.Timedelta(hours=1))
    week = week.reindex(grid)
    print(f"그래프 구간: {grid[0]:%Y-%m-%d %H시} ~ {grid[-1]:%Y-%m-%d %H시}, "
          f"값 있는 시각 {int(week['actual_ms'].notna().sum())}/{len(grid)}")

    fig, ax = plt.subplots(figsize=(12, 4.8))
    ax.plot(week.index, week["actual_ms"], color="black", lw=1.6, label="Actual")
    ax.plot(week.index, week["persistence_ms"], color="gray", ls="--", lw=1.2,
            label=f"Persistence (Dec MAE {mae_base:.3f})")
    ax.plot(week.index, week["linear_ms"], color="#1f5fbf", lw=1.4,
            label=f"Linear regression (Dec MAE {mae_lr:.3f})")
    ax.set_title("Seoul ASOS 108 · 1-hour-ahead wind speed, 2024-12-01 ~ 12-07")
    ax.set_xlabel("Target time (KST)")
    ax.set_ylabel("Wind speed (m/s)")
    top = week[["actual_ms", "persistence_ms", "linear_ms"]].max().max()
    ax.set_ylim(0, top * 1.3)                      # 범례가 최고점을 가리지 않도록 위쪽 여백
    ax.xaxis.set_major_locator(mdates.DayLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    ax.xaxis.set_minor_locator(mdates.HourLocator(byhour=[6, 12, 18]))
    ax.grid(alpha=0.3)
    ax.legend(loc="upper center", ncol=3, frameon=False)
    fig.tight_layout()
    fig.savefig(OUT, dpi=150)
    print(f"그림 저장: {OUT.name}")

    # 크게 틀린 시각: 분석 근거
    w = week.dropna(subset=["actual_ms"]).copy()
    w["lr_err"] = w["linear_ms"] - w["actual_ms"]
    w["base_err"] = w["persistence_ms"] - w["actual_ms"]
    top = w.reindex(w["lr_err"].abs().sort_values(ascending=False).index).head(5)
    print("\n--- 이번 주 선형회귀 절대오차 상위 5개 (오차 = 예측 - 실제) ---")
    for t, r in top.iterrows():
        print(f"  {t:%m-%d %H시}  실제 {r['actual_ms']:.1f}  유지 {r['persistence_ms']:.1f}"
              f"  선형 {r['linear_ms']:.2f}  선형오차 {r['lr_err']:+.2f}")

    plt.show()


if __name__ == "__main__":
    main()
