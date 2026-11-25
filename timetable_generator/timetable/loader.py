"""개설강의 엑셀 로드, 컬럼 자동 매핑, 값 정규화.

처리 순서:
    1. 모든 시트를 헤더 없이 읽는다(``read_workbook``).
    2. 위쪽 ``HEADER_SCAN_ROWS``행에서 동의어가 가장 많이 맞는 행을 헤더로 고른다
       (``detect_header_row``). 시트가 여러 개면 점수가 가장 높은 시트를 쓴다.
    3. 헤더 셀을 표준 필드에 매핑한다(``auto_map_columns``). 사용자 지정 매핑이 우선.
    4. 데이터 행을 정규화한다(``normalize_rows``): 빈 행·반복 헤더 제거, 이어지는 행 병합,
       분반 분리/0 채움, 학점·이수구분·학년·수업방식 정규화. 문제가 있는 행은
       버리지 않고 ``LoadIssue``로 남긴다.

강의시간 문자열 자체의 해석은 parser 모듈(Phase 2)이 맡는다. 여기서는 원문을 보존만 한다.

명령행: ``python -m timetable.loader 파일.xlsx`` → 구조 분석 리포트 출력.
"""

from __future__ import annotations

import argparse
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any, Iterable, Mapping

import pandas as pd

from timetable import config
from timetable.models import Category

Source = str | Path | IO[bytes]

#: 정규화 결과 테이블의 컬럼 순서.
TABLE_COLUMNS: tuple[str, ...] = (
    "row",
    "code",
    "section",
    "name",
    "credits",
    "category",
    "category_raw",
    "dept",
    "grade",
    "grade_raw",
    "professor",
    "raw_time",
    "room",
    "delivery",
    "online_by_delivery",
    "merged_rows",
)

LEVEL_ERROR = "error"  # 행을 결과에서 제외
LEVEL_WARNING = "warning"  # 행은 유지, 값을 기본값으로 대체
LEVEL_INFO = "info"  # 구조 처리 내역(병합, 반복 헤더 제거 등)

METHOD_OVERRIDE = "override"
METHOD_EXACT = "exact"
METHOD_BASE = "base"
METHOD_PARTIAL = "partial"
METHOD_MISSING = "missing"

_SCORE_TO_METHOD = {
    config.MATCH_SCORE_EXACT: METHOD_EXACT,
    config.MATCH_SCORE_BASE: METHOD_BASE,
    config.MATCH_SCORE_PARTIAL: METHOD_PARTIAL,
}

_ZERO_WIDTH = re.compile(r"[​‌‍﻿]")
_BRACKETED = re.compile(r"[\(\[\{<][^\)\]\}>]*[\)\]\}>]")
_HEADER_TRIM = "*:："
_CODE_SECTION = re.compile(config.CODE_SECTION_PATTERN)
_CREDIT = re.compile(config.CREDIT_PATTERN)
_GRADE_RANGE = re.compile(r"^(\d+)[~\-](\d+)$")
_GRADE_SPLIT = re.compile(r"[,·/]")
_GRADE_SUFFIX = "학년"


class MappingError(ValueError):
    """헤더를 찾지 못했거나 필수 필드가 매핑되지 않은 경우."""


# ---------------------------------------------------------------------------
# 결과 자료형
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ColumnMatch:
    """표준 필드 하나의 매핑 결과."""

    field: str
    column: str | None
    method: str
    synonym: str | None = None

    @property
    def is_mapped(self) -> bool:
        """실제 컬럼에 연결되었는지."""
        return self.column is not None


@dataclass
class ColumnMapping:
    """시트 하나의 헤더 위치와 필드 매핑."""

    sheet_name: str
    header_row: int  # 엑셀 행 번호(1부터)
    columns: list[str]
    matches: dict[str, ColumnMatch]

    def column_for(self, field_name: str) -> str | None:
        """표준 필드에 연결된 실제 컬럼명(없으면 None)."""
        match = self.matches.get(field_name)
        return match.column if match else None

    @property
    def missing_required(self) -> list[str]:
        """매핑되지 않은 필수 필드."""
        return [f for f in config.REQUIRED_FIELDS if self.column_for(f) is None]

    @property
    def missing_optional(self) -> list[str]:
        """매핑되지 않은 선택 필드."""
        return [
            f
            for f in config.STANDARD_FIELDS
            if f not in config.REQUIRED_FIELDS and self.column_for(f) is None
        ]

    @property
    def unmapped_columns(self) -> list[str]:
        """어떤 표준 필드에도 쓰이지 않은 실제 컬럼."""
        used = {m.column for m in self.matches.values() if m.column}
        return [c for c in self.columns if c not in used]

    def as_dict(self) -> dict[str, str | None]:
        """{표준필드: 실제컬럼} 사전. UI에서 수정한 뒤 overrides로 다시 넘길 수 있다."""
        return {f: self.column_for(f) for f in config.STANDARD_FIELDS}

    def to_frame(self) -> pd.DataFrame:
        """매핑 결과 표(필드, 표시명, 컬럼, 방식, 근거 동의어)."""
        rows = []
        for f in config.STANDARD_FIELDS:
            m = self.matches[f]
            rows.append(
                {
                    "field": f,
                    "label": config.FIELD_LABELS[f],
                    "required": f in config.REQUIRED_FIELDS,
                    "column": m.column,
                    "method": m.method,
                    "synonym": m.synonym,
                }
            )
        return pd.DataFrame(rows)


@dataclass(frozen=True)
class LoadIssue:
    """정규화 중 발견한 문제. ``row``는 원본 엑셀 행 번호."""

    row: int
    level: str
    field: str
    value: str
    message: str


@dataclass
class LoadResult:
    """``load_course_table``의 반환값."""

    table: pd.DataFrame
    mapping: ColumnMapping
    issues: list[LoadIssue] = field(default_factory=list)
    sheet_names: list[str] = field(default_factory=list)

    def issues_frame(self, levels: Iterable[str] | None = None) -> pd.DataFrame:
        """문제 목록을 표로. ``levels``를 주면 해당 수준만."""
        wanted = set(levels) if levels else None
        rows = [vars(i) for i in self.issues if wanted is None or i.level in wanted]
        return pd.DataFrame(rows, columns=["row", "level", "field", "value", "message"])


# ---------------------------------------------------------------------------
# 셀/헤더 문자열 처리
# ---------------------------------------------------------------------------


def clean_cell(value: Any) -> str:
    """셀 값을 문자열로. 빈 값은 "", 정수형 float는 "3", 연속 공백·줄바꿈은 공백 1개."""
    if value is None:
        return ""
    if isinstance(value, float):
        if pd.isna(value):
            return ""
        if value.is_integer():
            return str(int(value))
    text = _ZERO_WIDTH.sub("", str(value))
    return " ".join(text.split())


def normalize_header(text: Any) -> str:
    """헤더 비교용 정규형: NFKC(전각→반각), 소문자, 공백 제거, 앞뒤 표시문자 제거."""
    s = unicodedata.normalize("NFKC", clean_cell(text)).lower()
    return "".join(s.split()).strip(_HEADER_TRIM)


def base_header(normalized: str) -> str:
    """괄호 안 내용을 지운 헤더. 예: "학점(이론-실습)" → "학점"."""
    return _BRACKETED.sub("", normalized).strip(_HEADER_TRIM)


def _synonym_index(
    synonyms: Mapping[str, tuple[str, ...]],
) -> dict[str, list[tuple[str, int, str]]]:
    """정규화 동의어 → [(필드, 순위, 원래 동의어)]."""
    index: dict[str, list[tuple[str, int, str]]] = {}
    for field_name, words in synonyms.items():
        for rank, word in enumerate(words):
            index.setdefault(normalize_header(word), []).append((field_name, rank, word))
    return index


def _unique_headers(cells: Iterable[Any]) -> list[str]:
    """헤더 셀을 고유한 컬럼명 리스트로. 빈 셀은 "(빈 헤더 N)", 중복은 "_2" 접미사."""
    names: list[str] = []
    seen: Counter[str] = Counter()
    for position, cell in enumerate(cells, start=1):
        name = clean_cell(cell) or f"(빈 헤더 {position})"
        seen[name] += 1
        if seen[name] > 1:
            name = f"{name}_{seen[name]}"
        names.append(name)
    return names


# ---------------------------------------------------------------------------
# 1~3. 읽기, 헤더 탐지, 컬럼 매핑
# ---------------------------------------------------------------------------


def read_workbook(source: Source) -> dict[str, pd.DataFrame]:
    """모든 시트를 헤더 없이(문자/숫자 원형 그대로) 읽는다. 행 인덱스 i = 엑셀 i+1행."""
    if hasattr(source, "seek"):
        source.seek(0)  # type: ignore[union-attr]
    return pd.read_excel(source, sheet_name=None, header=None, dtype=object, engine="openpyxl")


def count_header_matches(
    cells: Iterable[Any], synonyms: Mapping[str, tuple[str, ...]] = config.COLUMN_SYNONYMS
) -> int:
    """한 행에서 동의어와 정확/괄호제거 일치하는 셀 수."""
    index = _synonym_index(synonyms)
    count = 0
    for cell in cells:
        n = normalize_header(cell)
        if n and (n in index or base_header(n) in index):
            count += 1
    return count


def detect_header_row(
    raw: pd.DataFrame,
    synonyms: Mapping[str, tuple[str, ...]] = config.COLUMN_SYNONYMS,
    scan_rows: int = config.HEADER_SCAN_ROWS,
) -> tuple[int, int]:
    """헤더 행의 (0-based 인덱스, 일치 셀 수)를 돌려준다. 동점이면 위쪽 행."""
    best_index, best_count = -1, 0
    for i in range(min(scan_rows, len(raw))):
        count = count_header_matches(raw.iloc[i].tolist(), synonyms)
        if count > best_count:
            best_index, best_count = i, count
    return best_index, best_count


def auto_map_columns(
    headers: list[str],
    synonyms: Mapping[str, tuple[str, ...]] = config.COLUMN_SYNONYMS,
    overrides: Mapping[str, str | None] | None = None,
) -> dict[str, ColumnMatch]:
    """헤더 리스트를 표준 필드에 매핑한다.

    우선순위: 사용자 지정(override) > 정확 일치 > 괄호 제거 후 일치 > 부분 일치.
    같은 점수에서는 긴 동의어, 동의어 목록의 앞쪽, 왼쪽 컬럼 순으로 고른다.
    한 컬럼은 한 필드에만 쓰인다.

    Args:
        headers: 실제 컬럼명 리스트.
        synonyms: 표준필드 → 동의어 튜플.
        overrides: 표준필드 → 실제 컬럼명. 값이 None 또는 ""이면 그 필드를 강제로 비운다.

    Raises:
        MappingError: override가 없는 컬럼명이나 모르는 필드를 가리킬 때.
    """
    overrides = dict(config.COLUMN_MAPPING_OVERRIDES) | dict(overrides or {})
    matches: dict[str, ColumnMatch] = {}
    used_columns: set[str] = set()

    for field_name, column in overrides.items():
        if field_name not in config.STANDARD_FIELDS:
            raise MappingError(f"알 수 없는 표준 필드: {field_name!r}")
        if not column:
            matches[field_name] = ColumnMatch(field_name, None, METHOD_MISSING)
            continue
        if column not in headers:
            raise MappingError(
                f"지정한 컬럼 {column!r}({config.FIELD_LABELS[field_name]})이 헤더에 없습니다. "
                f"헤더: {headers}"
            )
        matches[field_name] = ColumnMatch(field_name, column, METHOD_OVERRIDE)
        used_columns.add(column)

    candidates: list[tuple[int, int, int, int, str, str, str]] = []
    for col_pos, header in enumerate(headers):
        n = normalize_header(header)
        b = base_header(n)
        for field_name, words in synonyms.items():
            for rank, word in enumerate(words):
                w = normalize_header(word)
                if n == w:
                    score = config.MATCH_SCORE_EXACT
                elif b and b == w:
                    score = config.MATCH_SCORE_BASE
                elif len(w) >= config.PARTIAL_MATCH_MIN_LEN and w in n:
                    score = config.MATCH_SCORE_PARTIAL
                else:
                    continue
                candidates.append((score, len(w), -rank, -col_pos, field_name, header, word))

    for score, _, _, _, field_name, header, word in sorted(candidates, reverse=True):
        if field_name in matches or header in used_columns:
            continue
        matches[field_name] = ColumnMatch(field_name, header, _SCORE_TO_METHOD[score], word)
        used_columns.add(header)

    for field_name in config.STANDARD_FIELDS:
        matches.setdefault(field_name, ColumnMatch(field_name, None, METHOD_MISSING))
    return matches


def choose_sheet(
    sheets: Mapping[str, pd.DataFrame], sheet: str | None = None
) -> tuple[str, int, int]:
    """사용할 시트와 헤더 행을 고른다. 반환: (시트명, 헤더 0-based 인덱스, 일치 수).

    Raises:
        MappingError: 지정 시트가 없거나, 어느 시트에서도 헤더를 찾지 못한 경우.
    """
    if sheet is not None:
        if sheet not in sheets:
            raise MappingError(f"시트 {sheet!r}가 없습니다. 시트 목록: {list(sheets)}")
        candidates = {sheet: sheets[sheet]}
    else:
        candidates = dict(sheets)

    best: tuple[str, int, int] | None = None
    for name, raw in candidates.items():
        index, count = detect_header_row(raw)
        if best is None or count > best[2]:
            best = (name, index, count)
    if best is None or best[2] < config.HEADER_MIN_MATCHES:
        found = best[2] if best else 0
        raise MappingError(
            f"헤더 행을 찾지 못했습니다(위 {config.HEADER_SCAN_ROWS}행에서 동의어 일치 "
            f"최대 {found}개 < 기준 {config.HEADER_MIN_MATCHES}개). "
            "config.COLUMN_SYNONYMS에 실제 헤더명을 추가하세요."
        )
    return best


def build_mapping(
    raw: pd.DataFrame,
    sheet_name: str,
    header_index: int,
    overrides: Mapping[str, str | None] | None = None,
) -> ColumnMapping:
    """헤더 행으로 ``ColumnMapping``을 만든다."""
    headers = _unique_headers(raw.iloc[header_index].tolist())
    matches = auto_map_columns(headers, overrides=overrides)
    return ColumnMapping(sheet_name, header_index + 1, headers, matches)


# ---------------------------------------------------------------------------
# 4. 값 정규화
# ---------------------------------------------------------------------------


def parse_credits(text: str) -> float | None:
    """학점 문자열에서 첫 숫자를 읽는다. 숫자가 없으면 None."""
    match = _CREDIT.search(text)
    return float(match.group(1)) if match else None


def normalize_category(raw: str) -> tuple[Category, bool]:
    """이수구분 원문을 정규화한다. 반환: (Category, 규칙에 걸렸는지)."""
    key = "".join(raw.split())
    if not key:
        return Category(config.CATEGORY_DEFAULT), False
    if key in config.CATEGORY_EXACT:
        return Category(config.CATEGORY_EXACT[key]), True
    for token, value in config.CATEGORY_CONTAINS_RULES:
        if token in key:
            return Category(value), True
    for prefix, value in config.CATEGORY_PREFIX_RULES:
        if key.startswith(prefix):
            return Category(value), True
    return Category(config.CATEGORY_DEFAULT), False


def parse_grade(raw: str) -> frozenset[int] | None:
    """대상학년 문자열을 학년 집합으로. 빈 집합 = 전체 학년, None = 해석 실패.

    예: "2" → {2}, "1,2" → {1,2}, "1~3" → {1,2,3}, "2학년" → {2}, "전체"/"" → {}.
    """
    compact = "".join(raw.split())
    key = compact.replace(_GRADE_SUFFIX, "")
    if not key or compact.lower() in config.GRADE_ALL_TOKENS or key.lower() in config.GRADE_ALL_TOKENS:
        return frozenset()
    grades: set[int] = set()
    for token in filter(None, _GRADE_SPLIT.split(key)):
        ranged = _GRADE_RANGE.match(token)
        if ranged:
            low, high = int(ranged.group(1)), int(ranged.group(2))
            if low > high:
                return None
            grades.update(range(low, high + 1))
        elif token.isdigit():
            grades.add(int(token))
        else:
            return None
    if not grades or min(grades) < config.MIN_GRADE or max(grades) > config.MAX_GRADE:
        return None
    return frozenset(grades)


def normalize_section(raw: str) -> str:
    """분반 정규화: 숫자면 SECTION_PAD_WIDTH 자리로 0 채움, 아니면 대문자 원문."""
    text = raw.strip()
    if text.isdigit():
        return text.zfill(config.SECTION_PAD_WIDTH)
    return text.upper()


def split_code_section(raw_code: str) -> tuple[str, str | None]:
    """"CSE2010-01" 같은 코드에서 (코드, 분반)을 분리. 패턴이 아니면 (원문, None)."""
    match = _CODE_SECTION.match(raw_code)
    if not match:
        return raw_code, None
    return match.group("code"), normalize_section(match.group("section"))


def is_online_delivery(raw: str) -> bool:
    """수업방식 문자열이 원격 강의를 뜻하는지(혼합형은 False)."""
    text = raw.lower()
    if any(k in text for k in config.BLENDED_DELIVERY_KEYWORDS):
        return False
    return any(k in text for k in config.ONLINE_DELIVERY_KEYWORDS)


def _is_repeated_header(values: Mapping[str, str], mapping: ColumnMapping) -> bool:
    """페이지마다 반복되는 헤더 행인지(셀 값이 자기 컬럼명과 같은 셀이 충분히 많음)."""
    same = sum(
        1
        for col in mapping.columns
        if values.get(col) and normalize_header(values[col]) == normalize_header(col)
    )
    return same >= config.HEADER_MIN_MATCHES


def normalize_rows(
    raw: pd.DataFrame, mapping: ColumnMapping
) -> tuple[pd.DataFrame, list[LoadIssue]]:
    """헤더 아래 데이터 행을 표준 테이블로 정규화한다.

    Returns:
        (TABLE_COLUMNS 순서의 DataFrame, LoadIssue 리스트)
    """
    issues: list[LoadIssue] = []
    records: list[dict[str, Any]] = []
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    pending_section: list[dict[str, Any]] = []
    columns = mapping.columns
    has_section_col = mapping.column_for("section") is not None

    def get(values: Mapping[str, str], field_name: str) -> str:
        column = mapping.column_for(field_name)
        return values.get(column, "") if column else ""

    def issue(row: int, level: str, field_name: str, value: str, message: str) -> None:
        issues.append(LoadIssue(row, level, field_name, value, message))

    def append_time(target: dict[str, Any], time_text: str, room: str, row: int) -> None:
        if time_text:
            target["raw_time"] = (
                f"{target['raw_time']}{config.MULTI_ROW_TIME_JOINER}{time_text}"
                if target["raw_time"]
                else time_text
            )
        if room and room not in target["room"].split(config.MULTI_ROW_ROOM_JOINER):
            target["room"] = (
                f"{target['room']}{config.MULTI_ROW_ROOM_JOINER}{room}" if target["room"] else room
            )
        target["merged_rows"] = (*target["merged_rows"], row)

    for raw_index in range(mapping.header_row, len(raw)):
        excel_row = raw_index + 1
        cells = raw.iloc[raw_index].tolist()
        values = {col: clean_cell(cells[i]) if i < len(cells) else "" for i, col in enumerate(columns)}
        if not any(values.values()):
            continue
        if _is_repeated_header(values, mapping):
            issue(excel_row, LEVEL_INFO, "-", "", "반복 헤더 행 제거")
            continue

        code_text, name = get(values, "code"), get(values, "name")
        time_text, room = get(values, "time"), get(values, "room")

        # 이어지는 행: 코드·과목명이 비고 강의시간/강의실만 있는 행 → 직전 강좌에 붙인다.
        if not code_text and not name and (time_text or room):
            if records:
                append_time(records[-1], time_text, room, excel_row)
                issue(
                    excel_row, LEVEL_INFO, "time", time_text,
                    f"이어지는 행 → {records[-1]['row']}행 강좌에 강의시간 병합",
                )
            else:
                issue(excel_row, LEVEL_ERROR, "code", "", "과목코드 없음(앞에 붙일 강좌도 없음)")
            continue
        if not code_text:
            issue(excel_row, LEVEL_ERROR, "code", name, "과목코드 없음 → 제외")
            continue
        if not name:
            issue(excel_row, LEVEL_ERROR, "name", code_text, "과목명 없음 → 제외")
            continue

        credits_text = get(values, "credits")
        credits = parse_credits(credits_text)
        if credits is None:
            issue(excel_row, LEVEL_ERROR, "credits", credits_text, "학점을 읽을 수 없음 → 제외")
            continue

        code = code_text.upper()
        section: str | None
        if has_section_col:
            section_text = get(values, "section")
            section = normalize_section(section_text) if section_text else None
        else:
            code, section = split_code_section(code)

        category_raw = get(values, "category")
        category, known = normalize_category(category_raw)
        if not known:
            issue(
                excel_row, LEVEL_WARNING, "category", category_raw,
                f"이수구분을 분류하지 못함 → {category.value}",
            )

        grade_raw = get(values, "grade")
        grade = parse_grade(grade_raw)
        if grade is None:
            issue(excel_row, LEVEL_WARNING, "grade", grade_raw, "대상학년 해석 실패 → 전체 학년으로 처리")
            grade = frozenset()

        delivery = get(values, "delivery")
        record: dict[str, Any] = {
            "row": excel_row,
            "code": code,
            "section": section,
            "name": name,
            "credits": credits,
            "category": category,
            "category_raw": category_raw,
            "dept": get(values, "dept"),
            "grade": grade,
            "grade_raw": grade_raw,
            "professor": get(values, "professor"),
            "raw_time": time_text,
            "room": room,
            "delivery": delivery,
            "online_by_delivery": is_online_delivery(delivery),
            "merged_rows": (),
        }

        if section is None:
            pending_section.append(record)
            records.append(record)
            continue

        key = (code, section)
        if key in by_key:
            first = by_key[key]
            if first["name"] == name:
                append_time(first, time_text, room, excel_row)
                issue(
                    excel_row, LEVEL_INFO, "section", f"{code}-{section}",
                    f"같은 과목코드·분반 → {first['row']}행 강좌에 강의시간 병합",
                )
            else:
                issue(
                    excel_row, LEVEL_ERROR, "section", f"{code}-{section}",
                    f"{first['row']}행과 과목코드·분반이 같은데 과목명이 다름 → 제외",
                )
            continue
        by_key[key] = record
        records.append(record)

    # 분반을 알 수 없는 행: 그 과목코드에서 아직 안 쓴 번호를 차례로 부여한다.
    used: dict[str, set[str]] = {}
    for code, section in by_key:
        used.setdefault(code, set()).add(section)
    for record in pending_section:
        taken = used.setdefault(record["code"], set())
        number = 1
        while normalize_section(str(number)) in taken:
            number += 1
        record["section"] = normalize_section(str(number))
        taken.add(record["section"])
        issue(
            record["row"], LEVEL_WARNING, "section", "",
            f"분반 정보 없음 → {record['section']} 자동 부여",
        )

    table = pd.DataFrame(records, columns=list(TABLE_COLUMNS))
    return table, issues


# ---------------------------------------------------------------------------
# 진입점
# ---------------------------------------------------------------------------


def load_course_table(
    source: Source,
    overrides: Mapping[str, str | None] | None = None,
    sheet: str | None = None,
) -> LoadResult:
    """엑셀을 읽어 정규화된 강좌 테이블을 돌려준다.

    Args:
        source: 파일 경로 또는 바이너리 파일 객체(Streamlit 업로드 파일 포함).
        overrides: 표준필드 → 실제 컬럼명 수동 매핑.
        sheet: 시트명. None이면 헤더 점수가 가장 높은 시트.

    Raises:
        MappingError: 헤더를 못 찾았거나 필수 필드가 매핑되지 않았을 때.
    """
    sheets = read_workbook(source)
    sheet_name, header_index, _ = choose_sheet(sheets, sheet)
    raw = sheets[sheet_name]
    mapping = build_mapping(raw, sheet_name, header_index, overrides)
    if mapping.missing_required:
        labels = ", ".join(f"{config.FIELD_LABELS[f]}({f})" for f in mapping.missing_required)
        raise MappingError(
            f"필수 필드를 찾지 못했습니다: {labels}. 헤더: {mapping.columns}. "
            "overrides로 직접 지정하거나 config.COLUMN_SYNONYMS에 동의어를 추가하세요."
        )
    table, issues = normalize_rows(raw, mapping)
    return LoadResult(table, mapping, issues, list(sheets))


# ---------------------------------------------------------------------------
# 구조 분석 리포트
# ---------------------------------------------------------------------------

_SHAPE_TOKEN = re.compile(
    rf"(?P<day>[{''.join(config.DAYS)}](?![가-힣]))|(?P<hangul>[가-힣]+)|(?P<num>\d+)|(?P<alpha>[A-Za-z]+)"
)
_SHAPE_SYMBOL = {"day": "D", "hangul": "가", "num": "9", "alpha": "a"}


def time_shape(text: str) -> str:
    """강의시간 문자열의 형태 서명. 예: "월1,2(공학관301) 수3" → "D9,9(가9) D9"."""
    return _SHAPE_TOKEN.sub(lambda m: _SHAPE_SYMBOL[m.lastgroup or "num"], text)


@dataclass
class StructureReport:
    """엑셀 구조 분석 결과(실제 포털 파일을 받았을 때 매핑·파서 설계 점검용)."""

    result: LoadResult
    header_scores: dict[str, int]
    fill_rates: dict[str, float]
    samples: dict[str, list[str]]
    category_counts: Counter[tuple[str, str]]
    grade_counts: Counter[str]
    delivery_counts: Counter[str]
    time_shapes: Counter[str]

    def to_text(self, top: int = 15) -> str:
        """사람이 읽는 텍스트 리포트."""
        r, m = self.result, self.result.mapping
        lines = [
            f"[시트] {r.sheet_names} → 사용: {m.sheet_name!r}, 헤더 행: {m.header_row}행",
            f"       시트별 헤더 일치 수: {self.header_scores}",
            "",
            "[컬럼 매핑]",
        ]
        for f in config.STANDARD_FIELDS:
            match = m.matches[f]
            req = "*" if f in config.REQUIRED_FIELDS else " "
            via = f" (동의어 {match.synonym!r})" if match.synonym else ""
            lines.append(
                f"  {req}{config.FIELD_LABELS[f]:<6} ← {str(match.column):<16} [{match.method}]{via}"
            )
        lines.append(f"  매핑 안 된 컬럼: {m.unmapped_columns}")
        lines += ["", "[컬럼별 채움률 / 샘플]"]
        for col in m.columns:
            lines.append(f"  {col:<16} {self.fill_rates[col]:6.1%}  {self.samples[col]}")
        lines += ["", f"[정규화] 강좌 {len(r.table)}개, 그룹(과목코드) {r.table['code'].nunique()}개"]
        level_counts = Counter(i.level for i in r.issues)
        lines.append(f"  이슈: {dict(level_counts)}")
        lines += ["", "[이수구분 원문 → 정규화]"]
        for (raw_cat, norm), n in self.category_counts.most_common():
            lines.append(f"  {raw_cat or '(빈 값)':<8} → {norm:<8} {n}")
        lines += ["", f"[대상학년 원문] {dict(self.grade_counts.most_common())}"]
        lines += [f"[수업방식 원문] {dict(self.delivery_counts.most_common())}"]
        lines += ["", f"[강의시간 형태 상위 {top}] (D=요일, 9=숫자, 가=한글, a=영문)"]
        for shape, n in self.time_shapes.most_common(top):
            lines.append(f"  {n:4d}  {shape or '(빈 값)'}")
        return "\n".join(lines)


def analyze_structure(
    source: Source,
    overrides: Mapping[str, str | None] | None = None,
    sheet: str | None = None,
    sample_size: int = 3,
) -> StructureReport:
    """엑셀 구조를 분석한다: 헤더 위치, 매핑, 채움률, 값 분포, 강의시간 형태."""
    sheets = read_workbook(source)
    header_scores = {name: detect_header_row(raw)[1] for name, raw in sheets.items()}
    result = load_course_table(source, overrides, sheet)
    m = result.mapping
    raw = sheets[m.sheet_name]
    body = raw.iloc[m.header_row:].reset_index(drop=True)
    body.columns = list(m.columns) + [f"(초과 {i})" for i in range(len(body.columns) - len(m.columns))]

    fill_rates: dict[str, float] = {}
    samples: dict[str, list[str]] = {}
    for col in m.columns:
        texts = [clean_cell(v) for v in body[col].tolist()]
        non_empty = [t for t in texts if t]
        fill_rates[col] = len(non_empty) / len(texts) if texts else 0.0
        samples[col] = list(dict.fromkeys(non_empty))[:sample_size]

    table = result.table
    return StructureReport(
        result=result,
        header_scores=header_scores,
        fill_rates=fill_rates,
        samples=samples,
        category_counts=Counter(
            zip(table["category_raw"], (c.value for c in table["category"]))
        ),
        grade_counts=Counter(table["grade_raw"]),
        delivery_counts=Counter(table["delivery"]),
        time_shapes=Counter(time_shape(t) for t in table["raw_time"]),
    )


def main(argv: list[str] | None = None) -> None:
    """명령행 진입점: 구조 분석 리포트를 출력한다."""
    parser = argparse.ArgumentParser(description="개설강의 엑셀 구조 분석")
    parser.add_argument("path", type=Path)
    parser.add_argument("--sheet", default=None)
    parser.add_argument("--issues", action="store_true", help="이슈 전체 출력")
    args = parser.parse_args(argv)
    report = analyze_structure(args.path, sheet=args.sheet)
    print(report.to_text())
    if args.issues:
        print()
        print(report.result.issues_frame().to_string(index=False))


if __name__ == "__main__":
    main()
