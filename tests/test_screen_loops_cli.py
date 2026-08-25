import itertools
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

import digiworld_bot as bot
import screen_loop
import screen_loops


def frame(base, panel, noise=None, size=(180, 320)):
    width, height = size
    array = np.zeros((height, width, 3), dtype=np.uint8)
    array[:, :] = base
    array[int(height * .75):int(height * .9),
          int(width * .3):int(width * .7)] = panel
    if noise is not None:
        rng = np.random.default_rng(noise)
        array[int(height * .1):int(height * .5)] = rng.integers(
            0, 255, (int(height * .5) - int(height * .1), width, 3),
            dtype=np.uint8)
    return Image.fromarray(array, "RGB")


def CHALLENGE(seed=1):
    return frame((20, 40, 90), (200, 200, 60), seed)


def REWARD(seed=1):
    return frame((10, 120, 170), (240, 240, 240), seed)


def BATTLE(seed=1):
    return frame((0, 90, 0), (0, 90, 0), seed)


class CliTests(unittest.TestCase):
    def setUp(self):
        self._folder = tempfile.TemporaryDirectory()
        root = Path(self._folder.name)
        patcher = patch.multiple(screen_loops, LOOPS_DIR=root,
                                 CAPTURES_DIR=root / "captures")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._folder.cleanup)
        self.root = root
        for state, maker in (("challenge", CHALLENGE), ("reward", REWARD)):
            folder = root / "captures" / "trials" / state
            folder.mkdir(parents=True)
            for seed in (1, 2, 3):
                maker(seed).save(folder / f"{seed}.png")

    def learn(self, *extra):
        return screen_loops.main([
            "learn", "--loop", "trials",
            "--tap", "challenge=115,250", "--tap", "reward=0.5,0.66",
            "--start", "challenge", "--cycle", "challenge",
            "--needs-session", "reward", *extra])

    def drive(self, frames, argv):
        """Run the CLI over a scripted frame sequence, one second apart."""
        with (patch.object(bot, "resolve_adb", return_value="adb"),
              patch.object(bot, "resolve_serial", return_value="serial"),
              patch.object(bot, "screenshot", side_effect=frames),
              patch.object(bot, "adb") as adb,
              patch("screen_loops.time.sleep"),
              patch("screen_loops.time.monotonic",
                    side_effect=itertools.count(0, 1.0))):
            code = screen_loops.main(argv)
        return code, adb

    # one full round trip: offer -> accepted -> run -> reward -> offer again
    ROUND_TRIP = [CHALLENGE(4), CHALLENGE(5), BATTLE(1), REWARD(4),
                  REWARD(5), BATTLE(2), CHALLENGE(6)]

    def test_learn_writes_a_profile_set_with_pixel_and_fraction_taps(self):
        self.assertEqual(self.learn(), 0)
        path = self.root / "trials.json"
        self.assertTrue(path.exists())
        profiles, states, policy = screen_loop.load_profiles(path)
        taps = {p.name: p.tap for p in profiles}
        self.assertAlmostEqual(taps["challenge"][0], 115 / 180, places=3)
        self.assertAlmostEqual(taps["reward"][1], .66, places=3)
        self.assertTrue(next(s for s in states
                             if s.name == "challenge").starts_session)
        self.assertTrue(next(s for s in states
                             if s.name == "reward").requires_session)
        self.assertEqual(policy.session_timeout, 300.0)

    def test_learn_without_captures_is_an_error(self):
        self.assertEqual(screen_loops.main(["learn", "--loop", "missing"]), 2)

    def test_watch_recognizes_the_cycle_and_never_taps(self):
        self.learn()
        code, adb = self.drive(list(self.ROUND_TRIP),
                               ["watch", "--loop", "trials", "--cycles", "1",
                                "--poll", "0"])
        self.assertEqual(code, 0)
        adb.assert_not_called()

    def test_run_taps_inside_the_declared_safe_radius(self):
        self.learn()
        code, adb = self.drive(list(self.ROUND_TRIP),
                               ["run", "--loop", "trials", "--cycles", "1",
                                "--poll", "0"])
        self.assertEqual(code, 0)
        taps = [tuple(int(value) for value in call.args[-2:])
                for call in adb.call_args_list]
        self.assertEqual(len(taps), 2, "una vuelta son dos taps")
        # The challenge tap goes to its own point (115, 250) and the
        # reward tap to its own (0.5, 0.66 of 180x320), each inside the
        # declared safe radius (2% / 1.2% of the screen).
        for (x, y), (want_x, want_y) in zip(taps, ((115, 250), (90, 211))):
            self.assertLessEqual(abs(x - want_x), .02 * 180 + 1)
            self.assertLessEqual(abs(y - want_y), .012 * 320 + 1)

    def test_the_reward_screen_is_only_tapped_inside_our_own_run(self):
        self.learn()
        # The reward screen arrives without this loop ever opening a run:
        # a leftover dialog from something the player did.
        code, adb = self.drive([REWARD(7), REWARD(8), REWARD(9)],
                               ["run", "--loop", "trials", "--poll", "0",
                                "--max-frames", "3"])
        self.assertEqual(code, 0)
        adb.assert_not_called()

    def test_a_run_writes_its_events(self):
        self.learn()
        self.drive(list(self.ROUND_TRIP),
                   ["run", "--loop", "trials", "--cycles", "1", "--poll", "0"])
        logs = sorted(Path("outputs").glob("*_trials/events.jsonl"))
        self.assertTrue(logs)
        text = logs[-1].read_text(encoding="utf-8")
        for path in logs:
            path.unlink()
            path.parent.rmdir()
        self.assertIn("challenge", text)
        self.assertIn("tap_xy", text)


if __name__ == "__main__":
    unittest.main()
