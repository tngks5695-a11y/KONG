"""Phase 1: 비트마스크 헬퍼와 mock 데이터 생성기 테스트."""

from __future__ import annotations

import pytest

from timetable import config
from timetable.mock_data import (
    MALFORMED_TIME_TEXTS,
    SHOWCASE_MALFORMED_TEXTS,
    SHOWCASE_ONLINE_TEXTS,
    generate_sections,
)
from timetable.models import Category, Course, mask_to_slots, slot_bit, slots_to_mask


def test_slot_bit_layout() -> None:
    assert slot_bit(0, 1) == 0
    assert slot_bit(0, config.MAX_PERIOD) == config.MAX_PERIOD - 1
    assert slot_bit(1, 1) == config.MAX_PERIOD  # 화요일 1교시
    assert slot_bit(2, 4) == 2 * config.MAX_PERIOD + 3


@pytest.mark.parametrize(("day", "period"), [(-1, 1), (len(config.DAYS), 1), (0, 0), (0, config.MAX_PERIOD + 1)])
def test_slot_bit_out_of_range(day: int, period: int) -> None:
    with pytest.raises(ValueError):
        slot_bit(day, period)


def test_mask_roundtrip() -> None:
    slots = frozenset({(0, 1), (0, 2), (2, 9), (3, 10), (6, config.MAX_PERIOD)})
    assert mask_to_slots(slots_to_mask(slots)) == slots
    assert slots_to_mask([]) == 0


def _course(code: str, slots: set[tuple[int, int]]) -> Course:
    return Course(code, "01", code, 3.0, Category.MAJOR, "전필", "X", frozenset(), "P",
                  frozenset(slots), slots_to_mask(slots), False, "")


def test_course_conflict_and_keys() -> None:
    a = _course("A", {(0, 1), (0, 2)})
    b = _course("B", {(0, 2), (1, 1)})
    c = _course("C", {(0, 3)})
    assert a.conflicts_with(b) and not a.conflicts_with(c)
    assert a.key == ("A", "01") and a.group == "A" and a.is_major and not a.is_general
    assert len({a, b, c, _course("A", {(0, 1), (0, 2)})}) == 3  # 해시 가능, 값 동등


def test_mock_is_deterministic() -> None:
    assert generate_sections(config.MOCK_LARGE_SIZE) == generate_sections(config.MOCK_LARGE_SIZE)
    assert generate_sections(config.MOCK_LARGE_SIZE, seed=1) != generate_sections(config.MOCK_LARGE_SIZE)


@pytest.mark.parametrize("size", [config.MOCK_SMALL_SIZE, config.MOCK_LARGE_SIZE])
def test_mock_sizes_and_groups(size: int) -> None:
    sections = generate_sections(size)
    assert len(sections) == size
    keys = [(s.code, s.section) for s in sections]
    assert len(set(keys)) == size  # (코드, 분반) 고유
    assert any(sum(1 for s in sections if s.code == code) > 1 for code, _ in keys)  # 분반 여러 개인 그룹 존재


def test_small_mock_covers_every_case() -> None:
    sections = generate_sections(config.MOCK_SMALL_SIZE)
    texts = {s.time_text for s in sections}
    assert set(SHOWCASE_ONLINE_TEXTS) <= texts
    assert set(SHOWCASE_MALFORMED_TEXTS) <= texts
    assert sum(1 for s in sections if s.continuation_text) == 2
    night = [s for s in sections if s.expected_slots and max(p for _, p in s.expected_slots) > config.DAY_PERIOD_COUNT]
    assert any("A" in s.time_text for s in night)  # 야간 문자 표기
    assert any(":" in s.time_text for s in night)  # 야간 시각 표기
    markers = {"-": "범위", "(": "괄호", ":": "시각", "/": "슬래시", ", ": "쉼표 요일구분"}
    for marker in markers:
        assert any(marker in s.time_text for s in sections if s.expected_slots), markers[marker]


def test_mock_truth_is_consistent() -> None:
    for s in generate_sections(config.MOCK_LARGE_SIZE):
        if s.time_text in MALFORMED_TIME_TEXTS:
            assert s.expected_slots is None
        elif s.expected_online:
            assert s.expected_slots == frozenset()
        else:
            assert s.expected_slots
            assert all(1 <= p <= config.MAX_PERIOD and 0 <= d < len(config.DAYS) for d, p in s.expected_slots)
