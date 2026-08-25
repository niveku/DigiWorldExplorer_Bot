import random
import unittest

import safe_tap


class PointTests(unittest.TestCase):
    def test_every_sample_stays_inside_the_promised_ellipse(self):
        rng = random.Random(7)
        for _ in range(2000):
            x, y = safe_tap.point(500, 600, 40, 25, rand=rng)
            # +1px of slack for the rounding to integer pixels.
            self.assertLessEqual(((x - 500) / 41.0) ** 2
                                 + ((y - 600) / 26.0) ** 2, 1.0)

    def test_a_rectangle_sampler_would_leave_the_promise(self):
        # The behaviour this port exists to fix: independent x/y sampling
        # reaches 1.41x the promised radius at the corners.
        rng = random.Random(7)
        worst = max(((rng.uniform(-40, 40) / 40.0) ** 2
                     + (rng.uniform(-25, 25) / 25.0) ** 2)
                    for _ in range(2000))
        self.assertGreater(worst, 1.0)

    def test_spreads_over_the_area_instead_of_hugging_the_centre(self):
        rng = random.Random(11)
        far = sum(1 for _ in range(2000)
                  if abs(safe_tap.point(0, 0, 100, 100, rand=rng)[0]) > 50)
        # Uniform over the area puts ~39% of samples beyond half the
        # radius on one axis; a naive linear radius would put ~25%.
        self.assertGreater(far, 600)

    def test_clamps_to_the_screen_and_returns_integers(self):
        rng = random.Random(3)
        for _ in range(200):
            x, y = safe_tap.point(5, 1275, 40, 40, bounds=(720, 1280),
                                  rand=rng)
            self.assertIsInstance(x, int)
            self.assertIsInstance(y, int)
            self.assertTrue(0 <= x <= 719 and 0 <= y <= 1279)

    def test_zero_radius_returns_the_exact_point(self):
        self.assertEqual(safe_tap.point(120, 340, 0, 0), (120, 340))

    def test_negative_radius_is_treated_as_no_variation(self):
        self.assertEqual(safe_tap.point(120, 340, -10, -10), (120, 340))


class DelayTests(unittest.TestCase):
    def test_varies_around_the_base_in_both_directions(self):
        rng = random.Random(5)
        values = [safe_tap.delay(1.0, .2, rng) for _ in range(500)]
        self.assertTrue(any(v < 1.0 for v in values))
        self.assertTrue(any(v > 1.0 for v in values))
        self.assertAlmostEqual(sum(values) / len(values), 1.0, delta=.03)

    def test_an_oversized_spread_can_never_produce_an_instant_tap(self):
        rng = random.Random(5)
        for _ in range(500):
            self.assertGreaterEqual(safe_tap.delay(.35, 5.0, rng),
                                    .35 * safe_tap.MIN_DELAY_FRACTION)

    def test_zero_base_stays_zero(self):
        self.assertEqual(safe_tap.delay(0, 5), 0.0)


class TapJitterTests(unittest.TestCase):
    def test_never_repeats_the_previous_point_on_the_same_target(self):
        jitter = safe_tap.TapJitter(random.Random(2))
        previous = None
        for _ in range(300):
            current = jitter.point("attempt", 400, 900, 30, 12)
            self.assertNotEqual(current, previous)
            previous = current

    def test_two_targets_keep_separate_histories(self):
        jitter = safe_tap.TapJitter(random.Random(2))
        first = jitter.point("a", 100, 100, 0, 0)
        second = jitter.point("b", 100, 100, 0, 0)
        # A zero radius has one legal point; different keys must not
        # resample each other away from it.
        self.assertEqual(first, second)

    def test_forget_clears_the_history(self):
        jitter = safe_tap.TapJitter(random.Random(2))
        jitter.point("a", 10, 10, 5, 5)
        jitter.forget("a")
        self.assertEqual(jitter._last, {})


if __name__ == "__main__":
    unittest.main()
