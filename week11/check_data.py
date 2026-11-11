"""
check_data.py  (실습 1: CSV 상태 확인)
asos_108_2023_2024.csv를 읽어 시각 순서, 행 수, 중복, 행이 없는 시각, 열별 빈칸을 확인한다.
원본 파일은 수정하지 않는다.

실행: python check_data.py
"""
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
SRC = BASE_DIR / "asos_108_2023_2024.csv"


def main():
    df = pd.read_csv(SRC, encoding="utf-8-sig")
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.sort_values("datetime").reset_index(drop=True)   # 읽은 사본만 정렬, 원본은 그대로

    print("--- 처음 3행 ---")
    print(df.head(3).to_string(index=False))

    first, last = df["datetime"].iloc[0], df["datetime"].iloc[-1]
    grid = pd.date_range(first, last, freq=pd.Timedelta(hours=1))   # 1시간 격자
    missing = grid.difference(pd.DatetimeIndex(df["datetime"]))

    print("\n--- 검사 결과 ---")
    print(f"처음 시각: {first:%Y-%m-%d %H:%M}")
    print(f"마지막 시각: {last:%Y-%m-%d %H:%M}")
    print(f"전체 행 수: {len(df):,}")
    print(f"중복 시각: {int(df['datetime'].duplicated().sum())}개")
    print(f"1시간 격자: {len(grid):,}시간 / 행이 없는 시각: {len(missing)}개")
    print("기존 행 안의 빈칸:")
    for col in ("wind_speed_ms", "temperature_C", "humidity_pct"):
        print(f"  {col}: {int(df[col].isna().sum())}개")
    print(f"풍속 0 m/s 행: {int((df['wind_speed_ms'] == 0).sum())}개 (정상 관측값, 빈칸 아님)")

    # 행이 없는 시각을 연속 구간으로 묶어 보여준다
    if len(missing):
        print("\n행이 없는 구간:")
        s = pd.Series(missing)
        block = (s.diff() != pd.Timedelta(hours=1)).cumsum()
        for _, g in s.groupby(block):
            a, b = g.iloc[0], g.iloc[-1]
            span = f"{a:%Y-%m-%d %H시}" if a == b else f"{a:%Y-%m-%d %H시} ~ {b:%Y-%m-%d %H시}"
            print(f"  {span} ({len(g)}개)")


if __name__ == "__main__":
    main()
