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
