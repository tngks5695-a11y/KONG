"""
make_dataset.py  (실습 2: 입력과 정답을 한 행에 만들기)
1) 빠진 시각을 빈 행으로 넣어 정확한 1시간 간격을 만든다.
2) 각 행 = 한 번의 예측
   입력 5개: 현재 풍속, 1시간 전 풍속, 2시간 전 풍속, 현재 기온, 현재 습도
   정답 1개: 정확히 1시간 뒤 실제 풍속 (입력에는 넣지 않음)
3) 입력이나 정답이 빈 행만 빼고, 빈 값은 채우지 않는다.
4) wind_dataset.csv로 저장한다.

실행: python make_dataset.py
"""
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
SRC = BASE_DIR / "asos_108_2023_2024.csv"
OUT = BASE_DIR / "wind_dataset.csv"

FEATURES = ["ws_now", "ws_lag1", "ws_lag2", "temp_now", "hum_now"]
TARGET = "ws_next"


def build():
    raw = pd.read_csv(SRC, encoding="utf-8-sig")
    raw["datetime"] = pd.to_datetime(raw["datetime"])
    raw = raw.sort_values("datetime").drop_duplicates("datetime").set_index("datetime")

    # 1시간 격자로 맞춤: 빠진 시각은 모든 값이 빈 행이 된다
    grid = pd.date_range(raw.index.min(), raw.index.max(), freq=pd.Timedelta(hours=1))
    hourly = raw.reindex(grid)
    hourly.index.name = "datetime"
    print(f"원본 행 수: {len(raw):,} → 1시간 간격 맞춘 뒤: {len(hourly):,}")

    # 격자가 일정하므로 shift(1)은 '정확히 1시간 전', shift(-1)은 '정확히 1시간 뒤'
    ws = hourly["wind_speed_ms"]
    ds = pd.DataFrame({
        "forecast_time": hourly.index,                         # 예측을 하는 시각(현재)
        "target_time": hourly.index + pd.Timedelta(hours=1),   # 맞힐 시각
        "ws_now": ws.values,
        "ws_lag1": ws.shift(1).values,
        "ws_lag2": ws.shift(2).values,
        "temp_now": hourly["temperature_C"].values,
        "hum_now": hourly["humidity_pct"].values,
        TARGET: ws.shift(-1).values,
    })

    before = len(ds)
    ds = ds.dropna(subset=FEATURES + [TARGET]).reset_index(drop=True)
    print(f"입력·정답 빈 행 제외: {before - len(ds):,}행")
    return ds, hourly


def main():
    ds, hourly = build()
    ds.to_csv(OUT, index=False, encoding="utf-8-sig", date_format="%Y-%m-%d %H:%M")
    print(f"저장 행 수: {len(ds):,}  →  {OUT.name}")
    print("\n--- 첫 4행 ---")
    print(ds.head(4).to_string(index=False))

    # 첫 행 정답이 원본의 '정확히 1시간 뒤' 풍속과 같은지 확인
    r = ds.iloc[0]
    src_val = hourly.loc[r["target_time"], "wind_speed_ms"]
    ok = "일치" if src_val == r[TARGET] else "불일치"
    print(f"\n검증: 첫 행 정답 {r[TARGET]} m/s = 원본 {r['target_time']:%Y-%m-%d %H시} 풍속 {src_val} m/s → {ok}")


if __name__ == "__main__":
    main()
