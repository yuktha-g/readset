from __future__ import annotations

from readset.hunks import apply_edits, changed_ranges, locate, overlaps


def test_should_report_changed_line_ranges_when_lines_replaced() -> None:
    old = "a\nb\nc\nd\n"
    new = "a\nB\nc\nd\n"
    assert changed_ranges(old, new) == [(2, 2)]


def test_should_report_insertion_point_when_lines_added() -> None:
    old = "a\nb\n"
    new = "a\nx\ny\nb\n"
    assert changed_ranges(old, new) == [(2, 2)]


def test_should_report_deleted_range_when_lines_removed() -> None:
    old = "a\nb\nc\nd\n"
    new = "a\nd\n"
    assert changed_ranges(old, new) == [(2, 3)]


def test_should_report_multiple_ranges_when_separate_edits() -> None:
    old = "".join(f"line{i}\n" for i in range(1, 21))
    new = old.replace("line3\n", "three\n").replace("line17\n", "seventeen\n")
    assert changed_ranges(old, new) == [(3, 3), (17, 17)]


def test_should_locate_unique_needle_as_line_range() -> None:
    text = "one\ntwo\nthree\nfour\n"
    assert locate(text, "two\nthree") == (2, 3)
    assert locate(text, "four") == (4, 4)


def test_should_return_none_when_needle_missing_or_ambiguous() -> None:
    text = "x\nx\ny\n"
    assert locate(text, "z") is None
    assert locate(text, "x") is None


def test_should_overlap_when_ranges_touch_within_margin() -> None:
    assert overlaps((5, 5), (5, 5), margin=0)
    assert not overlaps((5, 5), (7, 7), margin=1)
    assert overlaps((5, 5), (7, 7), margin=2)
    assert overlaps((1, 10), (4, 6), margin=0)


def test_should_apply_edits_in_order_when_each_is_unique() -> None:
    assert apply_edits("a b c", [("a", "A"), ("c", "C")]) == "A b C"


def test_should_return_none_when_an_edit_is_not_unique() -> None:
    assert apply_edits("a a", [("a", "b")]) is None
    assert apply_edits("a", [("z", "b")]) is None
