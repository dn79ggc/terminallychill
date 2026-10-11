from datetime import datetime, timedelta, timezone

from app.repo import ARRIVAL_PAD, flight_from_row, query_bounds


def test_query_window_is_padded_on_both_sides():
    start = datetime(2026, 10, 10, 18, 0, tzinfo=timezone.utc)
    end = start + timedelta(hours=3)
    begin, finish = query_bounds(start, end)
    assert begin == start - ARRIVAL_PAD
    assert finish == end + ARRIVAL_PAD
    assert ARRIVAL_PAD == timedelta(minutes=90)


def test_row_becomes_a_flight():
    flight = flight_from_row(
        {
            "uid": "snapshot:ZZ1",
            "ident": "ZZ1",
            "operator": "ZZ",
            "gate": "B12",
            "concourse": "B",
            "terminal": "S",
            "aircraft_type": "B738",
            "scheduled_out": datetime(2026, 10, 10, 18, 0, tzinfo=timezone.utc),
            "estimated_out": None,
            "delay_s": 60,
            "cancelled": False,
            "source": "snapshot",
            "fetched_at": datetime(2026, 10, 10, 17, 0, tzinfo=timezone.utc),
        }
    )
    assert flight.gate == "B12"
    assert flight.estimated_out is None
    assert flight.scheduled_out.tzinfo is not None
