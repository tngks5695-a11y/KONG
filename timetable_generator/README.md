# 수강신청 시간표 자동 생성기

학교 포털의 개설강의 목록(.xlsx)을 읽어서 사용자 조건을 모두 만족하는 시간표 조합을 만들고, 선호도 점수 순서로 보여 줍니다.

> 단계별로 개발하고 있습니다. 지금은 **Phase 1(엑셀 구조 분석, 컬럼 매핑, mock 데이터)** 까지 끝났습니다. 문제 정의, 알고리즘, 성능 표는 Phase 6에서 채웁니다.

## 실행 방법 (현재 단계)

```bash
cd timetable_generator
pip install -r requirements.txt

python -m timetable.mock_data --out data                 # mock 엑셀 2개 생성 (50강좌, 200강좌)
python -m timetable.loader data/mock_courses_50.xlsx     # 구조 분석 리포트 출력
python -m timetable.loader 내파일.xlsx --issues          # 실제 포털 파일 점검 (문제 행 전체 출력)
python -m pytest                                         # 테스트
```

## 구조

| 파일 | 내용 | 상태 |
|---|---|---|
| `timetable/config.py` | 컬럼 동의어, 교시 시각표, 정규화 규칙, mock 파라미터 | Phase 1 |
| `timetable/models.py` | `Course`, `Category`, 비트마스크 헬퍼 | Phase 1 |
| `timetable/loader.py` | 엑셀 로드, 헤더 행 탐지, 컬럼 자동 매핑, 값 정규화, 구조 분석 리포트 | Phase 1 |
| `timetable/mock_data.py` | mock 개설강의 엑셀 생성기 (정답 슬롯 포함) | Phase 1 |
| `data/mock_courses_50.xlsx` | A형: 제목 행 + 표준 헤더, 모든 시간 표기와 특수 케이스 포함 | Phase 1 |
| `data/mock_courses_200.xlsx` | B형: 다른 헤더명, `코드-분반` 결합 셀, `3-3-0` 학점, 반복 헤더 | Phase 1 |
| `parser.py`, `filters.py`, `solver.py`, `scorer.py`, `exporter.py`, `app.py` | | Phase 2~5 |
