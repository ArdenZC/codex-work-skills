from __future__ import annotations

import sys
import tempfile
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import render_qa  # noqa: E402


VERTICES = ("A", "B", "C", "D", "E")
EDGES = frozenset(
    {
        ("A", "B"),
        ("A", "C"),
        ("B", "C"),
        ("C", "D"),
        ("C", "E"),
        ("D", "E"),
    }
)


def adjacency_list(edges: frozenset[tuple[str, str]]) -> dict[str, list[str]]:
    adjacency = {vertex: set() for vertex in VERTICES}
    for left, right in edges:
        adjacency[left].add(right)
        adjacency[right].add(left)
    return {vertex: sorted(neighbors) for vertex, neighbors in adjacency.items()}


def depth_first_order(start: str, adjacency: dict[str, list[str]]) -> list[str]:
    order: list[str] = []
    visited: set[str] = set()

    def visit(vertex: str) -> None:
        visited.add(vertex)
        order.append(vertex)
        for neighbor in adjacency[vertex]:
            if neighbor not in visited:
                visit(neighbor)

    visit(start)
    return order


def breadth_first_order(start: str, adjacency: dict[str, list[str]]) -> list[str]:
    order: list[str] = []
    visited = {start}
    queue = deque([start])
    while queue:
        vertex = queue.popleft()
        order.append(vertex)
        for neighbor in adjacency[vertex]:
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)
    return order


def connected_components(edges: frozenset[tuple[str, str]]) -> list[tuple[str, ...]]:
    adjacency = adjacency_list(edges)
    unseen = set(VERTICES)
    components: list[tuple[str, ...]] = []
    while unseen:
        start = min(unseen)
        component: set[str] = set()
        queue = deque([start])
        unseen.remove(start)
        while queue:
            vertex = queue.popleft()
            component.add(vertex)
            for neighbor in adjacency[vertex]:
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    queue.append(neighbor)
        components.append(tuple(sorted(component)))
    return sorted(components)


class Issue71GraphFactsTests(unittest.TestCase):
    def test_undirected_adjacency_storage_and_alphabetical_order(self) -> None:
        adjacency = adjacency_list(EDGES)
        self.assertEqual(
            adjacency,
            {
                "A": ["B", "C"],
                "B": ["A", "C"],
                "C": ["A", "B", "D", "E"],
                "D": ["C", "E"],
                "E": ["C", "D"],
            },
        )
        self.assertEqual(sum(map(len, adjacency.values())), 2 * len(EDGES))
        for left, right in EDGES:
            self.assertIn(right, adjacency[left])
            self.assertIn(left, adjacency[right])

    def test_dfs_and_bfs_orders_from_d(self) -> None:
        adjacency = adjacency_list(EDGES)
        self.assertEqual(depth_first_order("D", adjacency), ["D", "C", "A", "B", "E"])
        self.assertEqual(breadth_first_order("D", adjacency), ["D", "C", "E", "A", "B"])

    def test_no_single_edge_removal_disconnects_graph(self) -> None:
        for removed in EDGES:
            with self.subTest(removed=removed):
                remaining = frozenset(EDGES - {removed})
                self.assertEqual(connected_components(remaining), [("A", "B", "C", "D", "E")])

    def test_removing_cd_and_ce_creates_the_claimed_components(self) -> None:
        remaining = frozenset(EDGES - {("C", "D"), ("C", "E")})
        self.assertEqual(connected_components(remaining), [("A", "B", "C"), ("D", "E")])


class Issue71RenderScopeTests(unittest.TestCase):
    def test_render_smoke_reports_visual_readability_as_not_evaluated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(render_qa, "find_renderer", return_value=None):
                result = render_qa.render_docx_directory(directory)
        self.assertEqual(result["status"], "not_executed")
        self.assertEqual(result["visual_readability_status"], "not_evaluated")


if __name__ == "__main__":
    unittest.main()
