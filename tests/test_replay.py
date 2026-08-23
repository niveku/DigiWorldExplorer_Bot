"""End-to-end regression: replay recorded runs through today's code.

Every unit test pins one function; these pin the SEAMS - the layer
interactions where all the 2026-08-22 field bugs lived (sensor
anchoring, TTL vs confetti, suspect starvation, phantom deadlocks).
Each recorded run in runs/ is a corpus of real frames; the harness
replays them with the current perception/memory/decision code and
asserts the invariants. A new field bug becomes a new recorded run
that must stay at zero violations forever.

Skipped automatically when no recorded runs are available (CI without
the runs corpus)."""
import os
import unittest

BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "runs")

# The 2026-08-22 corpus: the day of the layer-interaction regressions.
CORPUS = [
    "20260822T174628_436379Z",
    "20260822T175424_583117Z",
    "20260822T183056_829687Z",   # backsteps-for-nothing day
    "20260822T184638_555083Z",   # 'falló muchos drops' (TTL regression)
    "20260822T194747_257468Z",   # four-skip starvation, 2 lost energies
    "20260822T201927_294341Z",   # confetti-ghost circling (empty-previous
                                 # guard silenced the suspect detector)
    "20260822T205803_231886Z",   # energy lost to fixed ingestion band +
                                 # suspect-detour horseshoe walks
    "20260822T212332_788505Z",   # uncapped sliding wait deadlocked at
                                 # n=82 (47 straight waits)
    "20260822T215547_461705Z",   # explore garra bought over a free
                                 # step by the anti-reverse hysteresis
    "20260822T234822_139608Z",   # scrolled own forming wall off the
                                 # board + dash-ingested orange
                                 # strict-banded and lost
    "20260823T033159_051662Z",   # first run with the board rectangle
                                 # locked (StableBoard)
    "20260823T074036_943730Z",   # 'indecision, pasos estupidos hacia
                                 # atras': 36 of 186 frames in WAIT and a
                                 # run that ended alternating
                                 # (0,0)<->(0,1) over a dash orb walled
                                 # off from the player
    # (Two runs are deliberately NOT here, both recordings of a bug
    # fixed after they were taken. PING-PONG audits the positions the
    # RECORDED run actually stood on, which no fix can change, so they
    # can never reach zero. 20260823T143257_188677Z is the
    # orange-vs-dash-pair livelock, guarded now by ReverseStepVetoTests
    # in test_dash_wall; 20260823T150408_141217Z walked back to (3,1)
    # across a wall-stabilizing wait, guarded by BlockedDirectionTests
    # in test_pyramid_stats.)
    "20260823T142253_022914Z",   # first live run under the paw receipt:
                                 # the closing energy read lost to a
                                 # pickup animation
    "20260823T144136_225636Z",   # a paid claw detour the PING-PONG rule
                                 # read as waste: the pickup happened one
                                 # frame before the second stand
    "20260823T150728_355188Z",   # 80 actions, 79/79 taps charged, two
                                 # waits: the shape a clean run has
]


def _available():
    return [d for d in CORPUS
            if os.path.exists(os.path.join(BASE, d, "events.jsonl"))]


@unittest.skipUnless(_available(), "no recorded runs available")
class ReplayCorpusTests(unittest.TestCase):
    maxDiff = None

    def test_corpus_runs_have_zero_invariant_violations(self):
        import replay_harness
        failures = {}
        for name in _available():
            violations = replay_harness.replay_run(os.path.join(BASE, name))
            if violations:
                failures[name] = violations
        self.assertEqual(failures, {})


if __name__ == "__main__":
    unittest.main()
