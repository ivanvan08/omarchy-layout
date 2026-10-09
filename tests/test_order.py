"""Hermetic checks of how built-in-layout (dwindle) workspaces are compared with their profile tree.

Run: python3 -m unittest tests/test_order.py
"""

import importlib.util
import itertools
import json
import os
import re
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


class WorkspaceLayoutPersistence(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.saved_dir = cli.WORKSPACE_LAYOUTS_DIR
        self.saved_profile_path = cli.PROFILE_PATH
        self.saved_env_profile = os.environ.get("OMARCHY_LAYOUT_PROFILE")
        self.saved_env_layouts = os.environ.get("OMARCHY_LAYOUT_WORKSPACE_LAYOUTS_DIR")

        cli.WORKSPACE_LAYOUTS_DIR = self.tmp.name
        if "OMARCHY_LAYOUT_WORKSPACE_LAYOUTS_DIR" in os.environ:
            del os.environ["OMARCHY_LAYOUT_WORKSPACE_LAYOUTS_DIR"]

    def tearDown(self):
        cli.WORKSPACE_LAYOUTS_DIR = self.saved_dir
        cli.PROFILE_PATH = self.saved_profile_path
        if self.saved_env_profile is not None:
            os.environ["OMARCHY_LAYOUT_PROFILE"] = self.saved_env_profile
        elif "OMARCHY_LAYOUT_PROFILE" in os.environ:
            del os.environ["OMARCHY_LAYOUT_PROFILE"]

        if self.saved_env_layouts is not None:
            os.environ["OMARCHY_LAYOUT_WORKSPACE_LAYOUTS_DIR"] = self.saved_env_layouts
        elif "OMARCHY_LAYOUT_WORKSPACE_LAYOUTS_DIR" in os.environ:
            del os.environ["OMARCHY_LAYOUT_WORKSPACE_LAYOUTS_DIR"]

        self.tmp.cleanup()

    def test_override_profile_never_persists_layout_files(self):
        profile = {"workspaces": {"1": {"class": "A"}}}
        cli.PROFILE_PATH = "/tmp/fake-profile.json"
        os.environ["OMARCHY_LAYOUT_PROFILE"] = "/tmp/fake-profile.json"

        written = cli.write_workspace_layouts(profile, "external", dry_run=False)
        self.assertEqual(written, [])
        self.assertEqual(os.listdir(self.tmp.name), [])

    def test_default_profile_persists_files_and_cleans_stale_files(self):
        cli.PROFILE_PATH = None
        if "OMARCHY_LAYOUT_PROFILE" in os.environ:
            del os.environ["OMARCHY_LAYOUT_PROFILE"]

        stale_path = os.path.join(self.tmp.name, "6.lua")
        with open(stale_path, "w") as f:
            f.write("-- written by omarchy-layout - https://github.com/ivanvan08/omarchy-layout\n")
            f.write('hl.workspace_rule({ workspace = "6", layout = "lua:omarchy-layout" })\n')

        foreign_path = os.path.join(self.tmp.name, "8.lua")
        with open(foreign_path, "w") as f:
            f.write('-- written by omarchy toggle\nhl.workspace_rule({ workspace = "8", layout = "dwindle" })\n')

        profile = {"workspaces": {"1": {"class": "A"}}}

        dry_written = cli.write_workspace_layouts(profile, "external", dry_run=True)
        self.assertEqual(dry_written, [os.path.join(self.tmp.name, "1.lua")])
        self.assertTrue(os.path.exists(stale_path))
        self.assertTrue(os.path.exists(foreign_path))
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "1.lua")))

        written = cli.write_workspace_layouts(profile, "external", dry_run=False)
        self.assertEqual(written, [os.path.join(self.tmp.name, "1.lua")])
        self.assertFalse(os.path.exists(stale_path))
        self.assertTrue(os.path.exists(foreign_path))
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, "1.lua")))



class CenterCommandSelection(unittest.TestCase):
    def setUp(self):
        self.monitors = [
            {
                "id": 0,
                "name": "Virtual-1",
                "x": 0,
                "y": 0,
                "width": 3200,
                "height": 900,
                "scale": 1.0,
                "activeWorkspace": {"id": 2, "name": "2"},
                "specialWorkspace": {"id": 0, "name": ""},
            }
        ]
        self.tiled_left = {
            "address": "0x101",
            "class": "Left",
            "at": [12, 42],
            "size": [786, 846],
            "workspace": {"id": 2, "name": "2"},
            "floating": False,
            "mapped": True,
        }
        self.tiled_center = {
            "address": "0x102",
            "class": "Center",
            "at": [812, 42],
            "size": [1576, 846],
            "workspace": {"id": 2, "name": "2"},
            "floating": False,
            "mapped": True,
        }
        self.tiled_right = {
            "address": "0x103",
            "class": "Right",
            "at": [2402, 42],
            "size": [786, 846],
            "workspace": {"id": 2, "name": "2"},
            "floating": False,
            "mapped": True,
        }
        self.clients = [self.tiled_left, self.tiled_center, self.tiled_right]

    def test_hover_inside_tiled_window(self):
        cursor = (2500, 200)  # inside tiled_right
        target, err = cli.find_target_window(cursor, self.clients, self.monitors, None)
        self.assertIsNone(err)
        self.assertEqual(target, self.tiled_right)

    def test_hover_in_gap_falls_back_to_active(self):
        cursor = (805, 200)  # in gap between 798 and 812
        active = self.tiled_left
        target, err = cli.find_target_window(cursor, self.clients, self.monitors, active)
        self.assertIsNone(err)
        self.assertEqual(target, self.tiled_left)

    def test_hover_in_gap_with_no_active_window(self):
        cursor = (805, 200)  # in gap
        target, err = cli.find_target_window(cursor, self.clients, self.monitors, None)
        self.assertEqual(err, "none")
        self.assertIsNone(target)

    def test_floating_window_on_top_returns_floating_error(self):
        floating = {
            "address": "0x201",
            "class": "Float",
            "at": [900, 100],
            "size": [400, 300],
            "workspace": {"id": 2, "name": "2"},
            "floating": True,
            "mapped": True,
        }
        clients = [self.tiled_left, self.tiled_center, self.tiled_right, floating]
        cursor = (1000, 200)  # inside floating window (and inside tiled_center)
        target, err = cli.find_target_window(cursor, clients, self.monitors, None)
        self.assertEqual(err, "floating")
        self.assertIsNone(target)

    def test_shown_special_workspace_takes_precedence(self):
        special_monitors = [
            {
                "id": 0,
                "name": "Virtual-1",
                "x": 0,
                "y": 0,
                "width": 3200,
                "height": 900,
                "scale": 1.0,
                "activeWorkspace": {"id": 2, "name": "2"},
                "specialWorkspace": {"id": -99, "name": "special:scratchpad"},
            }
        ]
        special_window = {
            "address": "0x301",
            "class": "Special",
            "at": [812, 42],
            "size": [1576, 846],
            "workspace": {"id": -99, "name": "special:scratchpad"},
            "floating": False,
            "mapped": True,
        }
        clients = self.clients + [special_window]
        cursor = (1000, 200)  # inside both special_window and tiled_center
        target, err = cli.find_target_window(cursor, clients, special_monitors, None)
        self.assertIsNone(err)
        self.assertEqual(target, special_window)

    def test_identify_master_window(self):
        workarea_mid_x = 1600.0
        # 1 window
        self.assertEqual(cli.identify_master_window([self.tiled_center], workarea_mid_x), self.tiled_center)

        # 2 windows (center and left)
        two_wins = [self.tiled_left, self.tiled_center]
        self.assertEqual(cli.identify_master_window(two_wins, workarea_mid_x), self.tiled_center)

        # 3 windows (left, center, right)
        self.assertEqual(cli.identify_master_window(self.clients, workarea_mid_x), self.tiled_center)

        # 4 windows (stacked sides)
        w4_top_left = {
            "address": "0x401", "class": "TL", "at": [12, 42], "size": [786, 416],
            "workspace": {"id": 2, "name": "2"}, "floating": False, "mapped": True,
        }
        w4_bot_left = {
            "address": "0x402", "class": "BL", "at": [12, 472], "size": [786, 416],
            "workspace": {"id": 2, "name": "2"}, "floating": False, "mapped": True,
        }
        four_wins = [w4_top_left, w4_bot_left, self.tiled_center, self.tiled_right]
        self.assertEqual(cli.identify_master_window(four_wins, workarea_mid_x), self.tiled_center)

        # 5 windows
        w5_bot_right = {
            "address": "0x501", "class": "BR", "at": [2402, 472], "size": [786, 416],
            "workspace": {"id": 2, "name": "2"}, "floating": False, "mapped": True,
        }
        five_wins = [w4_top_left, w4_bot_left, self.tiled_center, self.tiled_right, w5_bot_right]
        self.assertEqual(cli.identify_master_window(five_wins, workarea_mid_x), self.tiled_center)

    def test_swap_plan(self):
        # Target already master -> no swap
        self.assertEqual(cli.plan_center_swap(self.tiled_center, self.tiled_center), [])

        # Target is side window -> swap with master
        swaps = cli.plan_center_swap(self.tiled_right, self.tiled_center)
        self.assertEqual(swaps, [("0x103", "0x102")])

    def test_workarea_mid_x_accounts_for_scale_and_reserved_area(self):
        monitor = {"x": 0, "width": 5120, "scale": 2, "reserved": [12, 30, 12, 0]}
        # logical width 2560, work area 12..2548, middle 1280
        self.assertEqual(cli.workarea_mid_x(monitor), 1280.0)
        self.assertEqual(cli.workarea_mid_x({"x": 3200, "width": 1920, "scale": 1}), 4160.0)
        self.assertEqual(cli.workarea_mid_x(None), 0.0)

    def test_is_centered_uses_the_shape_tolerance(self):
        mid = 1600.0
        self.assertTrue(cli.is_centered(self.tiled_center, mid))  # 812 + 1576/2 = 1600
        offset = dict(self.tiled_center, at=[840, 42])
        self.assertTrue(cli.is_centered(offset, mid))  # 28 px off, inside the 32 px tolerance
        off = dict(self.tiled_center, at=[900, 42])
        self.assertFalse(cli.is_centered(off, mid))  # 88 px off


SPECIAL = "special:scratchpad"


def scratchpad_window(address, klass, at, size):
    return {
        "address": address,
        "class": klass,
        "at": at,
        "size": size,
        "workspace": {"id": -98, "name": SPECIAL},
        "floating": False,
        "mapped": True,
        "monitor": 0,
    }


# Dwindle-ish geometry on the 3200x900 work area: A and B share the left half, C is the wide right
# column, so the tree is [[A | B] | C].
SPECIAL_BEFORE = [
    scratchpad_window("0xa01", "A", [12, 42], [785, 846]),
    scratchpad_window("0xa02", "B", [809, 42], [785, 846]),
    scratchpad_window("0xa03", "C", [1606, 42], [1582, 846]),
]
# After the switch: B is the centred master (middle 967 + 1266/2 = 1600 = the work-area middle).
SPECIAL_AFTER = [
    scratchpad_window("0xa01", "A", [12, 42], [943, 846]),
    scratchpad_window("0xa02", "B", [967, 42], [1266, 846]),
    scratchpad_window("0xa03", "C", [2245, 42], [943, 846]),
]
SPECIAL_MONITOR = {
    "id": 0,
    "name": "Virtual-1",
    "x": 0,
    "y": 0,
    "width": 3200,
    "height": 900,
    "scale": 1,
    "reserved": [0, 30, 0, 0],
    "activeWorkspace": {"id": 1, "name": "1"},
    "specialWorkspace": {"id": -98, "name": SPECIAL},
}
SPECIAL_CURSOR = (2700, 400)  # inside C in both frames (BEFORE 1606..3188, AFTER 2245..3188)


class CenterToggle(unittest.TestCase):
    """The real cmd_center as a toggle, against a faked compositor, on a scratchpad (negative id)."""

    def setUp(self):
        import argparse
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.state_dir = os.path.join(self.tmp.name, "state")
        self.layouts_dir = os.path.join(self.tmp.name, "workspace-layouts")
        os.makedirs(self.state_dir)
        os.makedirs(self.layouts_dir)

        self.saved = (
            cli.STATE_DIR,
            cli.WORKSPACE_LAYOUTS_DIR,
            cli.INSTANCE,
            cli.cursor_position,
            cli.clients,
            cli.hyprctl_json,
            cli.eval_lua,
            cli.send_notification,
            cli.rebuild_workspace,
        )
        self.saved_env = os.environ.pop("OMARCHY_LAYOUT_WORKSPACE_LAYOUTS_DIR", None)
        cli.STATE_DIR = self.state_dir
        cli.WORKSPACE_LAYOUTS_DIR = self.layouts_dir
        cli.INSTANCE = "test-session"
        self.argparse = argparse

        self.evals = []
        self.rebuilds = []
        self.mastered = False
        self.layouts = [{"id": -98, "name": SPECIAL, "tiledLayout": "dwindle"}]

        def read_clients():
            frame = SPECIAL_AFTER if self.mastered else SPECIAL_BEFORE
            return [dict(c) for c in frame]

        cli.cursor_position = lambda: SPECIAL_CURSOR
        cli.clients = read_clients
        cli.hyprctl_json = self.fake_query
        cli.eval_lua = self.fake_eval
        cli.send_notification = lambda *a, **k: None
        cli.rebuild_workspace = lambda ws, node, live, area: (self.rebuilds.append((ws, node)), "rebuilt")[1]

    def fake_query(self, *args):
        if args == ("monitors",):
            return [SPECIAL_MONITOR]
        if args == ("activewindow",):
            return None
        return self.layouts

    def fake_eval(self, lua):
        """Record the call and model the compositor: a workspace_rule eval swaps the geometry."""
        self.evals.append(lua)
        match = re.search(r'workspace_rule\(\{ workspace = "[^"]+", layout = "([^"]+)"', lua)
        if match:
            self.mastered = match.group(1) == "master"
            self.layouts = [dict(w, tiledLayout=match.group(1)) for w in self.layouts]
        return True

    def tearDown(self):
        (
            cli.STATE_DIR,
            cli.WORKSPACE_LAYOUTS_DIR,
            cli.INSTANCE,
            cli.cursor_position,
            cli.clients,
            cli.hyprctl_json,
            cli.eval_lua,
            cli.send_notification,
            cli.rebuild_workspace,
        ) = self.saved
        if self.saved_env is not None:
            os.environ["OMARCHY_LAYOUT_WORKSPACE_LAYOUTS_DIR"] = self.saved_env
        self.tmp.cleanup()

    def run_center(self, mode=None):
        return cli.cmd_center(self.argparse.Namespace(mode=mode, verbose=False))

    def state_files(self):
        return sorted(name for name in os.listdir(self.state_dir) if name.startswith("center-"))

    def layout_files(self):
        return sorted(os.listdir(self.layouts_dir))

    def test_a_special_workspace_is_addressed_by_name_and_never_by_its_negative_id(self):
        self.run_center()
        rules = [lua for lua in self.evals if "workspace_rule" in lua]
        self.assertEqual(len(rules), 1, self.evals)
        self.assertIn(f'workspace = "{SPECIAL}"', rules[0])
        swaps = [lua for lua in self.evals if "window.swap" in lua]
        self.assertEqual(len(swaps), 1, self.evals)
        self.assertIn("0xa03", swaps[0])  # the hovered window C
        self.assertIn("0xa02", swaps[0])  # the master B
        for lua in self.evals:
            self.assertIsNone(re.search(r"-\d", lua), lua)

    def test_the_written_rule_has_no_negative_number_anywhere(self):
        self.run_center()
        self.assertEqual(self.layout_files(), [f"{SPECIAL.replace(':', '-')}.lua"], self.layout_files())
        for name in self.layout_files():
            self.assertFalse(name.startswith("-"), name)
        with open(os.path.join(self.layouts_dir, self.layout_files()[0])) as handle:
            text = handle.read()
        self.assertIn(f'workspace = "{SPECIAL}"', text)
        self.assertIn('layout = "master"', text)
        self.assertIn('orientation = "center"', text)
        self.assertIsNone(re.search(r"-\d", text), text)

    def test_on_records_the_previous_state_and_off_puts_it_back(self):
        self.run_center()
        state_files = self.state_files()
        self.assertEqual(len(state_files), 1, state_files)
        self.assertTrue(state_files[0].startswith("center-test-session-"), state_files[0])
        with open(os.path.join(self.state_dir, state_files[0])) as handle:
            state = json.load(handle)
        self.assertEqual(state["layout"], "dwindle")
        self.assertEqual(state["selector"], SPECIAL)
        self.assertEqual(state["layout_opts"], None)
        self.assertEqual(state["order"], ["A", "B", "C"])
        self.assertEqual(state["persisted_text"], None)
        self.assertEqual(state["node"]["children"][0]["class"], "A")

        before = len(self.evals)
        self.run_center()
        rules = [lua for lua in self.evals[before:] if "workspace_rule" in lua]
        self.assertEqual(len(rules), 1, self.evals[before:])
        self.assertIn('layout = "dwindle"', rules[0])
        self.assertEqual(self.rebuilds, [(SPECIAL, state["dwindle_node"])])
        self.assertEqual(self.state_files(), [])
        self.assertEqual(self.layout_files(), [])

    def test_the_recorded_dwindle_tree_nests_the_way_dwindle_built_it(self):
        # A and B share the left half, C is the wide right column: [[A | B] | C]. The flat `save`
        # shape cannot express that (it simulates to the wide column first), so the dwindle tree is
        # recorded separately and is what OFF rebuilds from.
        self.run_center()
        with open(os.path.join(self.state_dir, self.state_files()[0])) as handle:
            state = json.load(handle)
        self.assertEqual(
            state["dwindle_node"],
            {
                "split": "columns",
                "children": [
                    {"split": "columns", "children": [{"class": "A"}, {"class": "B"}]},
                    {"class": "C"},
                ],
            },
        )
        start, steps = cli.build_steps(state["dwindle_node"])
        boxes = {start: (12, 42, 5096, 1386)}
        for new, target, split in steps:
            x, y, w, h = boxes[target]
            boxes[target], boxes[new] = (x, y, w / 2, h), (x + w / 2, y, w / 2, h)
        self.assertGreater(boxes["C"][2], boxes["A"][2], boxes)  # the wide column is C
        self.assertEqual(boxes["A"][2], boxes["B"][2], boxes)

    def test_on_is_idempotent(self):
        self.run_center("on")
        first = len(self.evals)
        self.run_center("on")
        self.assertEqual(self.evals[first:], [])
        self.assertEqual(len(self.state_files()), 1)

    def test_off_without_a_recorded_state_does_nothing(self):
        self.assertEqual(self.run_center("off"), 0)
        self.assertEqual(self.evals, [])
        self.assertEqual(self.state_files(), [])

    def test_off_restores_the_rule_file_a_profile_workspace_had(self):
        original = '-- written by omarchy-layout\nhl.workspace_rule({ workspace = "special:scratchpad", layout = "dwindle" })\n'
        path = os.path.join(self.layouts_dir, "special-scratchpad.lua")
        with open(path, "w") as handle:
            handle.write(original)
        self.run_center("on")
        with open(path) as handle:
            self.assertIn('layout = "master"', handle.read())
        self.run_center("off")
        with open(path) as handle:
            self.assertEqual(handle.read(), original)
        self.assertEqual(self.state_files(), [])

    def test_stale_state_of_other_sessions_is_pruned(self):
        other = os.path.join(self.state_dir, "center-other-session-special-scratchpad.json")
        mine = os.path.join(self.state_dir, "center-test-session-3.json")
        flag = os.path.join(self.state_dir, "assembled-other-session-2")
        for path in (other, mine, flag):
            with open(path, "w") as handle:
                handle.write("{}\n")
        cli.prune_other_session_state()
        self.assertEqual(self.state_files(), ["center-test-session-3.json"])

    def test_rule_target_derivation(self):
        self.assertEqual(cli.workspace_rule_target({"id": 3, "name": "3"}), ("3", "3"))
        self.assertEqual(
            cli.workspace_rule_target({"id": -98, "name": SPECIAL}), (SPECIAL, "special-scratchpad")
        )
        self.assertEqual(cli.workspace_rule_target({"id": 7, "name": "web"}), ("7", "7"))
        self.assertIsNone(cli.workspace_rule_target({"id": -98, "name": ""}))


class CenterOnNormalWorkspace(unittest.TestCase):
    """The toggle on a numbered workspace whose rule file already exists (a profile workspace)."""

    def setUp(self):
        import argparse
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.state_dir = os.path.join(self.tmp.name, "state")
        self.layouts_dir = os.path.join(self.tmp.name, "workspace-layouts")
        os.makedirs(self.state_dir)
        os.makedirs(self.layouts_dir)
        self.original = '-- written by omarchy-layout - https://github.com/ivanvan08/omarchy-layout\nhl.workspace_rule({ workspace = "2", layout = "dwindle" })\n'
        self.rule_path = os.path.join(self.layouts_dir, "2.lua")
        with open(self.rule_path, "w") as handle:
            handle.write(self.original)

        self.saved = (
            cli.STATE_DIR, cli.WORKSPACE_LAYOUTS_DIR, cli.INSTANCE,
            cli.cursor_position, cli.clients, cli.hyprctl_json, cli.eval_lua, cli.rebuild_workspace,
        )
        cli.STATE_DIR, cli.WORKSPACE_LAYOUTS_DIR, cli.INSTANCE = self.state_dir, self.layouts_dir, "test-session"
        self.argparse = argparse
        self.evals = []

        windows = [
            {"address": "0xb01", "class": "A", "at": [12, 42], "size": [785, 846],
             "workspace": {"id": 2, "name": "2"}, "floating": False, "mapped": True, "monitor": 0},
            {"address": "0xb02", "class": "B", "at": [809, 42], "size": [785, 846],
             "workspace": {"id": 2, "name": "2"}, "floating": False, "mapped": True, "monitor": 0},
            {"address": "0xb03", "class": "C", "at": [1606, 42], "size": [1582, 846],
             "workspace": {"id": 2, "name": "2"}, "floating": False, "mapped": True, "monitor": 0},
        ]
        after = [dict(w, at=[12, 42], size=[943, 846]) for w in windows[:1]]
        after.append(dict(windows[1], at=[967, 42], size=[1266, 846]))
        after.append(dict(windows[2], at=[2245, 42], size=[943, 846]))
        self.mastered = False

        def read_clients():
            return [dict(c) for c in (after if self.mastered else windows)]

        monitor = dict(SPECIAL_MONITOR, activeWorkspace={"id": 2, "name": "2"}, specialWorkspace={"id": 0, "name": ""})
        self.layouts = [{"id": 2, "name": "2", "tiledLayout": "dwindle"}]
        cli.cursor_position = lambda: SPECIAL_CURSOR
        cli.clients = read_clients
        cli.hyprctl_json = lambda *args: [monitor] if args == ("monitors",) else (None if args == ("activewindow",) else self.layouts)
        cli.eval_lua = self.fake_eval
        cli.rebuild_workspace = lambda ws, node, live, area: "rebuilt"

    def fake_eval(self, lua):
        """Record the call and model the compositor: a workspace_rule eval swaps the geometry."""
        self.evals.append(lua)
        match = re.search(r'workspace_rule\(\{ workspace = "[^"]+", layout = "([^"]+)"', lua)
        if match:
            self.mastered = match.group(1) == "master"
            self.layouts = [dict(w, tiledLayout=match.group(1)) for w in self.layouts]
        return True

    def tearDown(self):
        (
            cli.STATE_DIR, cli.WORKSPACE_LAYOUTS_DIR, cli.INSTANCE,
            cli.cursor_position, cli.clients, cli.hyprctl_json, cli.eval_lua, cli.rebuild_workspace,
        ) = self.saved
        self.tmp.cleanup()

    def test_a_numbered_workspace_keeps_its_numeric_key_and_restores_its_rule_file(self):
        cli.cmd_center(self.argparse.Namespace(mode=None, verbose=False))
        self.assertEqual(sorted(os.listdir(self.layouts_dir)), ["2.lua"])
        with open(self.rule_path) as handle:
            self.assertIn('layout = "master"', handle.read())
        self.assertEqual(sorted(n for n in os.listdir(self.state_dir) if n.startswith("center-")),
                         ["center-test-session-2.json"])

        cli.cmd_center(self.argparse.Namespace(mode="off", verbose=False))
        with open(self.rule_path) as handle:
            self.assertEqual(handle.read(), self.original)
        self.assertEqual([n for n in os.listdir(self.state_dir) if n.startswith("center-")], [])
        rules = [lua for lua in self.evals if "workspace_rule" in lua]
        self.assertEqual(rules[-1], 'hl.workspace_rule({ workspace = "2", layout = "dwindle" })')


if __name__ == "__main__":
    unittest.main()
