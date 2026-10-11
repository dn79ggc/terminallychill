import json
import xml.etree.ElementTree as ET
from pathlib import Path

from app.graph import DEFAULT_PATH, load_graph, validate_graph_document

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample" / "atl_synthetic.json"
SVG = ROOT / "web" / "concourse.svg"
SVG_NS = "{http://www.w3.org/2000/svg}"


def _document() -> dict:
    return json.loads(DEFAULT_PATH.read_text(encoding="utf-8"))


def _highest_sample_gate() -> int:
    flights = json.loads(SAMPLE.read_text(encoding="utf-8"))["flights"]
    numbers = []
    for flight in flights:
        gate = (flight.get("gate") or "").strip().upper()
        if len(gate) > 1 and gate[0] == "B" and gate[1:].isdigit():
            numbers.append(int(gate[1:]))
    return max(numbers)


def test_graph_document_is_connected_and_covers_sample_gates():
    data = _document()
    assert validate_graph_document(data) == []
    zones = {zone["id"]: zone for zone in data["zones"]}
    nodes = {node["id"] for node in data["nodes"]}
    for edge in data["edges"]:
        assert edge["a"] in nodes and edge["b"] in nodes
    for node in data["nodes"]:
        assert node["zone"] is None or node["zone"] in zones
    covered: dict[int, str] = {}
    for zone in zones.values():
        if zone["kind"] != "gates":
            continue
        low, high = zone["gate_range"]
        for number in range(low, high + 1):
            assert number not in covered
            covered[number] = zone["id"]
    highest = _highest_sample_gate()
    for number in range(1, highest + 1):
        assert number in covered
    assert sum(zone["kind"] == "rest" for zone in zones.values()) >= 3
    assert sum(zone["kind"] == "amenity" for zone in zones.values()) >= 2


def test_graph_loads_and_resolves_a_gate():
    graph = load_graph()
    assert graph.zone_for_gate("b12").id == "B-gates-11-20"
    assert graph.zone_for_gate("D9") is None
    assert graph.shortest_path("B-gates-11-20", "B-rest-mid") is not None


def test_svg_has_each_zone_once_and_a_viewbox():
    data = _document()
    root = ET.parse(SVG).getroot()
    assert root.attrib.get("viewBox")
    ids = [element.attrib["id"] for element in root.iter() if "id" in element.attrib]
    for zone in data["zones"]:
        assert ids.count(zone["id"]) == 1
        match = next(element for element in root.iter() if element.attrib.get("id") == zone["id"])
        titles = [child for child in list(match) if child.tag == f"{SVG_NS}title"]
        assert len(titles) == 1 and titles[0].text
