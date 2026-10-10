from datetime import timezone

import pytest

from app.models import concourse_of, parse_dt


@pytest.mark.parametrize(
    "gate,expected",
    [("B22", "B"), ("t3", "T"), (" D13", "D"), ("F1", "F"), ("A", "A"), (None, None), ("", None), ("Z9", None), ("12", None)],
)
def test_concourse_of(gate, expected):
    assert concourse_of(gate) == expected


def test_parse_dt_variants():
    assert parse_dt("2026-10-10T18:00:00Z").utcoffset().total_seconds() == 0
    assert parse_dt("2026-10-10T14:00:00-04:00").hour == 18          # converted to UTC
    assert parse_dt("2026-10-10T18:00:00").tzinfo == timezone.utc    # naive -> assumed UTC
    assert parse_dt(None) is None
