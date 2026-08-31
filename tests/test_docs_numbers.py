"""The docs state a few live numbers. These tests keep them true.

On 2026-08-31 the test total was written in four places and read 638, 638,
520 and 607 at the same time, and the launcher printed a hard-coded ratio
that had been wrong for a week. The rule that came out of it: a count that
changes is written in ONE document, `docs/UPSTREAM.md`, and everything else
links there.

Anything git can answer (commit totals, diff stats) is not written down at
all, so there is nothing here to check for those. What stays stated is the
test total and the version, and both are checked against the thing they
describe rather than against each other.
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
UPSTREAM = ROOT / "docs" / "UPSTREAM.md"
READMES = (ROOT / "README.md", ROOT / "README.en.md")

#: Documents that must not restate a live count. A dated changelog entry is
#: exempt: "638 tests" under v0.4.0 is a fact about that release.
NO_COUNTS = (ROOT / "README.md", ROOT / "README.en.md",
             ROOT / "CONTRIBUTING.md", ROOT / "NOTICE.md")


def read(path):
    return path.read_text(encoding="utf-8")


def count_test_methods():
    """Every `def test_*` under tests/, which is what unittest will run."""
    total = 0
    for path in sorted(ROOT.joinpath("tests").glob("test_*.py")):
        total += len(re.findall(r"^\s+def (test_\w+)", read(path), re.M))
    return total


class TestTotalTests(unittest.TestCase):
    def test_upstream_states_the_real_total(self):
        stated = re.search(r"\*\*(\d+) tests\*\*", read(UPSTREAM))
        self.assertIsNotNone(
            stated, "docs/UPSTREAM.md no longer states a test total")
        self.assertEqual(
            int(stated.group(1)), count_test_methods(),
            "docs/UPSTREAM.md states a test total that is no longer true; "
            "it is the ONE place that number is written, so update it there")

    def test_no_other_document_restates_it(self):
        total = str(count_test_methods())
        for path in NO_COUNTS:
            self.assertNotIn(
                f"{total} tests", read(path),
                f"{path.name} restates the test total. It belongs in "
                "docs/UPSTREAM.md alone, because four copies drift in four "
                "directions")


class VersionBadgeTests(unittest.TestCase):
    def test_every_readme_badge_matches_the_VERSION_file(self):
        version = read(ROOT / "VERSION").strip()
        for path in READMES:
            badge = re.search(r"badge/version-([\d.]+)-", read(path))
            self.assertIsNotNone(badge, f"{path.name} has no version badge")
            self.assertEqual(
                badge.group(1), version,
                f"{path.name} badge says {badge.group(1)}, VERSION says "
                f"{version}")


class LanguageSwitcherTests(unittest.TestCase):
    """Two READMEs are two chances to publish one and forget the other."""

    def test_each_readme_points_at_the_other(self):
        self.assertIn("README.en.md", read(ROOT / "README.md"))
        self.assertIn("README.md", read(ROOT / "README.en.md"))

    def test_they_have_the_same_sections(self):
        # Not a translation check, which no test can do. This catches the
        # failure that actually happens: a section added to one README and
        # forgotten in the other.
        def sections(path):
            return [line.count("#")
                    for line in read(path).splitlines()
                    if re.match(r"^#{2,3} ", line)]
        self.assertEqual(
            sections(ROOT / "README.md"), sections(ROOT / "README.en.md"),
            "the two READMEs no longer have the same section structure; "
            "they are updated together")


if __name__ == "__main__":
    unittest.main()
