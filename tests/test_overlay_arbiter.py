"""The arbiter as the explorer wires it: real fixtures, real tap points."""

import random
import unittest
from pathlib import Path

from PIL import Image

import auto_digiworld_batch2 as runner
import safe_tap

FIXTURES = Path(__file__).with_name("fixtures")
GUIDE = FIXTURES / "growth_guide_stage_failed.png"
BOARD = FIXTURES / "claw_board.png"


def image(path):
    with Image.open(path) as handle:
        return handle.convert("RGB")


class ArbiterWiringTests(unittest.TestCase):
    def test_the_growth_guide_panel_owns_the_frame_and_is_tapped(self):
        arbiter = runner.build_overlay_arbiter(lambda: 1)
        panel = image(GUIDE)
        decision = arbiter.observe(0, panel, None, panel.size)
        self.assertEqual((decision.kind, decision.owner),
                         ("dismiss", "growth_guide"))
        self.assertTrue(decision.evidence.get("stage_failed"))
        self.assertEqual(decision.point, runner.DISMISS_TAP_XY)

    def test_the_second_attempt_moves_to_the_other_safe_point(self):
        arbiter = runner.build_overlay_arbiter(lambda: 1)
        panel = image(GUIDE)
        first = arbiter.observe(0, panel, None, panel.size)
        second = arbiter.observe(1, panel, None, panel.size)
        self.assertNotEqual(first.point, second.point)
        # Below the guide and above the world/home button.
        self.assertAlmostEqual(second.point[1] / panel.size[1], .865,
                               places=2)

    def test_a_readable_board_is_never_owned_before_two_strikes(self):
        arbiter = runner.build_overlay_arbiter(lambda: 1)
        board = image(BOARD)
        self.assertEqual(arbiter.observe(0, board, None, board.size).kind,
                         "none")

    def test_an_unreadable_board_promotes_the_suspicion_at_two_strikes(self):
        strikes = {"n": 1}
        arbiter = runner.build_overlay_arbiter(lambda: strikes["n"])
        board = image(BOARD)
        self.assertEqual(arbiter.observe(0, board, None, board.size).kind,
                         "none")
        strikes["n"] = 2
        decision = arbiter.observe(1, board, None, board.size)
        self.assertEqual((decision.kind, decision.owner),
                         ("dismiss", "suspected_cover"))

    def test_a_cover_that_will_not_close_stops_the_run(self):
        arbiter = runner.build_overlay_arbiter(lambda: 5)
        board = image(BOARD)
        kinds = [arbiter.observe(t, board, None, board.size).kind
                 for t in range(4)]
        self.assertEqual(kinds, ["dismiss", "dismiss", "stop", "stop"])

    def test_the_panel_outranks_the_suspicion(self):
        arbiter = runner.build_overlay_arbiter(lambda: 5)
        panel = image(GUIDE)
        self.assertEqual(arbiter.observe(0, panel, None, panel.size).owner,
                         "growth_guide")


class TapPointTests(unittest.TestCase):
    BOARD_BOX = (100, 200, 600, 700)      # 5x5 cells of 100x100

    def test_without_jitter_the_tap_is_the_cell_centre(self):
        self.assertEqual(runner.cell_tap_point(self.BOARD_BOX, (2, 2)),
                         (350, 450))

    def test_jitter_never_leaves_the_cell(self):
        jitter = safe_tap.TapJitter(random.Random(4))
        for _ in range(500):
            x, y = runner.cell_tap_point(self.BOARD_BOX, (2, 2), jitter)
            # The cell spans 300..400 x 400..500; the safe radius is 20%
            # of the cell, so the tap stays well inside it.
            self.assertTrue(320 <= x <= 380, x)
            self.assertTrue(420 <= y <= 480, y)

    def test_consecutive_taps_on_one_cell_differ(self):
        jitter = safe_tap.TapJitter(random.Random(4))
        first = runner.cell_tap_point(self.BOARD_BOX, (1, 1), jitter)
        second = runner.cell_tap_point(self.BOARD_BOX, (1, 1), jitter)
        self.assertNotEqual(first, second)

    def test_a_button_tap_stays_inside_its_radius(self):
        jitter = safe_tap.TapJitter(random.Random(9))
        for _ in range(200):
            x, y = runner.button_tap_point((640, 1180), jitter)
            self.assertLessEqual(abs(x - 640), 11)
            self.assertLessEqual(abs(y - 1180), 7)

    def test_a_missing_button_stays_missing(self):
        self.assertIsNone(runner.button_tap_point(None,
                                                  safe_tap.TapJitter()))


if __name__ == "__main__":
    unittest.main()
