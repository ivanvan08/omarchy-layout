"""Hermetic checks of the swap planning that puts built-in-layout workspaces into profile order.

Run: python3 -m unittest tests/test_order.py
"""

import importlib.util
import itertools
import os
import unittest
from importlib.machinery import SourceFileLoader

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_loader = SourceFileLoader("omarchy_layout_cli", os.path.join(ROOT, "bin", "layout"))
_spec = importlib.util.spec_from_loader("omarchy_layout_cli", _loader)
cli = importlib.util.module_from_spec(_spec)
_loader.exec_module(cli)

AREA = (12, 42, 1176, 666)

# Two chats sharing the left half, an editor alone in the right half.
CHAT_WALL = {
    "layout": "dwindle",
    "split": "columns",
    "ratios": [0.5, 0.5],
    "children": [
        {
            "split": "columns",
            "ratios": [0.5, 0.5],
            "children": [{"class": "ChatA"}, {"class": "ChatB"}],
        },
        {"class": "Editor"},
    ],
}


def apply_swaps(order, swaps):
    order = list(order)
    for i, j in swaps:
        order[i], order[j] = order[j], order[i]
    return order


class DesiredOrder(unittest.TestCase):
    def test_columns_read_left_to_right(self):
        self.assertEqual(cli.desired_order(CHAT_WALL, AREA), ["ChatA", "ChatB", "Editor"])

    def test_rows_inside_columns_read_column_by_column(self):
        node = {
            "split": "columns",
            "children": [
                {"split": "rows", "children": [{"class": "Top"}, {"class": "Bottom"}]},
                {"class": "Right"},
            ],
        }
        self.assertEqual(cli.desired_order(node, AREA), ["Top", "Bottom", "Right"])


class PlanSwaps(unittest.TestCase):
    def test_late_window_in_the_middle_is_swapped_to_the_right(self):
        # The case seen at login: the late window took the middle cell, the right one took its place.
        current = ["ChatA", "Editor", "ChatB"]
        desired = ["ChatA", "ChatB", "Editor"]
        swaps = cli.plan_swaps(current, desired)
        self.assertEqual(swaps, [(1, 2)])
        self.assertEqual(apply_swaps(current, swaps), desired)

    def test_ordered_workspace_needs_no_swap(self):
        desired = ["ChatA", "ChatB", "Editor"]
        self.assertEqual(cli.plan_swaps(desired, desired), [])

    def test_every_permutation_is_sorted_in_at_most_n_minus_one_swaps(self):
        desired = ["A", "B", "C", "D"]
        for current in itertools.permutations(desired):
            swaps = cli.plan_swaps(list(current), desired)
            self.assertEqual(apply_swaps(current, swaps), desired, current)
            self.assertLessEqual(len(swaps), len(desired) - 1, current)


if __name__ == "__main__":
    unittest.main()
