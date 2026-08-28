"""main() has to survive its own FIRST frame.

Why this exists: nothing in this suite had ever executed the runner's
main loop. It is the live ADB loop, so every test mocked around it, and
the 598 that passed said nothing about whether it runs at all. Twice now
that blind spot shipped a crash to the user's machine on the opening
frames:

- a NameError on a call left behind by a deletion (2026-08-2x, which is
  why test_no_dangling_calls exists), and
- `UnboundLocalError: cannot access local variable 'player'`, from a
  line placed forty lines above where `player` is resolved. From the
  second iteration on it would have read fine; the first one died
  (reported live 2026-08-28).

A static checker was tried for the second one and abandoned: proving
"bound on every path" needs real flow analysis, and the narrow version
accused correct code. Executing the loop proves it instead, and covers
every other way a frame can fail rather than one.

The device is replaced, not simulated: `screenshot` hands back a real
recorded board and `adb` swallows the taps. What is asserted is only
that frames go through and taps come out - the decisions themselves are
what the rest of the suite and the replay harness are for.
"""
import itertools
import os
import sys
import unittest
from unittest.mock import patch

from PIL import Image

import auto_digiworld_batch2 as runner
import digiworld_bot as bot

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def board_frame(name="fm_at_1_1"):
    with Image.open(os.path.join(FIXTURES, f"{name}.png")) as image:
        return image.convert("RGB")


class RunnerSmokeTests(unittest.TestCase):
    def drive(self, argv, frames):
        """Run main() over a scripted frame sequence with no real device."""
        with (patch.object(sys, "argv", ["auto_digiworld_batch2.py"] + argv),
              patch.object(bot, "resolve_adb", return_value="adb"),
              patch.object(bot, "resolve_serial", return_value="serial"),
              patch.object(runner.bot, "screenshot",
                           side_effect=itertools.cycle(frames)),
              patch.object(runner.bot, "adb", return_value="") as adb,
              patch.object(runner.time, "sleep")):
            code = runner.main()
        return code, adb

    def test_the_first_frame_does_not_crash(self):
        # The whole point: iteration ONE, where a local assigned later in
        # the loop is not bound yet. --steps 1 stops right after it.
        code, adb = self.drive(["--steps", "1"], [board_frame()])
        self.assertEqual(code, 0)
        # Not "it tapped" - one frame need not decide to act. Only that
        # the loop reached the device at all instead of dying first.
        self.assertTrue(adb.called)

    def test_several_frames_do_not_crash(self):
        # Iteration two onwards exercises the paths that DO carry state
        # across frames: the ledger, the belt, the barren memory.
        code, _ = self.drive(["--steps", "4"],
                             [board_frame("fm_at_1_1"),
                              board_frame("fm_at_3_1"),
                              board_frame("claw_board")])
        self.assertEqual(code, 0)

    def test_plan_only_reads_the_hud_without_tapping(self):
        code, adb = self.drive(["--steps", "10", "--plan-only"],
                               [board_frame()])
        self.assertEqual(code, 0)
        for call in adb.call_args_list:
            self.assertNotIn("tap", call.args, "--plan-only no debe tocar nada")


if __name__ == "__main__":
    unittest.main()
