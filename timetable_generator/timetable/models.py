"""도메인 데이터 모델.

- ``Category``: 이수구분 정규화 값(전공/교양/기타). 원문은 ``Course.category_raw``에 유지한다.
- ``Course``: 분반 1개(=강좌 1개). 같은 ``code``의 분반들은 한 그룹이다.
- 시간 비트마스크: 비트 위치 = ``day_index * MAX_PERIOD + (period - 1)``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Iterable

from timetable import config

Slot = tuple[int, int]
"""(day_index, period). day_index는 config.DAYS의 인덱스(0=월), period는 1부터."""


class Category(StrEnum):
    """이수구분 정규화 값."""

    MAJOR = config.CATEGORY_MAJOR
    GENERAL = config.CATEGORY_GENERAL
    OTHER = config.CATEGORY_OTHER


def slot_bit(day_index: int, period: int, max_period: int = config.MAX_PERIOD) -> int:
    """(요일, 교시) 한 칸의 비트 위치를 돌려준다.

    Raises:
        ValueError: 요일·교시가 지원 범위를 벗어난 경우.
    """
    if not 0 <= day_index < len(config.DAYS):
        raise ValueError(f"day_index 범위 밖: {day_index}")
    if not 1 <= period <= max_period:
        raise ValueError(f"교시 범위 밖: {period} (1..{max_period})")
    return day_index * max_period + (period - 1)


def slots_to_mask(slots: Iterable[Slot], max_period: int = config.MAX_PERIOD) -> int:
    """슬롯 집합을 정수 비트마스크로 바꾼다."""
    mask = 0
    for day_index, period in slots:
        mask |= 1 << slot_bit(day_index, period, max_period)
    return mask


def mask_to_slots(mask: int, max_period: int = config.MAX_PERIOD) -> frozenset[Slot]:
    """비트마스크를 슬롯 집합으로 되돌린다(slots_to_mask의 역함수)."""
    slots: set[Slot] = set()
    bit = 0
    while mask:
        if mask & 1:
            slots.add((bit // max_period, bit % max_period + 1))
        mask >>= 1
        bit += 1
    return frozenset(slots)


@dataclass(frozen=True, slots=True)
class Course:
    """개설 강좌(분반) 하나.

    Attributes:
        code: 과목코드. 같은 코드의 분반들이 한 그룹을 이룬다.
        section: 분반 문자열(숫자면 0 채움, 예: "01").
        name: 과목명.
        credits: 학점(0.5 단위 가능하므로 float).
        category: 정규화된 이수구분.
        category_raw: 원본 이수구분 문자열.
        dept: 개설학과.
        grade: 대상학년 집합. 빈 집합이면 '전체 학년'.
        professor: 담당교수.
        slots: 수업 칸 집합 (day_index, period).
        time_mask: ``slots``의 비트마스크.
        is_online: 시간 미정·원격 강의 여부(충돌 검사에서 제외).
        raw_time: 원본 강의시간 문자열.
        room: 강의실(강의시간 문자열에서 분리한 것 포함).
        source_row: 원본 엑셀 행 번호(1부터). 리포트용.
    """

    code: str
    section: str
    name: str
    credits: float
    category: Category
    category_raw: str
    dept: str
    grade: frozenset[int]
    professor: str
    slots: frozenset[Slot]
    time_mask: int
    is_online: bool
    raw_time: str
    room: str = ""
    source_row: int = 0
    grade_raw: str = field(default="", compare=False)

    @property
    def key(self) -> tuple[str, str]:
        """강좌 고유 키 (과목코드, 분반)."""
        return (self.code, self.section)

    @property
    def group(self) -> str:
        """그룹 키(과목코드). 한 조합에 그룹당 최대 1개만 들어간다."""
        return self.code

    @property
    def is_major(self) -> bool:
        """전공 과목 여부."""
        return self.category is Category.MAJOR

    @property
    def is_general(self) -> bool:
        """교양 과목 여부."""
        return self.category is Category.GENERAL

    def conflicts_with(self, other: "Course") -> bool:
        """두 강좌의 수업 시간이 한 칸이라도 겹치는지."""
        return (self.time_mask & other.time_mask) != 0
