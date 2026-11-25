"""개발·테스트용 mock 개설강의 엑셀 생성기.

실제 포털 파일이 없을 때 쓰는 가상 데이터다. 일부러 포털마다 다른 형식을 섞는다.

- 소형(50강좌, "A형"): 위에 제목·조회조건 행, 헤더는 표준에 가까운 이름, 분반은 숫자 셀,
  한 강좌의 시간이 두 행에 나뉜 '이어지는 행' 포함.
- 대형(200강좌, "B형"): 제목 행 없음, 헤더 이름이 다름(강좌명/구분/주관학과/요일/시간 등),
  과목코드와 분반이 "CSE2010-01"처럼 한 셀, 학점이 "3-3-0" 형식, 반복 헤더 행 포함.

강의시간 문자열은 같은 시간을 여러 표기로 렌더링한다:
"월1,2,3 수4" / "월1-3" / "월(1,2)화(3)" / "월1,2(공학관301)" / "월 09:00~10:50" /
"화3,4/목3,4" / "화3,4, 목3,4" / 야간 "목A,B" / 원격·미정·빈 값 / 일부러 깨진 문자열.

각 분반의 정답 슬롯(``MockSection.expected_slots``)을 함께 돌려주므로 Phase 2 파서 검증에 쓴다.

명령행: ``python -m timetable.mock_data --out data``
"""

from __future__ import annotations

import argparse
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from timetable import config
from timetable.config import DEFAULT_PERIOD_SCHEDULE, minutes_to_hhmm
from timetable.models import Slot

# ---------------------------------------------------------------------------
# 가상 교과목 카탈로그: (과목명, 학점, 대상학년 원문, 이수구분 원문)
# ---------------------------------------------------------------------------

CourseSpec = tuple[str, float, str, str]

DEPARTMENTS: dict[str, tuple[str, list[CourseSpec]]] = {
    "CSE": ("컴퓨터공학과", [
        ("프로그래밍기초", 3, "1", "전기"), ("이산수학", 3, "1", "전기"),
        ("자료구조", 3, "2", "전필"), ("컴퓨터구조", 3, "2", "전필"),
        ("객체지향프로그래밍", 3, "2", "전선"), ("웹프로그래밍", 3, "2", "전선"),
        ("오픈소스SW실습", 2, "2", "전선"), ("리눅스시스템실습", 1, "2", "전선"),
        ("알고리즘", 3, "3", "전필"), ("운영체제", 3, "3", "전필"),
        ("데이터베이스", 3, "3", "전선"), ("컴퓨터네트워크", 3, "3", "전선"),
        ("소프트웨어공학", 3, "3", "전선"), ("인공지능", 3, "3,4", "전심"),
        ("컴파일러", 3, "4", "전선"), ("캡스톤디자인", 3, "4", "전필"),
    ]),
    "EEE": ("전자공학과", [
        ("회로이론", 3, "1", "전기"), ("디지털논리회로", 3, "2", "전필"),
        ("전자기학", 3, "2", "전필"), ("신호및시스템", 3, "2", "전선"),
        ("전자회로", 3, "3", "전필"), ("전자회로실험", 2, "3", "전선"),
        ("제어공학", 3, "3", "전선"), ("반도체공학", 3, "3", "전선"),
        ("통신이론", 3, "4", "전선"), ("마이크로프로세서", 3, "3", "전선"),
    ]),
    "MEC": ("기계공학과", [
        ("정역학", 3, "1", "전기"), ("동역학", 3, "2", "전필"),
        ("열역학", 3, "2", "전필"), ("재료역학", 3, "2", "전필"),
        ("유체역학", 3, "3", "전필"), ("CAD실습", 2, "2", "전선"),
        ("기계설계", 3, "3", "전선"), ("열전달", 3, "3", "전선"),
        ("기계공작법", 3, "3", "전선"), ("진동학", 3, "4", "전선"),
    ]),
    "BUS": ("경영학과", [
        ("경영학원론", 3, "1", "전기"), ("회계원리", 3, "1", "전기"),
        ("마케팅원론", 3, "2", "전필"), ("재무관리", 3, "2", "전필"),
        ("조직행동론", 3, "2", "전선"), ("경영통계", 3, "2", "전선"),
        ("인사관리", 3, "3", "전선"), ("생산운영관리", 3, "3", "전선"),
        ("경영정보시스템", 3, "3", "전선"), ("국제경영", 3, "4", "전선"),
    ]),
    "GED": ("교양교육원", [
        ("대학글쓰기", 2, "1", "교필"), ("영어회화1", 2, "1", "교필"),
        ("영어회화2", 2, "1,2", "교필"), ("미적분학1", 3, "1", "기교"),
        ("일반물리학1", 3, "1", "기교"), ("일반화학", 3, "1", "기교"),
        ("심리학의이해", 3, "전체", "교선"), ("철학과비판적사고", 3, "전체", "교선"),
        ("세계사의흐름", 3, "", "교선"), ("경제학의이해", 3, "전체", "교선"),
        ("현대사회와윤리", 3, "전체", "교선"), ("생활체육(테니스)", 1, "전체", "교선"),
        ("생활체육(요가)", 1, "", "교선"), ("음악의이해", 2, "전체", "교선"),
        ("미술감상", 2, "전체", "교선"), ("창의적문제해결", 3, "1~2", "핵교"),
        ("데이터리터러시", 3, "전체", "핵교"), ("글로벌리더십", 2, "전체", "교선"),
        ("진로탐색", 1, "1", "교필"), ("사회봉사", 1, "전체", "일선"),
        ("교육학개론", 2, "2", "교직"), ("중국어기초", 3, "전체", "교선"),
        ("일본어기초", 3, "전체", "교선"), ("과학기술과사회", 3, "전체", "교선"),
        ("환경과인간", 2, "전체", "교선"), ("AI와미래사회", 3, "전체", "핵교"),
    ]),
}

#: 데이터 크기별 학과 비중(강좌 수 기준).
DEPT_SHARE: dict[int, dict[str, float]] = {
    config.MOCK_SMALL_SIZE: {"CSE": 0.40, "EEE": 0.12, "GED": 0.48},
    config.MOCK_LARGE_SIZE: {"CSE": 0.20, "EEE": 0.13, "MEC": 0.13, "BUS": 0.14, "GED": 0.40},
}

#: B형에서 원문 표기를 바꿔 쓰는 이수구분/학년(정규화 규칙 검증용).
CATEGORY_LONG_FORM = {
    "전필": "전공필수", "전선": "전공선택", "전기": "전공기초", "전심": "전공심화",
    "교필": "교양필수", "교선": "교양선택", "기교": "기초교양", "핵교": "핵심교양",
    "일선": "일반선택", "교직": "교직",
}

PROFESSORS = (
    "김민준", "이서연", "박지호", "최수아", "정도윤", "강하은", "조예준", "윤지유",
    "장시우", "임서윤", "한주원", "오하린", "서건우", "신채원", "권우진", "황다은",
)
BUILDINGS = {"CSE": "공학관", "EEE": "공학관", "MEC": "제2공학관", "BUS": "경영관", "GED": "인문관"}

ONLINE_TIME_TEXTS = ("", "원격", "미정", "TBA", "시간미정", "온라인(비대면)")
#: 일부러 깨진 강의시간(파싱 실패 리포트 검증용). 정답 슬롯은 None.
MALFORMED_TIME_TEXTS = ("월1,2 수", "화99", "X3,4", "목 25:00~26:00", "금 3-1", "수@#")

WEEKDAY_COUNT = 5  # 월~금
SATURDAY_INDEX = config.DAYS.index("토")
DAY_PAIRS = ((0, 2), (1, 3), (2, 4), (0, 3), (1, 4))
LAB_KEYWORDS = ("실습", "실험")
NIGHT_PERIODS = tuple(sorted(config.NIGHT_PERIOD_LABELS.values()))
NIGHT_LETTER = {v: k for k, v in config.NIGHT_PERIOD_LABELS.items()}
SPLIT_PROBABILITY = 0.6  # 3시간 수업을 2+1로 나눌 확률
LETTER_NIGHT_PROBABILITY = 0.5  # 야간 교시를 A/B로 표기할 확률
ROOM_COLUMN_BLANK_PROBABILITY = 0.5  # 강의실을 시간 문자열에 넣었을 때 강의실 칸을 비울 확률
ROOM_FLOORS = range(1, 6)
ROOM_NUMBERS = range(1, 12)
SECTION_CAPACITY = (30, 40, 50, 60, 80)


@dataclass(frozen=True)
class MockSection:
    """mock 강좌 1개와 정답."""

    dept_prefix: str
    code: str
    section: str
    name: str
    credits: float
    category_raw: str
    dept: str
    grade_raw: str
    professor: str
    time_text: str
    room: str
    delivery: str
    expected_slots: frozenset[Slot] | None  # None = 의도적으로 깨진 문자열
    expected_online: bool
    continuation_text: str = ""  # 이어지는 행에 적을 나머지 강의시간(있으면)


# ---------------------------------------------------------------------------
# 시간 생성
# ---------------------------------------------------------------------------


def _hours_for(name: str, credits: float) -> int:
    """학점·과목 성격에 따른 주당 수업 교시 수(실습/실험은 +1)."""
    hours = max(1, int(round(credits)))
    if any(k in name for k in LAB_KEYWORDS):
        hours += 1
    return hours


def _blocks_for(hours: int, rng: random.Random, force_split: bool = False) -> list[int]:
    """주당 교시 수를 요일별 연속 블록 길이로 나눈다. ``force_split``이면 2개 요일로."""
    if force_split and hours >= 2:
        return [hours - hours // 2, hours // 2]
    if hours >= 4:
        return [hours // 2, hours - hours // 2]
    if hours == 3:
        return [2, 1] if rng.random() < SPLIT_PROBABILITY else [3]
    if hours == 2:
        return [1, 1] if rng.random() < SPLIT_PROBABILITY else [2]
    return [hours]


def _random_slots(
    hours: int, night: bool, rng: random.Random, force_split: bool = False
) -> dict[int, list[int]]:
    """요일 → 교시 리스트(연속 블록)를 무작위로 만든다."""
    blocks = _blocks_for(hours, rng, force_split)
    if len(blocks) == 1:
        day = SATURDAY_INDEX if rng.random() < config.MOCK_SATURDAY_RATIO else rng.randrange(WEEKDAY_COUNT)
        days = [day]
    else:
        days = list(rng.choice(DAY_PAIRS))
    if night:
        start_range = range(NIGHT_PERIODS[0], NIGHT_PERIODS[-1] + 2)
    else:
        start_range = range(1, config.DAY_PERIOD_COUNT + 1)
    result: dict[int, list[int]] = {}
    shared_start = None
    for day, length in zip(days, blocks):
        starts = [s for s in start_range if s + length - 1 <= (NIGHT_PERIODS[-1] if night else config.DAY_PERIOD_COUNT)]
        if shared_start is None or shared_start not in starts:
            shared_start = rng.choice(starts)
        result[day] = list(range(shared_start, shared_start + length))
    return result


# ---------------------------------------------------------------------------
# 강의시간 렌더러: 같은 슬롯을 다양한 포털 표기로
# ---------------------------------------------------------------------------

Schedule = dict[int, list[int]]


def _period_token(period: int, letters: bool) -> str:
    return NIGHT_LETTER[period] if letters and period in NIGHT_LETTER else str(period)


def _is_consecutive(periods: Sequence[int]) -> bool:
    return all(b - a == 1 for a, b in zip(periods, periods[1:]))


def render_comma(s: Schedule, letters: bool, room: str) -> str:
    """"월1,2,3 수4"."""
    return " ".join(f"{config.DAYS[d]}{','.join(_period_token(p, letters) for p in ps)}" for d, ps in s.items())


def render_range(s: Schedule, letters: bool, room: str) -> str:
    """"월1-3 수4" (연속 2교시 이상은 범위, 구분자는 '-' 또는 '~')."""
    parts = []
    for d, ps in s.items():
        if len(ps) >= 2 and _is_consecutive(ps):
            sep = "-" if ps[0] % 2 else "~"
            parts.append(f"{config.DAYS[d]}{_period_token(ps[0], letters)}{sep}{_period_token(ps[-1], letters)}")
        else:
            parts.append(f"{config.DAYS[d]}{','.join(_period_token(p, letters) for p in ps)}")
    return " ".join(parts)


def render_paren(s: Schedule, letters: bool, room: str) -> str:
    """"월(1,2)화(3)"."""
    return "".join(f"{config.DAYS[d]}({','.join(_period_token(p, letters) for p in ps)})" for d, ps in s.items())


def render_with_room(s: Schedule, letters: bool, room: str) -> str:
    """"월1,2(공학관301) 수3(공학관301)"."""
    return " ".join(
        f"{config.DAYS[d]}{','.join(_period_token(p, letters) for p in ps)}({room})" for d, ps in s.items()
    )


def render_clock(s: Schedule, letters: bool, room: str) -> str:
    """"월 09:00~10:50, 수 09:00~09:50" (요일별 교시가 연속일 때만)."""
    if not all(_is_consecutive(ps) for ps in s.values()):
        return render_comma(s, letters, room)
    sched = DEFAULT_PERIOD_SCHEDULE
    return ", ".join(
        f"{config.DAYS[d]} {minutes_to_hhmm(sched.start_minutes(ps[0]))}~{minutes_to_hhmm(sched.end_minutes(ps[-1]))}"
        for d, ps in s.items()
    )


def render_slash(s: Schedule, letters: bool, room: str) -> str:
    """"화3,4/목3,4"."""
    return "/".join(f"{config.DAYS[d]}{','.join(_period_token(p, letters) for p in ps)}" for d, ps in s.items())


def render_comma_days(s: Schedule, letters: bool, room: str) -> str:
    """"화3,4, 목3,4" (요일 구분자도 쉼표)."""
    return ", ".join(f"{config.DAYS[d]}{','.join(_period_token(p, letters) for p in ps)}" for d, ps in s.items())


Renderer = Callable[[Schedule, bool, str], str]

#: 서로 다른 표기 7종(소형 파일에서 차례로 모두 쓴다).
UNIQUE_RENDERERS: tuple[Renderer, ...] = (
    render_comma, render_range, render_paren, render_with_room,
    render_clock, render_slash, render_comma_days,
)
#: 대형 파일의 무작위 선택용(가장 흔한 "월1,2 수3" 형식에 가중).
RANDOM_RENDERERS: tuple[Renderer, ...] = (render_comma, *UNIQUE_RENDERERS)

#: 소형 파일에 반드시 넣는 특수 케이스.
SHOWCASE_ONLINE_TEXTS = ("", "원격", "미정", "온라인(비대면)")
SHOWCASE_MALFORMED_TEXTS = ("월1,2 수", "화99", "X3,4")
SHOWCASE_NIGHT = ((render_comma, True), (render_clock, False), (render_range, True))
SHOWCASE_CONTINUATION_COUNT = 2
UNDECIDED_TIME_TEXTS = ("미정", "TBA", "시간미정")

KIND_NORMAL = "normal"
KIND_ONLINE = "online"
KIND_MALFORMED = "malformed"
KIND_NIGHT = "night"
KIND_CONTINUATION = "continuation"


@dataclass(frozen=True)
class _Plan:
    """분반 하나를 어떻게 만들지(종류, 표기, 특수 문자열)."""

    kind: str
    renderer: Renderer = render_comma
    letters: bool = False
    text: str = ""


@dataclass(frozen=True)
class _Skeleton:
    """시간이 정해지기 전의 분반 뼈대."""

    prefix: str
    dept: str
    code: str
    number: int
    name: str
    credits: float
    grade_raw: str
    category_raw: str

    @property
    def hours(self) -> int:
        return _hours_for(self.name, self.credits)


# ---------------------------------------------------------------------------
# 강좌 생성
# ---------------------------------------------------------------------------


def _dept_quotas(size: int) -> dict[str, int]:
    """학과별 강좌 수(합계 = size)."""
    shares = DEPT_SHARE.get(size) or DEPT_SHARE[config.MOCK_LARGE_SIZE]
    quotas = {k: int(size * v) for k, v in shares.items()}
    leftover = size - sum(quotas.values())
    for key in sorted(shares, key=shares.get, reverse=True)[:leftover]:  # type: ignore[arg-type]
        quotas[key] += 1
    return quotas


def _skeletons(size: int, rng: random.Random) -> list[_Skeleton]:
    """학과 비중대로 교과목을 돌며 분반 뼈대 ``size``개를 만든다."""
    result: list[_Skeleton] = []
    for prefix, quota in _dept_quotas(size).items():
        dept_name, catalog = DEPARTMENTS[prefix]
        produced = cycle = 0
        while produced < quota:
            for index, (name, credits, grade_raw, category_raw) in enumerate(catalog):
                if produced >= quota:
                    break
                course_name = name if cycle == 0 else f"{name}{cycle + 1}"
                grade_digit = grade_raw[0] if grade_raw[:1].isdigit() else "0"
                code = f"{prefix}{grade_digit}{cycle}{index:02d}"
                count = rng.choices(config.MOCK_SECTION_COUNTS, config.MOCK_SECTION_WEIGHTS)[0]
                for number in range(1, min(count, quota - produced) + 1):
                    result.append(_Skeleton(prefix, dept_name, code, number, course_name,
                                            float(credits), grade_raw, category_raw))
                    produced += 1
            cycle += 1
    return result


def _showcase_plans(skeletons: Sequence[_Skeleton], rng: random.Random) -> list[_Plan]:
    """모든 표기·특수 케이스가 최소 1번씩 들어가도록 배치한다(소형 파일용)."""
    order = list(range(len(skeletons)))
    rng.shuffle(order)
    plans: dict[int, _Plan] = {}
    splittable = [i for i in order if skeletons[i].hours >= 2]
    for i in splittable[:SHOWCASE_CONTINUATION_COUNT]:
        plans[i] = _Plan(KIND_CONTINUATION)
    free = [i for i in order if i not in plans]
    specials = (
        [_Plan(KIND_ONLINE, text=t) for t in SHOWCASE_ONLINE_TEXTS]
        + [_Plan(KIND_MALFORMED, text=t) for t in SHOWCASE_MALFORMED_TEXTS]
        + [_Plan(KIND_NIGHT, renderer=r, letters=l) for r, l in SHOWCASE_NIGHT]
    )
    for i, plan in zip(free, specials):
        plans[i] = plan
    normal_index = 0
    for i in range(len(skeletons)):
        if i not in plans:
            renderer = UNIQUE_RENDERERS[normal_index % len(UNIQUE_RENDERERS)]
            plans[i] = _Plan(KIND_NORMAL, renderer=renderer)
            normal_index += 1
    return [plans[i] for i in range(len(skeletons))]


def _random_plan(rng: random.Random) -> _Plan:
    """비율(config.MOCK_*_RATIO)에 따라 무작위로 정한다(대형 파일용)."""
    roll = rng.random()
    if roll < config.MOCK_ONLINE_RATIO:
        return _Plan(KIND_ONLINE, text=rng.choice(ONLINE_TIME_TEXTS))
    if roll < config.MOCK_ONLINE_RATIO + config.MOCK_MALFORMED_RATIO:
        return _Plan(KIND_MALFORMED, text=rng.choice(MALFORMED_TIME_TEXTS))
    renderer = rng.choice(RANDOM_RENDERERS)
    if rng.random() < config.MOCK_NIGHT_RATIO:
        return _Plan(KIND_NIGHT, renderer=renderer, letters=rng.random() < LETTER_NIGHT_PROBABILITY)
    return _Plan(KIND_NORMAL, renderer=renderer)


def generate_sections(
    size: int = config.MOCK_SMALL_SIZE,
    seed: int = config.MOCK_SEED,
    showcase: bool | None = None,
) -> list[MockSection]:
    """mock 강좌 ``size``개를 결정적으로 생성한다(같은 seed → 같은 결과).

    Args:
        size: 강좌(분반) 수.
        seed: 난수 시드.
        showcase: True면 모든 표기·특수 케이스를 최소 1번씩 넣는다.
            None이면 소형(MOCK_SMALL_SIZE 이하)일 때 True.
    """
    rng = random.Random(seed)
    skeletons = _skeletons(size, rng)
    if showcase is None:
        showcase = size <= config.MOCK_SMALL_SIZE
    plans = _showcase_plans(skeletons, rng) if showcase else [_random_plan(rng) for _ in skeletons]
    return [_make_section(sk, plan, rng) for sk, plan in zip(skeletons, plans)]


def _make_section(sk: _Skeleton, plan: _Plan, rng: random.Random) -> MockSection:
    """뼈대와 계획으로 분반 하나의 시간·강의실·교수를 정한다."""
    room = f"{BUILDINGS[sk.prefix]}{rng.choice(ROOM_FLOORS)}{rng.choice(ROOM_NUMBERS):02d}"
    common = dict(
        dept_prefix=sk.prefix, code=sk.code, section=f"{sk.number:02d}", name=sk.name,
        credits=sk.credits, category_raw=sk.category_raw, dept=sk.dept,
        grade_raw=sk.grade_raw, professor=rng.choice(PROFESSORS),
    )
    if plan.kind == KIND_ONLINE:
        delivery = "대면" if plan.text in UNDECIDED_TIME_TEXTS else "원격"
        return MockSection(**common, time_text=plan.text, room="", delivery=delivery,
                           expected_slots=frozenset(), expected_online=True)
    if plan.kind == KIND_MALFORMED:
        return MockSection(**common, time_text=plan.text, room=room, delivery="대면",
                           expected_slots=None, expected_online=False)

    night = plan.kind == KIND_NIGHT
    split = plan.kind == KIND_CONTINUATION
    schedule = _random_slots(sk.hours, night, rng, force_split=split)
    expected = frozenset((d, p) for d, ps in schedule.items() for p in ps)
    continuation = ""
    if split:
        first_day, *rest = schedule
        text = render_comma({first_day: schedule[first_day]}, plan.letters, room)
        continuation = render_comma({d: schedule[d] for d in rest}, plan.letters, room)
    else:
        text = plan.renderer(schedule, plan.letters, room)
    room_cell = room
    if plan.renderer is render_with_room and rng.random() < ROOM_COLUMN_BLANK_PROBABILITY:
        room_cell = ""
    return MockSection(**common, time_text=text, room=room_cell, delivery="대면",
                       expected_slots=expected, expected_online=False,
                       continuation_text=continuation)


# ---------------------------------------------------------------------------
# 엑셀 쓰기
# ---------------------------------------------------------------------------

HEADER_A = ("No", "학수번호", "분반", "교과목명", "학점", "이수구분", "개설학과", "대상학년",
            "담당교수", "강의시간", "강의실", "수업방식", "비고")
HEADER_B = ("학수번호-분반", "강좌명", "학점(이론-실습)", "구분", "주관학과", "학년",
            "교수명", "요일/시간", "강의장소", "강의유형", "정원")
TITLE_A = "2026학년도 1학기 개설강좌 조회"
SUBTITLE_A = "조회조건: 전체 학과 / 조회일시 2026-02-10 10:00"
HEADER_FILL = PatternFill("solid", fgColor="DDEBF7")
COLUMN_WIDTH = 14
WIDE_COLUMN_WIDTH = 30
WIDE_HEADERS = {"강의시간", "요일/시간", "교과목명", "강좌명"}


def _style_header(ws, row: int, ncols: int) -> None:
    for col in range(1, ncols + 1):
        cell = ws.cell(row=row, column=col)
        cell.font = Font(bold=True)
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center")


def _set_widths(ws, header: Sequence[str]) -> None:
    for col, name in enumerate(header, start=1):
        ws.column_dimensions[get_column_letter(col)].width = WIDE_COLUMN_WIDTH if name in WIDE_HEADERS else COLUMN_WIDTH


def _credits_b(credits: float, name: str) -> str:
    """B형 학점 표기 "학점-이론-실습"."""
    lab = 1 if any(k in name for k in LAB_KEYWORDS) else 0
    theory = max(int(credits) - lab, 0)
    return f"{credits:g}-{theory}-{lab * 2}"


def _grade_b(grade_raw: str) -> str:
    """B형 대상학년 표기("2학년", "전학년", "1~2학년" 등)."""
    if grade_raw in ("", "전체"):
        return "전학년" if grade_raw else ""
    return f"{grade_raw}학년"


def write_variant_a(sections: Sequence[MockSection], path: Path) -> None:
    """A형 엑셀: 제목 2행 + 빈 행 + 헤더(4행). 분반은 숫자 셀, 이어지는 행 포함."""
    wb = Workbook()
    ws = wb.active
    ws.title = "개설강좌"
    ws.append([TITLE_A])
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(HEADER_A))
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([SUBTITLE_A])
    ws.append([])
    ws.append(list(HEADER_A))
    _style_header(ws, ws.max_row, len(HEADER_A))
    for no, s in enumerate(sections, start=1):
        ws.append([no, s.code, int(s.section), s.name, s.credits, s.category_raw, s.dept,
                   s.grade_raw, s.professor, s.time_text, s.room, s.delivery, ""])
        if s.continuation_text:
            row = [None] * len(HEADER_A)
            row[HEADER_A.index("강의시간")] = s.continuation_text
            row[HEADER_A.index("강의실")] = s.room
            ws.append(row)
    _set_widths(ws, HEADER_A)
    wb.save(path)


def write_variant_b(sections: Sequence[MockSection], path: Path) -> None:
    """B형 엑셀: 헤더가 1행, 다른 헤더명, 코드-분반 결합, 반복 헤더 행 포함."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(list(HEADER_B))
    _style_header(ws, 1, len(HEADER_B))
    rng = random.Random(config.MOCK_SEED)
    for index, s in enumerate(sections, start=1):
        ws.append([f"{s.code}-{s.section}", s.name, _credits_b(s.credits, s.name),
                   CATEGORY_LONG_FORM.get(s.category_raw, s.category_raw), s.dept,
                   _grade_b(s.grade_raw), s.professor, s.time_text, s.room, s.delivery,
                   rng.choice(SECTION_CAPACITY)])
        if index % config.MOCK_REPEAT_HEADER_EVERY == 0 and index < len(sections):
            ws.append(list(HEADER_B))
    _set_widths(ws, HEADER_B)
    wb.save(path)


def write_mock_files(out_dir: Path, seed: int = config.MOCK_SEED) -> tuple[Path, Path]:
    """소형(A형)·대형(B형) mock 파일을 만든다. 반환: (소형 경로, 대형 경로)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    small = out_dir / config.MOCK_SMALL_FILENAME
    large = out_dir / config.MOCK_LARGE_FILENAME
    write_variant_a(generate_sections(config.MOCK_SMALL_SIZE, seed), small)
    write_variant_b(generate_sections(config.MOCK_LARGE_SIZE, seed), large)
    return small, large


def main(argv: list[str] | None = None) -> None:
    """명령행 진입점."""
    parser = argparse.ArgumentParser(description="mock 개설강의 엑셀 생성")
    parser.add_argument("--out", type=Path, default=Path("data"))
    parser.add_argument("--seed", type=int, default=config.MOCK_SEED)
    args = parser.parse_args(argv)
    for path in write_mock_files(args.out, args.seed):
        print(f"생성: {path}")


if __name__ == "__main__":
    main()
