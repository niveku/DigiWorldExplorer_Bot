import unittest

import overlays


def detector(queue):
    """A detector that reads its answers from a list, one per frame."""
    def detect(image, det=None):
        return queue.pop(0) if queue else None
    return detect


def kind(name, queue, priority=1, **extra):
    return overlays.OverlayKind(name=name, priority=priority,
                                detect=detector(queue),
                                points=extra.pop("points", ((.03, .5),
                                                            (.5, .865))),
                                **extra)


class ArbiterTests(unittest.TestCase):
    def test_a_clean_frame_belongs_to_the_explorer(self):
        arbiter = overlays.OverlayArbiter([kind("guide", [None])])
        decision = arbiter.observe(0.0, image=None, size=(720, 1280))
        self.assertEqual(decision.kind, "none")
        self.assertFalse(decision.owns_frame)

    def test_a_recognized_cover_takes_the_frame_and_gets_a_tap(self):
        arbiter = overlays.OverlayArbiter(
            [kind("guide", [{"stage_failed": True}])])
        decision = arbiter.observe(0.0, image=None, size=(720, 1280))
        self.assertEqual((decision.kind, decision.owner), ("dismiss", "guide"))
        self.assertTrue(decision.owns_frame)
        self.assertEqual(decision.point, (22, 640))
        self.assertEqual(decision.evidence, {"stage_failed": True})

    def test_the_second_attempt_uses_the_other_known_safe_point(self):
        arbiter = overlays.OverlayArbiter(
            [kind("guide", [{}, {}], cooldown=0.0)])
        first = arbiter.observe(0.0, None, size=(720, 1280))
        second = arbiter.observe(1.0, None, size=(720, 1280))
        self.assertNotEqual(first.point, second.point)
        self.assertEqual(second.point, (360, 1107))

    def test_attempts_respect_the_cooldown(self):
        arbiter = overlays.OverlayArbiter(
            [kind("guide", [{}, {}], cooldown=5.0)])
        self.assertEqual(arbiter.observe(0.0, None).kind, "dismiss")
        waited = arbiter.observe(1.0, None)
        self.assertEqual((waited.kind, waited.reason),
                         ("wait", "esperando entre intentos"))

    def test_gives_up_with_a_reason_after_the_attempt_budget(self):
        arbiter = overlays.OverlayArbiter(
            [kind("guide", [{}] * 4, cooldown=0.0, max_attempts=2)])
        arbiter.observe(0.0, None)
        arbiter.observe(1.0, None)
        decision = arbiter.observe(2.0, None)
        self.assertEqual(decision.kind, "stop")
        self.assertIn("2 intentos", decision.reason)

    def test_releases_the_frame_only_when_the_cover_is_gone(self):
        arbiter = overlays.OverlayArbiter(
            [kind("guide", [{}, {}, None], cooldown=0.0)])
        arbiter.observe(0.0, None)
        self.assertEqual(arbiter.owner, "guide")
        arbiter.observe(1.0, None)
        self.assertEqual(arbiter.owner, "guide")   # the tap proves nothing
        arbiter.observe(2.0, None)
        self.assertIsNone(arbiter.owner)
        self.assertEqual(arbiter.report(),
                         [{"overlay": "guide", "attempts": 2,
                           "resolved": True}])

    def test_priority_decides_when_two_covers_are_visible(self):
        arbiter = overlays.OverlayArbiter([
            kind("toast", [{}], priority=1),
            kind("guide", [{}], priority=9),
        ])
        self.assertEqual(arbiter.observe(0.0, None).owner, "guide")

    def test_a_new_cover_restarts_the_attempt_budget(self):
        arbiter = overlays.OverlayArbiter([
            kind("guide", [{}, None], priority=9, cooldown=0.0),
            kind("toast", [{}], priority=1, cooldown=0.0),
        ])
        arbiter.observe(0.0, None)
        decision = arbiter.observe(1.0, None)
        self.assertEqual((decision.owner, decision.attempt), ("toast", 1))
        self.assertEqual(arbiter.report(),
                         [{"overlay": "guide", "attempts": 1,
                           "resolved": False}])

    def test_a_cover_that_proves_the_world_stood_still_says_so(self):
        arbiter = overlays.OverlayArbiter(
            [kind("toast", [{}], freeze_reckoning=True)])
        self.assertTrue(arbiter.observe(0.0, None).freeze_reckoning)

    def test_a_cover_marked_untouchable_is_reported_but_never_tapped(self):
        arbiter = overlays.OverlayArbiter(
            [kind("cutscene", [{}], dismissable=False)])
        decision = arbiter.observe(0.0, None)
        self.assertEqual(decision.kind, "wait")
        self.assertIsNone(decision.point)
        self.assertTrue(decision.owns_frame)

    def test_without_a_screen_size_the_point_stays_normalized(self):
        arbiter = overlays.OverlayArbiter([kind("guide", [{}])])
        self.assertEqual(arbiter.observe(0.0, None).point, (.03, .5))


if __name__ == "__main__":
    unittest.main()
