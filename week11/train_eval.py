"""
train_eval.py  (실습 3 + 선택 실습 + 모델 저장)
- 학습: 정답 시각 2023-01-01 ~ 2024-11-30 23시 (KST)
- 평가: 정답 시각 2024-12-01 00시 ~ 2024-12-31 23시, 평가 중 재학습 없음
- 비교: 현재 풍속 유지(기준) vs 선형회귀 (+ 선택: 랜덤포레스트)
- 음수 예측은 0 m/s로 바꾼다.
- predictions.csv 저장, 학습한 모델을 wind_model.joblib으로 저장하고
  마지막 관측(2024-12-31 23시)으로 2025-01-01 00시 풍속을 예측한다.

실행:      python train_eval.py
선택 실습: python train_eval.py --rf
"""
import argparse
from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error

BASE_DIR = Path(__file__).resolve().parent
DATA = BASE_DIR / "wind_dataset.csv"
SRC = BASE_DIR / "asos_108_2023_2024.csv"
PRED = BASE_DIR / "predictions.csv"
MODEL = BASE_DIR / "wind_model.joblib"

FEATURES = ["ws_now", "ws_lag1", "ws_lag2", "temp_now", "hum_now"]
TARGET = "ws_next"
TEST_START = pd.Timestamp("2024-12-01 00:00")
TEST_END = pd.Timestamp("2024-12-31 23:00")


def load():
    ds = pd.read_csv(DATA, encoding="utf-8-sig", parse_dates=["forecast_time", "target_time"])
    ds = ds.sort_values("target_time").reset_index(drop=True)          # 시간순 유지
    train = ds[ds["target_time"] < TEST_START]
    test = ds[(ds["target_time"] >= TEST_START) & (ds["target_time"] <= TEST_END)]
    return train, test


def last_observation_input():
    """배포 CSV의 마지막 시각 기준 입력 5개를 만든다 (정답은 CSV에 없음)."""
    raw = pd.read_csv(SRC, encoding="utf-8-sig", parse_dates=["datetime"]).set_index("datetime")
    t = raw.index.max()
    need = [t, t - pd.Timedelta(hours=1), t - pd.Timedelta(hours=2)]
    if any(x not in raw.index for x in need) or raw.loc[need, "wind_speed_ms"].isna().any():
        return t, None
    x = pd.DataFrame([{
        "ws_now": raw.at[t, "wind_speed_ms"],
        "ws_lag1": raw.at[need[1], "wind_speed_ms"],
        "ws_lag2": raw.at[need[2], "wind_speed_ms"],
        "temp_now": raw.at[t, "temperature_C"],
        "hum_now": raw.at[t, "humidity_pct"],
    }])
    return t, x


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rf", action="store_true", help="선택 실습: 랜덤포레스트 추가")
    args = ap.parse_args()

    train, test = load()
    print(f"학습 {len(train):,}행: 정답 {train['target_time'].min():%Y-%m-%d %H시} ~ "
          f"{train['target_time'].max():%Y-%m-%d %H시}")
    print(f"평가 {len(test):,}행: 정답 {test['target_time'].min():%Y-%m-%d %H시} ~ "
          f"{test['target_time'].max():%Y-%m-%d %H시}")

    # 기준 예측: 1시간 뒤에도 현재 풍속 그대로
    base = test["ws_now"].to_numpy()

    # 선형회귀: 2024-11까지 한 번만 학습, 12월에는 고정
    lr = LinearRegression().fit(train[FEATURES], train[TARGET])
    lr_pred = lr.predict(test[FEATURES]).clip(min=0)

    y = test[TARGET].to_numpy()
    out = pd.DataFrame({
        "forecast_time": test["forecast_time"].dt.strftime("%Y-%m-%d %H:%M"),
        "target_time": test["target_time"].dt.strftime("%Y-%m-%d %H:%M"),
        "actual_ms": y,
        "persistence_ms": base,
        "linear_ms": lr_pred.round(3),
    })
    results = [("현재 풍속 유지", mean_absolute_error(y, base)),
               ("선형회귀", mean_absolute_error(y, lr_pred))]

    if args.rf:
        rf = RandomForestRegressor(n_estimators=100, max_depth=6, min_samples_leaf=5,
                                   random_state=42, n_jobs=-1)
        rf.fit(train[FEATURES], train[TARGET])
        rf_pred = rf.predict(test[FEATURES]).clip(min=0)
        out["rf_ms"] = rf_pred.round(3)
        results.append(("랜덤포레스트", mean_absolute_error(y, rf_pred)))

    out.to_csv(PRED, index=False, encoding="utf-8-sig")

    print("\n--- 선형회귀 계수 (입력 1 단위 증가 시 예측 풍속 변화) ---")
    for f, c in zip(FEATURES, lr.coef_):
        print(f"  {f:9s} {c:+.4f}")
    print(f"  절편      {lr.intercept_:+.4f}")
    print(f"음수 예측을 0으로 바꾼 평가 행: {int((lr.predict(test[FEATURES]) < 0).sum())}개")

    print("\n--- 12월 MAE (같은 평가 행 744건) ---")
    base_mae = results[0][1]
    for name, mae in results:
        diff = "" if name == results[0][0] else f"  (기준 대비 {(base_mae - mae) / base_mae * 100:+.1f}% 감소)"
        print(f"  {name:10s} {mae:.4f} m/s{diff}")

    print("\n--- 첫 평가 결과 ---")
    print(out.head(3).to_string(index=False))
    print(f"\n저장: {PRED.name}")

    # 모델 저장 후 다음 시각 예측
    joblib.dump({"model": lr, "features": FEATURES}, MODEL)
    t, x = last_observation_input()
    if x is None:
        print(f"\n[주의] {t:%Y-%m-%d %H시} 기준 입력에 빈 값이 있어 다음 시각 예측을 건너뜀")
        return
    saved = joblib.load(MODEL)
    nxt = max(float(saved["model"].predict(x[saved["features"]])[0]), 0.0)
    print(f"\n모델 저장: {MODEL.name}")
    print(f"마지막 관측 {t:%Y-%m-%d %H시} 입력: " +
          ", ".join(f"{k}={v}" for k, v in x.iloc[0].items()))
    print(f"→ {t + pd.Timedelta(hours=1):%Y-%m-%d %H시} 풍속 예측: {nxt:.2f} m/s (실제값은 배포 CSV에 없음)")


if __name__ == "__main__":
    main()
