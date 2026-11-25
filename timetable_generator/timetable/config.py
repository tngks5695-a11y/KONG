"""시간표 생성기 전역 설정.

컬럼 매핑, 교시 시각표, 정규화 규칙, mock 데이터 파라미터 등 코드 곳곳에서 쓰는
상수를 이 모듈에 모은다. 다른 모듈은 숫자/문자열 리터럴 대신 여기 값을 참조한다.

[가정] 표시가 붙은 항목은 실제 포털 엑셀을 받기 전까지의 가정값이다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final, Mapping

# ---------------------------------------------------------------------------
# 1. 요일 / 교시
# ---------------------------------------------------------------------------

#: 요일 순서. 인덱스가 곧 day_index 이며 time_mask 비트 배치에 쓰인다.
DAYS: Final[tuple[str, ...]] = ("월", "화", "수", "목", "금", "토", "일")

#: 주간 교시 수 [가정] 1~9교시 = 주간, 10교시 이상 = 야간.
DAY_PERIOD_COUNT: Final[int] = 9

#: 야간 교시 문자 표기 → 교시 번호 [가정] A=10교시(18:00)부터 연속.
NIGHT_PERIOD_LABELS: Final[Mapping[str, int]] = MappingProxyType(
    {"A": 10, "B": 11, "C": 12, "D": 13}
)

#: 지원하는 최대 교시. time_mask 비트 배치(day_index * MAX_PERIOD + period - 1)의 기준.
MAX_PERIOD: Final[int] = 13

MINUTES_PER_HOUR: Final[int] = 60


def hhmm_to_minutes(text: str) -> int:
    """"HH:MM" 문자열을 자정 기준 분(minute)으로 바꾼다."""
    hours, minutes = text.split(":")
    return int(hours) * MINUTES_PER_HOUR + int(minutes)


def minutes_to_hhmm(total: int) -> str:
    """자정 기준 분(minute)을 "HH:MM" 문자열로 바꾼다."""
    return f"{total // MINUTES_PER_HOUR:02d}:{total % MINUTES_PER_HOUR:02d}"


@dataclass(frozen=True)
class PeriodSchedule:
    """교시별 시작/종료 시각표.

    [가정] 기본값은 1교시 09:00 시작, 50분 수업 + 10분 휴식(교시 간격 60분).
    학교마다 다르면 ``explicit_starts``에 교시별 시작 시각을 직접 넣는다.
    """

    first_period_start: str = "09:00"
    class_minutes: int = 50
    break_minutes: int = 10
    max_period: int = MAX_PERIOD
    explicit_starts: Mapping[int, str] = field(default_factory=dict)

    def start_minutes(self, period: int) -> int:
        """``period`` 교시의 시작 시각(분)."""
        if period in self.explicit_starts:
            return hhmm_to_minutes(self.explicit_starts[period])
        step = self.class_minutes + self.break_minutes
        return hhmm_to_minutes(self.first_period_start) + (period - 1) * step

    def end_minutes(self, period: int) -> int:
        """``period`` 교시의 수업 종료 시각(분)."""
        return self.start_minutes(period) + self.class_minutes

    def periods(self) -> range:
        """지원하는 교시 번호 범위(1..max_period)."""
        return range(1, self.max_period + 1)

    def label(self, period: int) -> str:
        """교시 표시용 문자열. 예: ``"1교시 09:00-09:50"``."""
        start = minutes_to_hhmm(self.start_minutes(period))
        end = minutes_to_hhmm(self.end_minutes(period))
        return f"{period}교시 {start}-{end}"


DEFAULT_PERIOD_SCHEDULE: Final[PeriodSchedule] = PeriodSchedule()

# ---------------------------------------------------------------------------
# 2. 표준 필드와 컬럼 매핑
# ---------------------------------------------------------------------------

#: 표준 필드 키(코드 내부 이름) 순서.
STANDARD_FIELDS: Final[tuple[str, ...]] = (
    "code",
    "section",
    "name",
    "credits",
    "category",
    "dept",
    "grade",
    "professor",
    "time",
    "room",
    "delivery",
)

#: 표준 필드의 한글 표시명.
FIELD_LABELS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "code": "과목코드",
        "section": "분반",
        "name": "과목명",
        "credits": "학점",
        "category": "이수구분",
        "dept": "개설학과",
        "grade": "대상학년",
        "professor": "교수",
        "time": "강의시간",
        "room": "강의실",
        "delivery": "수업방식",
    }
)

#: 반드시 매핑되어야 하는 필드. 나머지는 없으면 기본값으로 채운다.
REQUIRED_FIELDS: Final[tuple[str, ...]] = ("code", "name", "credits", "time")

#: 표준 필드별 동의어. 앞에 있을수록 우선한다(동점일 때 tie-break).
#: 비교 전 normalize_header()로 공백 제거, 소문자화, 전각→반각(NFKC) 처리한다.
COLUMN_SYNONYMS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "code": (
            "과목코드", "학수번호", "교과목번호", "교과목코드", "과목번호",
            "학정번호", "학수코드", "강좌코드", "coursecode", "course code", "code",
        ),
        "section": (
            "분반", "분반번호", "분반코드", "강좌분반", "반", "section", "sec",
        ),
        "name": (
            "과목명", "교과목명", "강좌명", "강의명", "교과목", "과목",
            "coursename", "course name", "title", "name",
        ),
        "credits": (
            "학점", "이수학점", "학점수", "학점-이론-실습", "학-이-실", "학-강-실",
            "credit", "credits",
        ),
        "category": (
            "이수구분", "이수구분명", "과목구분", "교과구분", "이수", "구분",
            "category", "type",
        ),
        "dept": (
            "개설학과", "개설전공", "개설학부", "주관학과", "개설학과전공",
            "학과", "전공", "소속", "department", "dept",
        ),
        "grade": (
            "대상학년", "학년", "수강학년", "개설학년", "권장학년", "grade", "year",
        ),
        "professor": (
            "교수", "교수명", "담당교수", "담당교원", "강의교수", "교강사",
            "교원명", "강사", "professor", "instructor",
        ),
        "time": (
            "강의시간", "수업시간", "요일및시간", "요일/시간", "요일및교시",
            "요일/교시", "강의시간/강의실", "강의시간표", "시간표", "시간",
            "time", "schedule",
        ),
        "room": (
            "강의실", "강의장소", "장소", "호실", "강의실호실", "room", "classroom",
        ),
        "delivery": (
            "수업방식", "강의방식", "수업형태", "강의형태", "수업유형", "강의유형",
            "수업방법", "원격여부", "delivery", "mode",
        ),
    }
)

#: 사용자가 직접 지정하는 매핑(표준필드 → 실제 컬럼명). 자동 탐지보다 우선한다.
#: 예: {"time": "강의시간(강의실)"}
COLUMN_MAPPING_OVERRIDES: Final[Mapping[str, str]] = MappingProxyType({})

#: 매칭 방식별 점수. 높을수록 우선.
MATCH_SCORE_OVERRIDE: Final[int] = 4
MATCH_SCORE_EXACT: Final[int] = 3
MATCH_SCORE_BASE: Final[int] = 2  # 괄호 안 내용을 지운 헤더가 동의어와 일치
MATCH_SCORE_PARTIAL: Final[int] = 1  # 헤더가 동의어를 포함

#: 부분 일치(포함) 판정에 쓸 동의어의 최소 길이. "반", "구분" 같은 짧은 말의 오탐 방지.
PARTIAL_MATCH_MIN_LEN: Final[int] = 3

#: 헤더 행을 찾기 위해 위에서부터 훑을 행 수(제목·조회조건 행이 위에 있을 수 있음).
HEADER_SCAN_ROWS: Final[int] = 15

#: 헤더 행으로 인정할 최소 동의어 일치 셀 수.
HEADER_MIN_MATCHES: Final[int] = 3

# ---------------------------------------------------------------------------
# 3. 값 정규화 규칙
# ---------------------------------------------------------------------------

#: 분반 컬럼이 없을 때 과목코드 셀에서 코드와 분반을 분리하는 패턴. 예: "CSE2010-01".
#: 코드 부분에 숫자가 하나 이상 있어야 한다("GED-101" 같은 코드를 잘못 쪼개지 않도록).
CODE_SECTION_PATTERN: Final[str] = (
    r"^(?P<code>[A-Za-z0-9]*\d[A-Za-z0-9]*)[-_ .](?P<section>\d{1,3})$"
)

#: 숫자 분반을 이 자릿수로 0 채움. 1 → "01". [가정]
SECTION_PAD_WIDTH: Final[int] = 2

#: 학점 셀에서 첫 숫자를 학점으로 읽는다. "3", "3.0", "3-3-0", "3(3)", "3학점" 모두 3.
CREDIT_PATTERN: Final[str] = r"(\d+(?:\.\d+)?)"

#: 대상학년이 '전체'임을 뜻하는 표기. 빈 값도 전체로 취급한다.
GRADE_ALL_TOKENS: Final[frozenset[str]] = frozenset(
    {"전체", "전학년", "공통", "전체학년", "all", "0", "-"}
)

#: 유효 학년 범위(포함). 5·6학년은 건축·약학 등 6년제 고려.
MIN_GRADE: Final[int] = 1
MAX_GRADE: Final[int] = 6

#: 이수구분 정규화 값(models.Category의 값과 동일한 문자열).
CATEGORY_MAJOR: Final[str] = "MAJOR"
CATEGORY_GENERAL: Final[str] = "GENERAL"
CATEGORY_OTHER: Final[str] = "OTHER"

#: 이수구분 원문(공백 제거) → 정규화 값. 정확히 일치하는 표기를 먼저 본다.
CATEGORY_EXACT: Final[Mapping[str, str]] = MappingProxyType(
    {
        # 전공
        "전필": CATEGORY_MAJOR, "전선": CATEGORY_MAJOR, "전기": CATEGORY_MAJOR,
        "전심": CATEGORY_MAJOR, "전공": CATEGORY_MAJOR, "전공필수": CATEGORY_MAJOR,
        "전공선택": CATEGORY_MAJOR, "전공기초": CATEGORY_MAJOR, "전공심화": CATEGORY_MAJOR,
        "전공핵심": CATEGORY_MAJOR, "복전": CATEGORY_MAJOR,
        # 교양
        "교필": CATEGORY_GENERAL, "교선": CATEGORY_GENERAL, "교양": CATEGORY_GENERAL,
        "교양필수": CATEGORY_GENERAL, "교양선택": CATEGORY_GENERAL,
        "기교": CATEGORY_GENERAL, "기초교양": CATEGORY_GENERAL,
        "핵교": CATEGORY_GENERAL, "핵심교양": CATEGORY_GENERAL,
        "균교": CATEGORY_GENERAL, "균형교양": CATEGORY_GENERAL,
        "일교": CATEGORY_GENERAL, "일반교양": CATEGORY_GENERAL,
        "공교": CATEGORY_GENERAL, "공통교양": CATEGORY_GENERAL,
        # 전공도 교양도 아닌 것 [가정]
        "일선": CATEGORY_OTHER, "일반선택": CATEGORY_OTHER,
        "자선": CATEGORY_OTHER, "자유선택": CATEGORY_OTHER,
        "교직": CATEGORY_OTHER, "교직이론": CATEGORY_OTHER,
    }
)

#: 정확 일치가 없을 때 앞에서부터 적용하는 (포함어, 정규화 값) 규칙.
CATEGORY_CONTAINS_RULES: Final[tuple[tuple[str, str], ...]] = (
    ("교직", CATEGORY_OTHER),
    ("교양", CATEGORY_GENERAL),
    ("전공", CATEGORY_MAJOR),
)

#: 포함 규칙도 없을 때 적용하는 (접두어, 정규화 값) 규칙. 예: "전탐" → MAJOR.
CATEGORY_PREFIX_RULES: Final[tuple[tuple[str, str], ...]] = (
    ("전", CATEGORY_MAJOR),
    ("교", CATEGORY_GENERAL),
)

#: 이수구분 컬럼이 없거나 값이 비었을 때의 정규화 값.
CATEGORY_DEFAULT: Final[str] = CATEGORY_OTHER

#: 수업방식 값에 이 단어가 있으면 원격 강의로 본다(소문자 비교).
ONLINE_DELIVERY_KEYWORDS: Final[tuple[str, ...]] = (
    "원격", "온라인", "비대면", "사이버", "이러닝", "e-러닝", "online", "remote",
)

#: 원격 키워드가 있어도 대면 시간이 있는 혼합형 표기(원격으로 보지 않음).
BLENDED_DELIVERY_KEYWORDS: Final[tuple[str, ...]] = ("혼합", "블렌디드", "blended", "hybrid")

#: 한 강좌가 여러 행에 나뉘어 있을 때 강의시간·강의실을 합치는 구분자.
MULTI_ROW_TIME_JOINER: Final[str] = " / "
MULTI_ROW_ROOM_JOINER: Final[str] = ", "

# ---------------------------------------------------------------------------
# 4. mock 데이터
# ---------------------------------------------------------------------------

MOCK_SEED: Final[int] = 20260301
MOCK_SMALL_SIZE: Final[int] = 50
MOCK_LARGE_SIZE: Final[int] = 200
MOCK_SMALL_FILENAME: Final[str] = "mock_courses_50.xlsx"
MOCK_LARGE_FILENAME: Final[str] = "mock_courses_200.xlsx"

#: 시간 미정/원격 강좌 비율, 의도적으로 깨진 강의시간 비율, 야간 분반 비율.
MOCK_ONLINE_RATIO: Final[float] = 0.07
MOCK_MALFORMED_RATIO: Final[float] = 0.03
MOCK_NIGHT_RATIO: Final[float] = 0.05
MOCK_SATURDAY_RATIO: Final[float] = 0.02
#: 그룹당 분반 수 후보와 가중치.
MOCK_SECTION_COUNTS: Final[tuple[int, ...]] = (1, 2, 3, 4)
MOCK_SECTION_WEIGHTS: Final[tuple[float, ...]] = (0.40, 0.35, 0.18, 0.07)
#: 대형 파일에서 반복 헤더 행(페이지 구분)을 넣을 데이터 행 간격.
MOCK_REPEAT_HEADER_EVERY: Final[int] = 100

# ---------------------------------------------------------------------------
# 5. 이후 Phase 기본값 (요구사항에서 정해진 값)
# ---------------------------------------------------------------------------

DEFAULT_TOP_K: Final[int] = 50
