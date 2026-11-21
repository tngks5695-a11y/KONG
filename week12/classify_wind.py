"""
classify_wind.py  (12주차 실습 1~4: 1시간 뒤 강풍 여부 분류)

입력 5개(예측 시각까지 알 수 있는 값): 현재 풍속·기온·습도, 1시간 전 풍속, 2시간 전 풍속
정답: 1시간 뒤 실제 풍속이 4.0 m/s 이상이면 1(강풍), 아니면 0
학습: 정답 시각 2023-01-01 ~ 2024-11-30 (KST) / 평가: 정답 시각 2024-12-01 ~ 12-31 (KST)

실습 1  정답 붙이기, 기간 나누기, 두 시각이 정확히 1시간 차이인지 확인
실습 2  기준 예측 2개(항상 0, 현재 상태 유지) + 표준화·로지스틱 회귀
        → classification_predictions.csv
실습 3  같은 12월 744행으로 적중·놓침·오경보·정상 판정, 정확도·정밀도·재현율 비교
        → classification_scores.csv
실습 4  같은 강풍 확률에 판정 기준 0.20을 추가
        → 예측 CSV에는 새 열(pred_logit_020), 평가 CSV에는 새 행(로지스틱 0.20)

준비: 11주차 make_dataset.py로 만든 wind_dataset.csv를 이 파일과 같은 폴더에 둔다.
      열 이름 ws_next가 강의 프롬프트의 wind_next1h(1시간 뒤 실제 풍속)에 해당한다.
실행: python classify_wind.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

BASE_DIR = Path(__file__).resolve().parent
DATA = BASE_DIR / "wind_dataset.csv"
PRED_OUT = BASE_DIR / "classification_predictions.csv"
SCORE_OUT = BASE_DIR / "classification_scores.csv"

FEATURES = ["ws_now", "ws_lag1", "ws_lag2", "temp_now", "hum_now"]   # 입력 5개
NEXT_WS = "ws_next"        # 1시간 뒤 실제 풍속: 정답을 붙이는 데만 쓰고 입력에는 넣지 않음
STRONG_WS = 4.0            # 정답 기준(m/s): 1시간 뒤 풍속이 이 값 이상이면 1 (4.0 포함)
THRESHOLDS = [0.50, 0.20]  # 판정 기준: 강풍 확률이 이 값 이상이면 1로 판정 (0.20은 실습 4)
TEST_START = pd.Timestamp("2024-12-01 00:00")
TEST_END = pd.Timestamp("2024-12-31 23:00")


def col_name(t):
    """판정 기준 0.50 → 'pred_logit_050' 처럼 예측 열 이름을 만든다."""
    return f"pred_logit_{round(t * 100):03d}"


def pct(x):
    """비율을 %로 표시. 계산할 수 없는 값(NaN)은 '해당 없음'."""
    return "해당 없음" if pd.isna(x) else f"{x * 100:.1f}%"


def span(s):
    return f"{s.min():%Y-%m-%d %H시} ~ {s.max():%Y-%m-%d %H시}"


# ------------------------------------------------------------------ 실습 1
def load_and_split():
    print("=" * 18, "실습 1: CSV와 정답 확인", "=" * 18)
    if not DATA.exists():
        sys.exit(f"[중단] {DATA.name}이 없습니다. 11주차에 만든 파일을 이 폴더에 복사하세요.")
    df = pd.read_csv(DATA, encoding="utf-8-sig", parse_dates=["forecast_time", "target_time"])
    need = ["forecast_time", "target_time", NEXT_WS] + FEATURES
    lack = [c for c in need if c not in df.columns]
    if lack:
        sys.exit(f"[중단] 필요한 열이 없습니다: {lack}\n현재 열: {list(df.columns)}")

    # 시간순 유지: 정답 시각 순서로 정렬(같은 값의 순서는 바꾸지 않는 안정 정렬)
    df = df.sort_values("target_time", kind="stable").reset_index(drop=True)
    dup = int(df["target_time"].duplicated().sum())
    gap_ok = (df["target_time"] - df["forecast_time"]) == pd.Timedelta(hours=1)
    print(f"전체 {len(df):,}행, 정답 시각 {span(df['target_time'])}")
    print(f"시간순 정렬: {'확인' if df['target_time'].is_monotonic_increasing else '실패'}"
          f" / 중복 정답 시각: {dup}개")
    print(f"정답 시각 - 예측 시각 = 정확히 1시간: {int(gap_ok.sum()):,}행, 아닌 행 {int((~gap_ok).sum())}개")
    if dup or not gap_ok.all():
        sys.exit("[중단] 시각 중복이나 1시간이 아닌 행이 있습니다. wind_dataset.csv를 다시 만드세요.")

    # 정답: 1시간 뒤 실제 풍속 4.0 m/s 이상이면 1 (4.0 자체도 강풍)
    df["strong_actual"] = (df[NEXT_WS] >= STRONG_WS).astype(int)

    train = df[df["target_time"] < TEST_START].copy()
    test = df[(df["target_time"] >= TEST_START) & (df["target_time"] <= TEST_END)].copy()

    table = []
    for name, part in (("학습", train), ("12월 평가", test)):
        n1 = int(part["strong_actual"].sum())
        table.append({"구분": name, "정답 시각": span(part["target_time"]), "전체": len(part),
                      "0 (강풍 아님)": len(part) - n1, "1 (강풍)": n1,
                      "강풍 비율": f"{n1 / len(part) * 100:.1f}%"})
    print()
    print(pd.DataFrame(table).to_string(index=False))

    r = test.iloc[0]
    print(f"\n학습의 마지막 정답 시각: {train['target_time'].max():%Y-%m-%d %H시}"
          f" = 첫 평가의 예측 시각: {r['forecast_time']:%Y-%m-%d %H시}")
    print("첫 평가 행:")
    print(f"  예측 시각 {r['forecast_time']:%Y-%m-%d %H:%M} → 정답 시각 {r['target_time']:%Y-%m-%d %H:%M}")
    print(f"  입력: 현재 풍속 {r['ws_now']} / 1시간 전 {r['ws_lag1']} / 2시간 전 {r['ws_lag2']} m/s,"
          f" 기온 {r['temp_now']} °C, 습도 {r['hum_now']} %")
    print(f"  1시간 뒤 실제 풍속 {r[NEXT_WS]} m/s → 정답 {int(r['strong_actual'])}")
    return train, test


# ------------------------------------------------------------------ 실습 2 (+ 실습 4의 0.20 열)
def fit_and_predict(train, test):
    print("\n" + "=" * 15, "실습 2: 기준 예측과 분류 모델", "=" * 15)
    if NEXT_WS in FEATURES:
        sys.exit("[중단] 1시간 뒤 실제 풍속이 입력에 들어 있습니다.")

    # 표준화 기준(평균·표준편차)과 모델은 학습 행(2024-11까지)으로만 정한다
    scaler = StandardScaler().fit(train[FEATURES])
    model = LogisticRegression(max_iter=1000)       # class_weight=None: 클래스 가중치 사용 안 함
    model.fit(scaler.transform(train[FEATURES]), train["strong_actual"])

    print(f"입력 {len(FEATURES)}개: {', '.join(FEATURES)}  (정답용 {NEXT_WS}는 입력에서 제외)")
    print("표준화 기준(학습 행의 평균·표준편차)과 표준화된 입력의 계수:")
    for f, m, s, c in zip(FEATURES, scaler.mean_, scaler.scale_, model.coef_[0]):
        print(f"  {f:9s} 평균 {m:7.2f}  표준편차 {s:6.2f}  계수 {c:+.3f}")
    print(f"  절편 {model.intercept_[0]:+.3f}")

    # 12월: 학습한 표준화 기준과 모델을 그대로 적용 (평가 중 재학습 없음)
    prob = model.predict_proba(scaler.transform(test[FEATURES]))[:, 1]

    pred = pd.DataFrame({
        "forecast_time": test["forecast_time"].dt.strftime("%Y-%m-%d %H:%M"),
        "target_time": test["target_time"].dt.strftime("%Y-%m-%d %H:%M"),
        "actual_ws_ms": test[NEXT_WS].to_numpy(),
        "strong_actual": test["strong_actual"].to_numpy(),
        "ws_now_ms": test["ws_now"].to_numpy(),
        "pred_always0": 0,                                                   # 기준 1: 항상 0
        "pred_persistence": (test["ws_now"] >= STRONG_WS).astype(int).to_numpy(),  # 기준 2
        "prob_strong": prob.round(6),                                        # 강풍 추정 확률
    })
    for t in THRESHOLDS:                     # 같은 확률, 판정 기준만 다름
        pred[col_name(t)] = (prob >= t).astype(int)
    return pred


# ------------------------------------------------------------------ 실습 3 (+ 실습 4의 0.20 행)
def confusion(y, p):
    tp = int(((y == 1) & (p == 1)).sum())
    fn = int(((y == 1) & (p == 0)).sum())
    fp = int(((y == 0) & (p == 1)).sum())
    tn = int(((y == 0) & (p == 0)).sum())
    return tp, fn, fp, tn


def evaluate(pred):
    print("\n" + "=" * 15, "실습 3: 같은 12월 자료로 평가", "=" * 15)
    methods = [("항상 0", "pred_always0", "모든 시각을 0으로 예측"),
               ("현재 상태 유지", "pred_persistence", f"현재 풍속 ≥ {STRONG_WS} m/s → 1")]
    methods += [(f"로지스틱 {t:.2f}", col_name(t), f"강풍 확률 ≥ {t:.2f} → 1") for t in THRESHOLDS]

    y = pred["strong_actual"].to_numpy()
    n_strong = int(y.sum())
    rows = []
    for name, col, rule in methods:
        p = pred[col].to_numpy()                       # 모든 방법이 같은 pred 표의 같은 행을 사용
        tp, fn, fp, tn = confusion(y, p)
        rows.append({
            "방법": name, "판정 규칙": rule, "평가 행": len(p), "실제 강풍": n_strong,
            "적중(TP)": tp, "놓침(FN)": fn, "오경보(FP)": fp, "정상 판정(TN)": tn,
            "정확도(%)": round((tp + tn) / len(p) * 100, 1),
            "정밀도(%)": round(tp / (tp + fp) * 100, 1) if tp + fp else np.nan,  # 1로 예측한 행이 없으면 해당 없음
            "재현율(%)": round(tp / (tp + fn) * 100, 1) if tp + fn else np.nan,
        })
    scores = pd.DataFrame(rows)

    same_rows = scores["평가 행"].nunique() == 1 and (scores["적중(TP)"] + scores["놓침(FN)"] == n_strong).all()
    print(f"평가 행: {len(pred)}행 (정답 시각 {pred['target_time'].iloc[0]} ~ {pred['target_time'].iloc[-1]})")
    print(f"실제 강풍: {n_strong}건 / 모든 방법이 같은 평가 행 사용, 적중 + 놓침 = {n_strong}: "
          f"{'확인' if same_rows else '불일치'}")

    show = scores[["방법", "정확도(%)", "정밀도(%)", "재현율(%)", "적중(TP)", "오경보(FP)", "놓침(FN)", "정상 판정(TN)"]].copy()
    for c in ("정확도(%)", "정밀도(%)", "재현율(%)"):
        show[c] = [pct(v / 100) for v in show[c]]
    print()
    print(show.to_string(index=False))
    return scores


def compare_thresholds(scores):
    print("\n" + "=" * 15, "실습 4: 판정 기준 0.50 vs 0.20", "=" * 15)
    print(f"같은 모델·같은 강풍 확률 사용, 실제 강풍 기준은 {STRONG_WS} m/s 그대로")
    t = scores[scores["방법"].str.startswith("로지스틱")].copy()
    t.insert(0, "판정 기준", t["방법"].str.replace("로지스틱 ", "", regex=False))
    show = t[["판정 기준", "적중(TP)", "놓침(FN)", "오경보(FP)", "정밀도(%)", "재현율(%)"]].copy()
    for c in ("정밀도(%)", "재현율(%)"):
        show[c] = [pct(v / 100) for v in show[c]]
    print(show.to_string(index=False))
    a, b = t.iloc[0], t.iloc[1]
    print(f"\n{b['판정 기준']}에서는 강풍을 {b['적중(TP)'] - a['적중(TP)']}건 더 맞혔고,"
          f" 오경보도 {b['오경보(FP)'] - a['오경보(FP)']}건 늘었음.")


def main():
    train, test = load_and_split()
    pred = fit_and_predict(train, test)
    pred.to_csv(PRED_OUT, index=False, encoding="utf-8-sig")
    print(f"\n저장: {PRED_OUT.name} ({len(pred)}행)")
    print("예측 CSV 첫 5행:")
    print(pd.read_csv(PRED_OUT, encoding="utf-8-sig").head(5).to_string(index=False))

    scores = evaluate(pred)
    scores.to_csv(SCORE_OUT, index=False, encoding="utf-8-sig", na_rep="해당 없음")
    print(f"\n저장: {SCORE_OUT.name} ({len(scores)}행)")

    compare_thresholds(scores)


if __name__ == "__main__":
    main()
