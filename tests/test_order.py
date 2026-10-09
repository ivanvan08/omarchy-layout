"""Hermetic checks of how built-in-layout (dwindle) workspaces are compared with their profile tree.

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

# The work area of the 3200x900 logical monitor with a 30 px bar, as dwindle sees it.
AREA = (12, 42, 3176, 846)

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

# Measured on the live session, 2026-10-07 17:01, after the old order check said "ok":
# ChatA spans the left half and the other two share the right one.
WRONG_TREE = [
    ("ChatA", (12, 42, 1581, 846)),
    ("ChatB", (1607, 42, 781, 846)),
    ("Editor", (2402, 42, 786, 846)),
]
# The same session when the tree was right.
RIGHT_TREE = [
    ("ChatA", (12, 42, 781, 846)),
    ("ChatB", (807, 42, 786, 846)),
    ("Editor", (1607, 42, 1581, 846)),
]

# Center preset: left, middle, right columns.
CENTER_WALL = {
    "layout": "center",
    "split": "columns",
    "children": [{"class": "Left"}, {"class": "Middle"}, {"class": "Right"}],
}
CENTER_RIGHT_TREE = [
    ("Left", (12, 42, 785, 846)),
    ("Middle", (809, 42, 1582, 846)),
    ("Right", (2403, 42, 785, 846)),
]


def relabel(rects, order):
    return [(klass, rect) for klass, (_, rect) in zip(order, rects)]


class Classify(unittest.TestCase):
    def test_a_window_spanning_the_wrong_half_needs_a_rebuild(self):
        # Reads ChatA | ChatB | Editor left to right, which is what the old check compared.
        self.assertEqual(cli.classify(WRONG_TREE, CHAT_WALL, AREA), "rebuild")

    def test_the_profile_tree_is_ok(self):
        self.assertEqual(cli.classify(RIGHT_TREE, CHAT_WALL, AREA), "ok")

    def test_right_cells_with_the_wrong_windows_need_a_swap(self):
        swapped = relabel(RIGHT_TREE, ["ChatA", "Editor", "ChatB"])
        self.assertEqual(cli.classify(swapped, CHAT_WALL, AREA), "swap")

    def test_a_missing_window_waits(self):
        self.assertEqual(cli.classify(RIGHT_TREE[:2], CHAT_WALL, AREA), "incomplete")

    def test_a_window_outside_the_profile_is_left_alone(self):
        extra = RIGHT_TREE + [("Other", (1607, 500, 1581, 388))]
        self.assertEqual(cli.classify(extra, CHAT_WALL, AREA), "foreign")


    def test_center_preset_in_right_cells_is_ok(self):
        self.assertEqual(cli.classify(CENTER_RIGHT_TREE, CENTER_WALL, AREA), "ok")

    def test_center_preset_with_swapped_windows_needs_swap(self):
        swapped = relabel(CENTER_RIGHT_TREE, ["Middle", "Left", "Right"])
        self.assertEqual(cli.classify(swapped, CENTER_WALL, AREA), "swap")

    def test_center_preset_with_wrong_cell_shapes_needs_rebuild(self):
        wrong_shapes = relabel(WRONG_TREE, ["Left", "Middle", "Right"])
        self.assertEqual(cli.classify(wrong_shapes, CENTER_WALL, AREA), "rebuild")

    def test_center_preset_missing_window_is_incomplete(self):
        self.assertEqual(cli.classify(CENTER_RIGHT_TREE[:2], CENTER_WALL, AREA), "incomplete")

    def test_center_preset_extra_window_is_foreign(self):
        extra = CENTER_RIGHT_TREE + [("Other", (500, 42, 200, 846))]
        self.assertEqual(cli.classify(extra, CENTER_WALL, AREA), "foreign")

class BuildPlan(unittest.TestCase):
    def test_the_second_half_is_split_off_before_the_first_half_grows(self):
        start, steps = cli.build_steps(CHAT_WALL)
        self.assertEqual(start, "ChatA")
        self.assertEqual(steps, [("Editor", "ChatA", "columns"), ("ChatB", "ChatA", "columns")])

    def test_simulated_inserts_reproduce_the_profile_cells(self):
        start, steps = cli.build_steps(CHAT_WALL)
        cells = {start: (0.0, 0.0, 1.0, 1.0)}
        for new, target, split in steps:
            x, y, w, h = cells[target]
            if split == "columns":
                cells[target], cells[new] = (x, y, w / 2, h), (x + w / 2, y, w / 2, h)
            else:
                cells[target], cells[new] = (x, y, w, h / 2), (x, y + h / 2, w, h / 2)
        self.assertEqual(cells["Editor"], (0.5, 0.0, 0.5, 1.0))
        self.assertEqual(cells["ChatA"], (0.0, 0.0, 0.25, 1.0))
        self.assertEqual(cells["ChatB"], (0.25, 0.0, 0.25, 1.0))

    def test_three_columns_nest_to_the_right(self):
        node = {"split": "columns", "children": [{"class": "A"}, {"class": "B"}, {"class": "C"}]}
        self.assertEqual(cli.build_steps(node), ("A", [("B", "A", "columns"), ("C", "B", "columns")]))

    def test_the_wall_is_buildable_on_a_wide_screen(self):
        self.assertTrue(cli.build_feasible(CHAT_WALL, AREA, 1.0))

    def test_rows_in_a_wide_cell_cannot_be_built(self):
        # dwindle splits a wide cell side by side, whatever the profile asks.
        node = {"split": "rows", "children": [{"class": "Top"}, {"class": "Bottom"}]}
        self.assertFalse(cli.build_feasible(node, AREA, 1.0))



class CenterPreset(unittest.TestCase):
    def test_expected_cells_default_ratio(self):
        boxes = cli.natural_boxes(CENTER_WALL, AREA)
        self.assertEqual(
            boxes,
            [
                ("Left", (12, 42, 785, 846)),
                ("Middle", (809, 42, 1582, 846)),
                ("Right", (2403, 42, 785, 846)),
            ],
        )

    def test_expected_cells_non_default_ratio(self):
        node = {
            "layout": "center",
            "split": "columns",
            "ratios": [0.2, 0.6, 0.2],
            "children": [{"class": "Left"}, {"class": "Middle"}, {"class": "Right"}],
        }
        boxes = cli.natural_boxes(node, AREA)
        self.assertEqual(
            boxes,
            [
                ("Left", (12, 42, 626, 846)),
                ("Middle", (650, 42, 1900, 846)),
                ("Right", (2562, 42, 626, 846)),
            ],
        )

    def test_child_count_less_than_three_rejected(self):
        node = {
            "layout": "center",
            "split": "columns",
            "children": [{"class": "Left"}, {"class": "Right"}],
        }
        with self.assertRaises(ValueError) as ctx:
            cli.validate_workspace_node("3", node)
        self.assertIn("exactly 3 children", str(ctx.exception))

    def test_child_count_more_than_three_rejected(self):
        node = {
            "layout": "center",
            "split": "columns",
            "children": [
                {"class": "A"},
                {"class": "B"},
                {"class": "C"},
                {"class": "D"},
            ],
        }
        with self.assertRaises(ValueError) as ctx:
            cli.validate_workspace_node("3", node)
        self.assertIn("exactly 3 children", str(ctx.exception))

    def test_non_leaf_child_rejected(self):
        node = {
            "layout": "center",
            "split": "columns",
            "children": [
                {"class": "A"},
                {"split": "columns", "children": [{"class": "B"}]},
                {"class": "C"},
            ],
        }
        with self.assertRaises(ValueError) as ctx:
            cli.validate_workspace_node("3", node)
        self.assertIn("must be a leaf", str(ctx.exception))

    def test_unequal_side_ratios_rejected(self):
        node = {
            "layout": "center",
            "split": "columns",
            "ratios": [0.2, 0.5, 0.3],
            "children": [{"class": "A"}, {"class": "B"}, {"class": "C"}],
        }
        with self.assertRaises(ValueError) as ctx:
            cli.validate_workspace_node("3", node)
        self.assertIn("equal sides", str(ctx.exception))

    def test_non_columns_split_rejected(self):
        node = {
            "layout": "center",
            "split": "rows",
            "children": [{"class": "A"}, {"class": "B"}, {"class": "C"}],
        }
        with self.assertRaises(ValueError) as ctx:
            cli.validate_workspace_node("3", node)
        self.assertIn("split 'columns'", str(ctx.exception))

    def test_parking_behavior(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            saved = (cli.STATE_DIR, cli.INSTANCE)
            cli.STATE_DIR, cli.INSTANCE = tmp, "session-test"
            try:
                self.assertTrue(cli.parking("3", CENTER_WALL, "external"))
                open(cli.assembled_flag("3"), "w").close()
                self.assertFalse(cli.parking("3", CENTER_WALL, "external"))
            finally:
                cli.STATE_DIR, cli.INSTANCE = saved

class Parking(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.saved = (cli.STATE_DIR, cli.INSTANCE)
        cli.STATE_DIR, cli.INSTANCE = self.tmp.name, "session-a"

    def tearDown(self):
        cli.STATE_DIR, cli.INSTANCE = self.saved
        self.tmp.cleanup()

    def test_a_dwindle_workspace_is_parked_until_this_session_assembled_it(self):
        self.assertTrue(cli.parking("2", CHAT_WALL, "external"))
        open(cli.assembled_flag("2"), "w").close()
        self.assertFalse(cli.parking("2", CHAT_WALL, "external"))

    def test_a_flag_from_another_session_does_not_count(self):
        open(os.path.join(cli.STATE_DIR, "assembled-session-b-2"), "w").close()
        self.assertTrue(cli.parking("2", CHAT_WALL, "external"))

    def test_the_laptop_panel_and_managed_workspaces_never_park(self):
        self.assertFalse(cli.parking("2", CHAT_WALL, "internal"))
        managed = {key: value for key, value in CHAT_WALL.items() if key != "layout"}
        self.assertFalse(cli.parking("2", managed, "external"))




class PlanSwaps(unittest.TestCase):
    def test_every_permutation_is_sorted_in_at_most_n_minus_one_swaps(self):
        desired = ["A", "B", "C", "D"]
        for current in itertools.permutations(desired):
            order = list(current)
            swaps = cli.plan_swaps(order, desired)
            for i, j in swaps:
                order[i], order[j] = order[j], order[i]
            self.assertEqual(order, desired, current)
            self.assertLessEqual(len(swaps), len(desired) - 1, current)

    def test_every_permutation_of_three_is_sorted_in_at_most_two_swaps(self):
        desired = ["Left", "Middle", "Right"]
        for current in itertools.permutations(desired):
            order = list(current)
            swaps = cli.plan_swaps(order, desired)
            for i, j in swaps:
                order[i], order[j] = order[j], order[i]
            self.assertEqual(order, desired, current)
            self.assertLessEqual(len(swaps), 2, current)


if __name__ == "__main__":
    unittest.main()
