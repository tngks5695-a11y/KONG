"""Phase 1: 엑셀 로드·헤더 탐지·컬럼 매핑·값 정규화 테스트."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any, Sequence

import pytest
from openpyxl import Workbook, load_workbook

from timetable import config
from timetable.loader import (
    LEVEL_ERROR,
    LEVEL_INFO,
    LEVEL_WARNING,
    METHOD_BASE,
    METHOD_EXACT,
    METHOD_MISSING,
    METHOD_OVERRIDE,
    METHOD_PARTIAL,
    MappingError,
    analyze_structure,
    auto_map_columns,
    is_online_delivery,
    load_course_table,
    normalize_category,
    normalize_header,
    normalize_section,
    parse_credits,
    parse_grade,
    split_code_section,
    time_shape,
)
from timetable.mock_data import generate_sections, write_variant_a, write_variant_b
from timetable.models import Category

BASIC_HEADER = ["과목코드", "분반", "과목명", "학점", "이수구분", "강의시간"]


def write_xlsx(path: Path, rows: Sequence[Sequence[Any]], sheet: str = "Sheet1") -> Path:
    """행 리스트를 그대로 엑셀로 쓴다(None = 빈 셀)."""
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    for row in rows:
        ws.append(list(row))
    wb.save(path)
    return path


@pytest.fixture(scope="module")
def small_mock(tmp_path_factory: pytest.TempPathFactory):
    """소형(A형) mock 파일과 정답."""
    sections = generate_sections(config.MOCK_SMALL_SIZE)
    path = tmp_path_factory.mktemp("mock") / "small.xlsx"
    write_variant_a(sections, path)
    return path, sections


@pytest.fixture(scope="module")
def large_mock(tmp_path_factory: pytest.TempPathFactory):
    """대형(B형) mock 파일과 정답."""
    sections = generate_sections(config.MOCK_LARGE_SIZE)
    path = tmp_path_factory.mktemp("mock") / "large.xlsx"
    write_variant_b(sections, path)
    return path, sections


# ---------------------------------------------------------------------------
# 헤더 정규화 / 매핑
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (" 교과목 명 ", "교과목명"),
        ("학점（이론－실습）", "학점(이론-실습)"),  # 전각 → 반각
        ("Course Code", "coursecode"),
        ("*강의시간", "강의시간"),
        ("강의\n시간", "강의시간"),
        (None, ""),
    ],
)
def test_normalize_header(raw: Any, expected: str) -> None:
    assert normalize_header(raw) == expected


def test_auto_map_exact_synonyms() -> None:
    headers = ["학수번호", "분반", "교과목명", "학점", "이수구분", "개설학과", "대상학년",
               "담당교수", "강의시간", "강의실", "수업방식"]
    matches = auto_map_columns(headers)
    assert {f: m.column for f, m in matches.items()} == dict(zip(config.STANDARD_FIELDS, headers))
    assert all(m.method == METHOD_EXACT for m in matches.values())


def test_auto_map_base_and_partial() -> None:
    matches = auto_map_columns(["학수번호-분반", "강좌명", "학점(이론-실습)", "요일/시간"])
    assert matches["code"].column == "학수번호-분반"
    assert matches["code"].method == METHOD_PARTIAL
    assert matches["credits"].method == METHOD_BASE
    assert matches["section"].method == METHOD_MISSING


def test_exact_beats_base_for_same_field() -> None:
    matches = auto_map_columns(["교과목명(영문)", "교과목명", "학점"])
    assert matches["name"].column == "교과목명"


def test_one_column_used_once() -> None:
    # "강의시간/강의실"은 강의시간으로만 쓰이고 강의실은 비어야 한다.
    matches = auto_map_columns(["과목코드", "과목명", "학점", "강의시간/강의실"])
    assert matches["time"].column == "강의시간/강의실"
    assert matches["room"].column is None


def test_short_synonym_not_partial() -> None:
    # "구분"(2자)은 부분일치 금지 → "학년구분"이 이수구분으로 잡히면 안 된다.
    matches = auto_map_columns(["과목코드", "학년구분"])
    assert matches["category"].column is None


def test_override_wins_and_can_clear() -> None:
    headers = ["코드", "과목명", "학점", "시간정보", "강의실"]
    matches = auto_map_columns(headers, overrides={"code": "코드", "time": "시간정보", "room": None})
    assert matches["code"].column == "코드" and matches["code"].method == METHOD_OVERRIDE
    assert matches["time"].column == "시간정보"
    assert matches["room"].column is None


def test_override_unknown_column_or_field() -> None:
    with pytest.raises(MappingError, match="헤더에 없습니다"):
        auto_map_columns(["과목코드"], overrides={"code": "없는컬럼"})
    with pytest.raises(MappingError, match="알 수 없는 표준 필드"):
        auto_map_columns(["과목코드"], overrides={"nope": "과목코드"})


# ---------------------------------------------------------------------------
# 값 정규화
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("3", 3.0), ("3-3-0", 3.0), ("2.5", 2.5), ("3(3)", 3.0), ("3학점", 3.0), ("0", 0.0),
     ("", None), ("학점없음", None)],
)
def test_parse_credits(raw: str, expected: float | None) -> None:
    assert parse_credits(raw) == expected


@pytest.mark.parametrize(
    ("raw", "category", "known"),
    [
        ("전필", Category.MAJOR, True), ("전선", Category.MAJOR, True),
        ("전공 필수", Category.MAJOR, True), ("전기", Category.MAJOR, True),
        ("전공탐색", Category.MAJOR, True), ("전탐", Category.MAJOR, True),
        ("교필", Category.GENERAL, True), ("교양선택", Category.GENERAL, True),
        ("기교", Category.GENERAL, True), ("핵심교양", Category.GENERAL, True),
        ("교양(인문)", Category.GENERAL, True),
        ("일선", Category.OTHER, True), ("교직", Category.OTHER, True),
        ("", Category.OTHER, False), ("군사학", Category.OTHER, False),
    ],
)
def test_normalize_category(raw: str, category: Category, known: bool) -> None:
    assert normalize_category(raw) == (category, known)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2", {2}), ("2학년", {2}), ("1,2", {1, 2}), ("1~3", {1, 2, 3}), ("3-4", {3, 4}),
        ("1·2학년", {1, 2}), ("1,2학년", {1, 2}),
        ("전체", set()), ("전학년", set()), ("", set()), ("0", set()),
        ("7", None), ("3~1", None), ("상위", None),
    ],
)
def test_parse_grade(raw: str, expected: set[int] | None) -> None:
    result = parse_grade(raw)
    assert (None if result is None else set(result)) == expected


@pytest.mark.parametrize(("raw", "expected"), [("1", "01"), ("02", "02"), ("10", "10"), ("a", "A")])
def test_normalize_section(raw: str, expected: str) -> None:
    assert normalize_section(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("CSE2010-01", ("CSE2010", "01")), ("CSE2010_3", ("CSE2010", "03")),
     ("CSE2010", ("CSE2010", None)), ("GED-101", ("GED-101", None))],
)
def test_split_code_section(raw: str, expected: tuple[str, str | None]) -> None:
    assert split_code_section(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("원격", True), ("온라인(비대면)", True), ("Online", True), ("대면", False),
     ("혼합(원격+대면)", False), ("", False)],
)
def test_is_online_delivery(raw: str, expected: bool) -> None:
    assert is_online_delivery(raw) is expected


def test_time_shape() -> None:
    assert time_shape("월1,2(공학관301) 수3") == "D9,9(가9) D9"
    assert time_shape("월요일 오전") == "가 가"


# ---------------------------------------------------------------------------
# mock 파일 전체 로드
# ---------------------------------------------------------------------------


def _index(table) -> dict[tuple[str, str], dict]:
    return {(r["code"], r["section"]): r for r in table.to_dict("records")}


def test_small_mock_structure(small_mock) -> None:
    path, sections = small_mock
    result = load_course_table(path)
    assert result.mapping.header_row == 4  # 제목 2행 + 빈 행 아래
    assert result.mapping.missing_required == []
    assert all(m.method == METHOD_EXACT for m in result.mapping.matches.values())
    assert result.mapping.unmapped_columns == ["No", "비고"]
    assert len(result.table) == len(sections) == config.MOCK_SMALL_SIZE
    assert not [i for i in result.issues if i.level == LEVEL_ERROR]


def test_small_mock_values_match_truth(small_mock) -> None:
    path, sections = small_mock
    rows = _index(load_course_table(path).table)
    for s in sections:
        row = rows[(s.code, s.section)]
        expected_time = s.time_text
        if s.continuation_text:
            expected_time += config.MULTI_ROW_TIME_JOINER + s.continuation_text
        assert row["raw_time"] == expected_time
        assert row["name"] == s.name
        assert row["credits"] == s.credits
        assert row["category_raw"] == s.category_raw
        assert row["dept"] == s.dept
        assert row["professor"] == s.professor
        assert row["online_by_delivery"] is (s.delivery == "원격")


def test_small_mock_continuation_rows(small_mock) -> None:
    path, sections = small_mock
    result = load_course_table(path)
    merged = result.table[result.table["merged_rows"].map(len) > 0]
    assert len(merged) == sum(1 for s in sections if s.continuation_text) > 0
    for row in merged.to_dict("records"):
        assert row["merged_rows"] == (row["row"] + 1,)
    assert sum(1 for i in result.issues if i.level == LEVEL_INFO and "이어지는 행" in i.message) == len(merged)


def test_small_mock_row_numbers_point_to_excel(small_mock) -> None:
    path, _ = small_mock
    result = load_course_table(path)
    ws = load_workbook(path).active
    code_col = result.mapping.columns.index("학수번호") + 1
    for row in result.table.to_dict("records"):
        assert ws.cell(row=row["row"], column=code_col).value == row["code"]


def test_large_mock_structure(large_mock) -> None:
    path, sections = large_mock
    result = load_course_table(path)
    m = result.mapping
    assert m.header_row == 1
    assert m.column_for("section") is None  # 코드-분반 결합 셀에서 분리
    assert m.unmapped_columns == ["정원"]
    assert len(result.table) == len(sections) == config.MOCK_LARGE_SIZE
    assert any(i.message == "반복 헤더 행 제거" for i in result.issues)
    assert not [i for i in result.issues if i.level in (LEVEL_ERROR, LEVEL_WARNING)]


def test_large_mock_values_match_truth(large_mock) -> None:
    path, sections = large_mock
    rows = _index(load_course_table(path).table)
    for s in sections:
        row = rows[(s.code, s.section)]  # "CSE2010-01" → ("CSE2010", "01")
        assert row["credits"] == s.credits  # "3-3-0" → 3.0
        assert row["raw_time"] == s.time_text
        expected_grade = parse_grade(s.grade_raw)
        assert row["grade"] == expected_grade
    categories = {r["category_raw"]: r["category"] for r in rows.values()}
    assert categories["전공필수"] is Category.MAJOR
    assert categories["교양선택"] is Category.GENERAL
    assert categories["일반선택"] is Category.OTHER


def test_file_like_source(small_mock) -> None:
    path, _ = small_mock
    buffer = io.BytesIO(path.read_bytes())
    assert len(load_course_table(buffer).table) == config.MOCK_SMALL_SIZE
    # 같은 버퍼를 다시 읽어도 된다(Streamlit 재실행 대비 seek(0)).
    assert len(load_course_table(buffer).table) == config.MOCK_SMALL_SIZE


def test_analyze_structure_report(small_mock) -> None:
    path, _ = small_mock
    report = analyze_structure(path)
    text = report.to_text()
    assert "헤더 행: 4행" in text
    assert report.fill_rates["비고"] == 0.0
    assert report.time_shapes  # 강의시간 형태 집계가 있어야 함


# ---------------------------------------------------------------------------
# 오류·경계 케이스
# ---------------------------------------------------------------------------


def test_missing_required_field_raises(tmp_path: Path) -> None:
    path = write_xlsx(tmp_path / "x.xlsx", [["과목코드", "과목명", "학점", "강의실"], ["A1", "가", 3, "101"]])
    with pytest.raises(MappingError, match="강의시간"):
        load_course_table(path)


def test_no_header_raises(tmp_path: Path) -> None:
    path = write_xlsx(tmp_path / "x.xlsx", [["foo", "bar", "baz"], [1, 2, 3]])
    with pytest.raises(MappingError, match="헤더 행을 찾지 못했습니다"):
        load_course_table(path)


def test_override_rescues_unknown_header(tmp_path: Path) -> None:
    path = write_xlsx(tmp_path / "x.xlsx", [["과목코드", "과목명", "학점", "언제"], ["A1", "가", 3, "월1"]])
    result = load_course_table(path, overrides={"time": "언제"})
    assert result.table.loc[0, "raw_time"] == "월1"


def test_problem_rows_are_reported_not_lost(tmp_path: Path) -> None:
    rows = [
        BASIC_HEADER,
        [None, None, None, None, None, "월1"],        # 2: 앞 강좌 없는 이어지는 행
        ["A100", 1, "자료구조", 3, "전필", "월1,2"],   # 3: 정상
        ["A100", 1, "자료구조", 3, "전필", "수3"],     # 4: 같은 키 → 병합
        ["A100", 1, "다른과목", 3, "전필", "금1"],     # 5: 같은 키, 다른 과목명 → 제외
        [None, 2, "코드없음", 3, "전선", "화1"],       # 6: 코드 없음 → 제외
        ["B200", 1, "학점이상", "삼", "전선", "화1"],  # 7: 학점 해석 실패 → 제외
        ["C300", None, "분반없음", 2, "이상한구분", "목1"],  # 8: 분반 자동 부여 + 구분 경고
        [None] * 6,                                    # 9: 빈 행 → 무시
        ["D400", "01", "학년이상", 3, "교선", "금2"],  # 10: 정상
    ]
    path = write_xlsx(tmp_path / "x.xlsx", rows)
    result = load_course_table(path)
    table = _index(result.table)
    assert set(table) == {("A100", "01"), ("C300", "01"), ("D400", "01")}
    assert table[("A100", "01")]["raw_time"] == f"월1,2{config.MULTI_ROW_TIME_JOINER}수3"
    assert table[("A100", "01")]["merged_rows"] == (4,)
    errors = {i.row: i for i in result.issues if i.level == LEVEL_ERROR}
    assert set(errors) == {2, 5, 6, 7}
    assert errors[7].value == "삼"
    warnings = {(i.row, i.field) for i in result.issues if i.level == LEVEL_WARNING}
    assert warnings == {(8, "category"), (8, "section")}
    assert table[("C300", "01")]["category"] is Category.OTHER


def test_auto_section_skips_existing_numbers(tmp_path: Path) -> None:
    rows = [BASIC_HEADER, ["A1", "01", "가", 3, "전필", "월1"], ["A1", None, "가", 3, "전필", "화1"]]
    result = load_course_table(write_xlsx(tmp_path / "x.xlsx", rows))
    assert sorted(result.table["section"]) == ["01", "02"]


def test_best_sheet_is_chosen(tmp_path: Path) -> None:
    wb = Workbook()
    wb.active.title = "안내"
    wb.active.append(["이 파일은 개설강좌 목록입니다"])
    data = wb.create_sheet("목록")
    data.append(BASIC_HEADER)
    data.append(["A1", 1, "가", 3, "전필", "월1"])
    path = tmp_path / "x.xlsx"
    wb.save(path)
    result = load_course_table(path)
    assert result.mapping.sheet_name == "목록"
    assert result.sheet_names == ["안내", "목록"]
    with pytest.raises(MappingError, match="시트"):
        load_course_table(path, sheet="없는시트")
