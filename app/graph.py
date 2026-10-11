"""Walking graph for one concourse. Loaded from data/atl_graph.json. No database."""
from __future__ import annotations

import heapq
import json
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / "data" / "atl_graph.json"

KINDS = ("gates", "amenity", "rest", "service")


@dataclass(frozen=True)
class Zone:
    id: str
    label: str
    kind: str
    capacity: int
    gate_range: tuple[int, int] | None = None
    seats: int | None = None
    attractiveness: float = 1.0
    near_zone: str | None = None


@dataclass(frozen=True)
class Graph:
    concourse: str
    version: int
    svg: str
    zones: dict[str, Zone]
    node_ids: tuple[str, ...]
    coordinates: dict[str, tuple[float, float]]
    adj: dict[str, tuple[tuple[str, int], ...]]
    raw: dict

    def zone_for_gate(self, gate: str) -> Zone | None:
        parsed = parse_gate(gate)
        if parsed is None or parsed[0] != self.concourse:
            return None
        number = parsed[1]
        matches = [
            zone
            for zone in self.zones.values()
            if zone.kind == "gates"
            and zone.gate_range is not None
            and zone.gate_range[0] <= number <= zone.gate_range[1]
        ]
        if len(matches) != 1:
            return None
        return matches[0]

    def gate_label_span(self) -> str:
        ranges = [zone.gate_range for zone in self.zones.values() if zone.gate_range]
        low = min(item[0] for item in ranges)
        high = max(item[1] for item in ranges)
        return f"{self.concourse}{low}-{self.concourse}{high}"

    def shortest_path(self, start: str, goal: str) -> tuple[int, list[str]] | None:
        if start not in self.adj or goal not in self.adj:
            return None
        if start == goal:
            return 0, [start]
        # Path copies are cheap: the concourse graph is about 15 nodes.
        heap: list[tuple[int, str, list[str]]] = [(0, start, [start])]
        seen: set[str] = set()
        while heap:
            dist, node, path = heapq.heappop(heap)
            if node in seen:
                continue
            seen.add(node)
            if node == goal:
                return dist, path
            for nxt, walk_s in self.adj[node]:
                if nxt not in seen:
                    heapq.heappush(heap, (dist + walk_s, nxt, path + [nxt]))
        return None

    def walk_seconds(self, start: str, goal: str) -> int | None:
        found = self.shortest_path(start, goal)
        if found is None:
            return None
        return found[0]


def parse_gate(gate: str | None) -> tuple[str, int] | None:
    if not gate:
        return None
    text = gate.strip().upper()
    if len(text) < 2 or not text[0].isalpha() or not text[1:].isdigit():
        return None
    return text[0], int(text[1:])


def load_graph(path: Path = DEFAULT_PATH) -> Graph:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    problems = validate_graph_document(data)
    if problems:
        raise ValueError("; ".join(problems))
    zones: dict[str, Zone] = {}
    for item in data["zones"]:
        span = item.get("gate_range")
        zones[item["id"]] = Zone(
            id=item["id"],
            label=item["label"],
            kind=item["kind"],
            capacity=int(item["capacity"]),
            gate_range=(int(span[0]), int(span[1])) if span else None,
            seats=item.get("seats"),
            attractiveness=float(item.get("attractiveness", 1.0)),
            near_zone=item.get("near_zone"),
        )
    coordinates = {node["id"]: (float(node["x"]), float(node["y"])) for node in data["nodes"]}
    adj: dict[str, list[tuple[str, int]]] = {node["id"]: [] for node in data["nodes"]}
    for edge in data["edges"]:
        walk_s = int(edge["walk_s"])
        adj[edge["a"]].append((edge["b"], walk_s))
        adj[edge["b"]].append((edge["a"], walk_s))
    return Graph(
        concourse=data["concourse"],
        version=int(data["version"]),
        svg=data["svg"],
        zones=zones,
        node_ids=tuple(coordinates),
        coordinates=coordinates,
        adj={key: tuple(value) for key, value in adj.items()},
        raw=data,
    )


def validate_graph_document(data: dict) -> list[str]:
    problems: list[str] = []
    zone_ids = [zone["id"] for zone in data.get("zones", [])]
    if len(zone_ids) != len(set(zone_ids)):
        problems.append("duplicate zone id")
    zones = {zone["id"]: zone for zone in data.get("zones", [])}
    node_ids = [node["id"] for node in data.get("nodes", [])]
    if len(node_ids) != len(set(node_ids)):
        problems.append("duplicate node id")
    nodes = set(node_ids)
    for node in data.get("nodes", []):
        zone = node.get("zone")
        if zone is not None and zone not in zones:
            problems.append(f"node {node['id']} references missing zone {zone}")
    for edge in data.get("edges", []):
        if edge["a"] not in nodes or edge["b"] not in nodes:
            problems.append(f"edge {edge['a']}-{edge['b']} references a missing node")
    if nodes and not _connected(nodes, data.get("edges", [])):
        problems.append("graph is not connected")
    covered: dict[int, str] = {}
    for zone in zones.values():
        if zone.get("kind") == "gates":
            span = zone.get("gate_range")
            if not span:
                problems.append(f"{zone['id']} has no gate_range")
                continue
            for number in range(int(span[0]), int(span[1]) + 1):
                if number in covered:
                    problems.append(f"gate {number} is in {covered[number]} and {zone['id']}")
                covered[number] = zone["id"]
        if zone.get("near_zone") and zone["near_zone"] not in zones:
            problems.append(f"{zone['id']} near_zone is missing")
    kinds = [zone.get("kind") for zone in zones.values()]
    if kinds.count("rest") < 3:
        problems.append("need at least 3 rest zones")
    if kinds.count("amenity") < 2:
        problems.append("need at least 2 amenity zones")
    if "service" not in kinds:
        problems.append("need a service zone")
    return problems


def _connected(nodes: set[str], edges: list[dict]) -> bool:
    if not nodes:
        return False
    adj: dict[str, list[str]] = {node: [] for node in nodes}
    for edge in edges:
        if edge["a"] in adj and edge["b"] in adj:
            adj[edge["a"]].append(edge["b"])
            adj[edge["b"]].append(edge["a"])
    start = next(iter(nodes))
    seen = {start}
    stack = [start]
    while stack:
        node = stack.pop()
        for nxt in adj[node]:
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen == nodes


_GRAPH: Graph | None = None


def get_graph() -> Graph:
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = load_graph()
    return _GRAPH
