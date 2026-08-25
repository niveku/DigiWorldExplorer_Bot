import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

import screen_loop


def frame(base=(20, 40, 90), panel=(200, 200, 60), battle=None, size=(180, 320)):
    """A crude 'screen': background, a panel band, an optional noisy area."""
    width, height = size
    array = np.zeros((height, width, 3), dtype=np.uint8)
    array[:, :] = base
    array[int(height * .75):int(height * .9),
          int(width * .3):int(width * .7)] = panel
    if battle is not None:
        rng = np.random.default_rng(battle)
        array[int(height * .1):int(height * .6)] = rng.integers(
            0, 255, (int(height * .6) - int(height * .1), width, 3),
            dtype=np.uint8)
    return Image.fromarray(array, "RGB")


def grid(image):
    return screen_loop.downsample(image)


class DownsampleTests(unittest.TestCase):
    def test_cell_holds_the_mean_of_its_area_not_one_pixel(self):
        array = np.zeros((16, 12, 3), dtype=np.uint8)
        array[0, 0] = (255, 255, 255)
        image = Image.fromarray(array, "RGB")
        cell = screen_loop.downsample(image, cols=12, rows=16)[0, 0]
        self.assertTrue(np.allclose(cell, (255, 255, 255)))

    def test_shape_follows_the_requested_grid(self):
        self.assertEqual(grid(frame()).shape, (screen_loop.FINGERPRINT_ROWS,
                                               screen_loop.FINGERPRINT_COLS, 3))


class ProfileTests(unittest.TestCase):
    def test_recognizes_the_same_screen_and_rejects_another_one(self):
        profile = screen_loop.ScreenProfile.learn(
            "challenge", [grid(frame(battle=s)) for s in (1, 2, 3)])
        self.assertTrue(profile.matches(grid(frame(battle=9))))
        other = frame(base=(150, 30, 30), panel=(30, 30, 30), battle=9)
        self.assertFalse(profile.matches(grid(other)))

    def test_the_animated_area_does_not_decide(self):
        # Same panel and frame, a completely different battle picture.
        # The spread weighting is what keeps this a match; an unweighted
        # mean distance would put it far outside any usable threshold.
        grids = [grid(frame(battle=s)) for s in (1, 2, 3)]
        profile = screen_loop.ScreenProfile.learn("challenge", grids)
        far = grid(frame(battle=99))
        mean, spread = profile.arrays()
        unweighted = float(np.abs(far - mean).mean() / 255.0)
        self.assertLess(profile.distance(far), unweighted)
        self.assertTrue(profile.matches(far))

    def test_threshold_is_derived_from_the_captures(self):
        grids = [grid(frame(battle=s)) for s in (1, 2, 3)]
        profile = screen_loop.ScreenProfile.learn("challenge", grids)
        worst = max(profile.distance(g) for g in grids)
        self.assertAlmostEqual(profile.threshold,
                               max(screen_loop.MIN_THRESHOLD,
                                   worst * screen_loop.THRESHOLD_MARGIN),
                               places=6)

    def test_a_profile_needs_at_least_one_capture(self):
        with self.assertRaises(ValueError):
            screen_loop.ScreenProfile.learn("empty", [])

    def test_survives_a_round_trip_through_json(self):
        profile = screen_loop.ScreenProfile.learn(
            "challenge", [grid(frame(battle=1))], tap=(.64, .78))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "profiles.json"
            screen_loop.save_profiles(
                path, [profile],
                [screen_loop.StateSpec("challenge")],
                screen_loop.LoopPolicy(max_cycles=3))
            profiles, states, policy = screen_loop.load_profiles(path)
        self.assertEqual(profiles[0].tap, (.64, .78))
        self.assertTrue(profiles[0].matches(grid(frame(battle=2))))
        self.assertEqual(states[0].name, "challenge")
        self.assertEqual(policy.max_cycles, 3)
        self.assertTrue(json.loads(json.dumps(profile.mean)))


class HashTests(unittest.TestCase):
    def test_an_unchanged_frame_is_not_progress(self):
        value = screen_loop.frame_hash(frame(battle=1))
        self.assertFalse(screen_loop.hash_changed(value, value))

    def test_a_new_scene_is_progress(self):
        first = screen_loop.frame_hash(frame(battle=1))
        second = screen_loop.frame_hash(frame(base=(200, 30, 30),
                                              panel=(10, 10, 10)))
        self.assertTrue(screen_loop.hash_changed(first, second))

    def test_the_first_frame_always_counts_as_progress(self):
        self.assertTrue(screen_loop.hash_changed(None, 0))


def runner(**policy):
    profiles = [
        screen_loop.ScreenProfile.learn("challenge", [grid(frame(battle=1))],
                                        tap=(.64, .78)),
        screen_loop.ScreenProfile.learn(
            "reward", [grid(frame(base=(10, 90, 160), panel=(240, 240, 240)))],
            tap=(.50, .66)),
        screen_loop.ScreenProfile.learn(
            "unaffordable", [grid(frame(base=(120, 20, 20), panel=(255, 0, 0)))]),
    ]
    states = [
        screen_loop.StateSpec("challenge", taps_max=2, settle=.3, retry=1.0,
                              starts_session=True, counts_cycle=True),
        screen_loop.StateSpec("reward", taps_max=2, settle=.3, retry=1.0,
                              requires_session=True),
        screen_loop.StateSpec("unaffordable", action="stop",
                              stop_reason="coste en rojo"),
    ]
    return screen_loop.LoopRunner(profiles, states,
                                  screen_loop.LoopPolicy(**policy))


class RunnerTests(unittest.TestCase):
    def test_waits_for_the_screen_to_settle_before_the_first_tap(self):
        loop = runner()
        self.assertEqual(loop.decide(0.0, "challenge").kind, "wait")
        self.assertEqual(loop.decide(0.5, "challenge").kind, "tap")

    def test_caps_the_taps_per_visit_to_one_screen(self):
        loop = runner()
        loop.decide(0.0, "challenge")
        self.assertEqual(loop.decide(0.5, "challenge").kind, "tap")
        self.assertEqual(loop.decide(1.6, "challenge").kind, "tap")
        self.assertEqual(loop.decide(3.0, "challenge").kind, "wait")
        self.assertEqual(loop.decide(9.0, "challenge").reason,
                         "tope de taps en esta pantalla")

    def test_a_new_visit_to_the_same_screen_gets_a_fresh_budget(self):
        loop = runner()
        loop.decide(0.0, "challenge")
        loop.decide(0.5, "challenge")
        loop.decide(1.6, "challenge")
        loop.decide(2.0, None)               # battle
        loop.decide(20.0, "challenge")       # the screen is back
        self.assertEqual(loop.decide(20.5, "challenge").kind, "tap")

    def test_the_tap_point_comes_from_the_profile(self):
        loop = runner()
        loop.decide(0.0, "challenge")
        self.assertEqual(loop.decide(0.5, "challenge").tap, (.64, .78))

    def test_never_acts_on_a_screen_this_loop_did_not_open(self):
        loop = runner()
        decision = loop.decide(1.0, "reward")
        self.assertEqual(decision.kind, "wait")
        self.assertEqual(decision.reason, "sin sesion propia")

    def test_adopts_one_leftover_run_when_asked_to(self):
        # Regression: relaunching while the game sat on the reward screen
        # deadlocked on "sin sesion propia" forever, because the screen
        # that starts a session is behind the one nobody may close.
        loop = runner(adopt_session=True)
        self.assertEqual(loop.decide(1.0, "reward").reason,
                         "asentando la pantalla")
        self.assertEqual(loop.decide(1.5, "reward").kind, "tap")

    def test_the_adoption_is_spent_after_the_first_run(self):
        loop = runner(adopt_session=True)
        loop.decide(1.0, "reward")
        loop.decide(1.5, "reward")           # adopted
        loop.decide(2.0, None, changed=True)
        loop.decide(3.0, "challenge")        # our own run starts
        loop.decide(3.5, "challenge")
        loop.decide(4.0, None, changed=True)
        loop.session_active = False          # the run ended elsewhere
        loop.decide(5.0, "reward")
        decision = loop.decide(5.5, "reward")
        self.assertEqual((decision.kind, decision.reason),
                         ("wait", "sin sesion propia"))

    def test_without_the_flag_a_leftover_screen_is_still_untouchable(self):
        loop = runner()
        self.assertEqual(loop.decide(1.0, "reward").reason, "sin sesion propia")
        self.assertEqual(loop.decide(1.5, "reward").reason, "sin sesion propia")

    def test_acts_on_the_reward_once_the_session_is_ours(self):
        loop = runner()
        loop.decide(0.0, "challenge")
        loop.decide(0.5, "challenge")
        loop.decide(3.0, None)
        loop.decide(6.0, "reward")
        self.assertEqual(loop.decide(6.5, "reward").kind, "tap")

    def test_a_stop_screen_ends_the_loop(self):
        loop = runner()
        decision = loop.decide(1.0, "unaffordable")
        self.assertEqual((decision.kind, decision.reason),
                         ("stop", "coste en rojo"))

    def test_stops_when_nothing_moves_for_the_inactivity_timeout(self):
        loop = runner(inactivity_timeout=5.0)
        loop.decide(0.0, "challenge", changed=True)
        loop.decide(0.5, "challenge", changed=False)
        decision = loop.decide(6.0, "challenge", changed=False)
        self.assertEqual((decision.kind, decision.reason),
                         ("stop", "sin progreso visible"))

    def test_a_moving_frame_keeps_the_inactivity_clock_alive(self):
        loop = runner(inactivity_timeout=5.0)
        loop.decide(0.0, "challenge", changed=True)
        loop.decide(4.0, None, changed=True)
        self.assertEqual(loop.decide(8.0, None, changed=True).kind, "wait")

    def test_stops_when_the_session_runs_long(self):
        loop = runner(session_timeout=10.0)
        loop.decide(0.0, "challenge")
        decision = loop.decide(11.0, None, changed=True)
        self.assertEqual(decision.reason, "timeout de sesion")

    def test_the_first_sight_of_the_offer_is_not_a_completed_cycle(self):
        loop = runner(max_cycles=1)
        loop.decide(0.0, "challenge")
        self.assertEqual(loop.cycles, 0)
        self.assertEqual(loop.decide(0.5, "challenge").kind, "tap")

    def test_the_session_clock_restarts_with_every_run(self):
        # Regression: the live dungeon loop stopped at 5:01 with 13 clean
        # cycles behind it because the session clock was set on the first
        # run and never again, turning a per-run guard into a global cap.
        loop = runner(session_timeout=10.0)
        now = 0.0
        for _ in range(6):
            loop.decide(now, "challenge")
            loop.decide(now + .5, "challenge")
            loop.decide(now + 3.0, None, changed=True)
            now += 8.0
        decision = loop.decide(now, "challenge")
        self.assertNotEqual(decision.reason, "timeout de sesion")
        self.assertGreaterEqual(loop.cycles, 5)

    def test_a_run_that_never_comes_back_still_times_out(self):
        loop = runner(session_timeout=10.0)
        loop.decide(0.0, "challenge")
        loop.decide(0.5, "challenge")
        decision = loop.decide(30.0, None, changed=True)
        self.assertEqual(decision.reason, "timeout de sesion")

    def test_counts_completed_cycles_and_stops_on_the_budget(self):
        loop = runner(max_cycles=1)
        loop.decide(0.0, "challenge")        # the offer
        loop.decide(0.5, "challenge")        # accepted
        loop.decide(5.0, None)               # the run
        decision = loop.decide(20.0, "challenge")   # back at the offer
        self.assertEqual(loop.cycles, 1)
        self.assertEqual((decision.kind, decision.reason),
                         ("stop", "presupuesto de vueltas agotado"))

    def test_taps_that_change_nothing_back_off_and_then_stop(self):
        loop = runner(ineffective_taps_backoff=2, ineffective_taps_stop=3)
        loop.decide(0.0, "challenge", changed=True)
        loop.decide(0.5, "challenge", changed=False)      # tap 1
        loop.decide(2.0, "challenge", changed=False)      # tap 2, 1 wasted
        self.assertEqual(loop.ineffective_taps, 1)
        loop.decide(5.0, "challenge", changed=False)      # capped, counts
        self.assertGreaterEqual(loop.backoff, 1.0)
        decision = loop.decide(30.0, "challenge", changed=False)
        self.assertEqual(decision.kind, "stop")

    def test_a_screen_that_disappears_clears_the_wasted_tap_count(self):
        loop = runner(ineffective_taps_backoff=2, ineffective_taps_stop=3)
        loop.decide(0.0, "challenge", changed=True)
        loop.decide(0.5, "challenge", changed=False)
        loop.decide(2.0, "challenge", changed=False)
        self.assertEqual(loop.ineffective_taps, 1)
        loop.decide(3.0, None, changed=True)
        self.assertEqual(loop.ineffective_taps, 0)
        self.assertEqual(loop.backoff, 1.0)

    def test_observe_classifies_a_real_frame(self):
        loop = runner()
        image = frame(battle=4)
        decision = loop.observe(0.0, grid(image),
                                screen_loop.frame_hash(image))
        self.assertEqual(decision.state, "challenge")

    def test_an_unknown_screen_only_waits(self):
        loop = runner()
        decision = loop.observe(
            0.0, grid(frame(base=(0, 128, 0), panel=(0, 128, 0))))
        self.assertEqual((decision.kind, decision.state), ("wait", None))


if __name__ == "__main__":
    unittest.main()
