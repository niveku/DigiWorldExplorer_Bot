import itertools
import shutil
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

    def test_the_screen_that_stopped_the_loop_is_kept_as_an_image(self):
        # 2026-08-26: two runs died on "sin progreso visible" with clean
        # cycles behind them and nobody could say what was on screen,
        # because the game had moved on by the time anyone looked. The
        # second one froze on a screen that still scored as `battle`, so
        # saving the frame only for unrecognized screens was not enough.
        self.learn()
        frozen = BATTLE(9)
        code, _ = self.drive([CHALLENGE(4), CHALLENGE(5)] + [frozen] * 20,
                             ["run", "--loop", "trials", "--poll", "0"])
        self.assertEqual(code, 0)
        shots = sorted(Path("outputs").glob("*_trials/frame_al_parar.png"))
        self.assertTrue(shots)
        self.addCleanup(shots[-1].unlink)
        with Image.open(shots[-1]) as saved:
            self.assertEqual(saved.size, frozen.size)

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

    def test_adopt_session_closes_the_leftover_dialog_once(self):
        # The relaunch case: the previous process was killed on a reward
        # panel, so the screen that would open a run is behind it.
        self.learn()
        code, adb = self.drive([REWARD(7), REWARD(8), REWARD(9)],
                               ["run", "--loop", "trials", "--poll", "0",
                                "--adopt-session", "--max-frames", "3"])
        self.assertEqual(code, 0)
        self.assertTrue(adb.called)

    def test_a_run_writes_its_events(self):
        # The run folder is named "<stamp>_<loop>", and the stamp itself
        # contains an underscore, so anything looser than an exact suffix
        # match reaches other loops' folders: the first version of this
        # cleanup globbed "*_trials" and tried to delete the live
        # "*_sp_trials" log of a run that was going on at the time.
        def mine():
            return {path for path in Path("outputs").glob("*_trials")
                    if path.name.split("Z_", 1)[-1] == "trials"}

        before = mine()
        self.learn()
        self.drive(list(self.ROUND_TRIP),
                   ["run", "--loop", "trials", "--cycles", "1", "--poll", "0"])
        created = sorted(mine() - before)
        self.assertEqual(len(created), 1)
        log = created[0] / "events.jsonl"
        text = log.read_text(encoding="utf-8")
        # A stopped run also leaves frame_al_parar.png, so the directory
        # is cleared rather than assumed to hold exactly one file.
        shutil.rmtree(created[0])
        self.assertIn("challenge", text)
        self.assertIn("tap_xy", text)


if __name__ == "__main__":
    unittest.main()
