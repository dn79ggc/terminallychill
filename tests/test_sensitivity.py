import runpy
from pathlib import Path

REPORT = Path(__file__).resolve().parents[1] / "scripts" / "sensitivity.py"


def test_sensitivity_report_is_honest_about_what_it_cannot_show():
    module = runpy.run_path(str(REPORT))
    text = module["build_report"]()
    assert "no ground-truth" in text
    assert "Load factor 0.70" in text
    assert "Seats +20%" in text
    assert "Arrival peak 70 min before departure" in text
    assert "guarantee" not in text.lower()
    assert "machine learning" not in text.lower()
