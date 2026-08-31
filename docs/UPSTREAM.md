# What this fork changed

Fork traceability. Git history is the source of truth; this is the readable
summary.

- **Base**: [RobinTh0r/DigiWorldExplorer_Bot](https://github.com/RobinTh0r/DigiWorldExplorer_Bot),
  last commit by the original author `d7d8548` (2026-07-31).
- **This fork**: everything after it. Ask git rather than trusting a number
  written here:

  ```bash
  git remote add upstream https://github.com/RobinTh0r/DigiWorldExplorer_Bot.git
  git fetch upstream
  git rev-list --count upstream/main..HEAD   # how many commits
  git diff --stat upstream/main..HEAD        # how much they touched
  git log --oneline upstream/main..HEAD      # what they were
  ```

## Where the numbers live

Counts that change go in exactly one place, and this file is it. Anything
else that wants one links here instead of repeating it, because the same
count written into four documents drifts in four directions: on 2026-08-31
the test total read 638 in the README badge, 638 in the fork note, 520 in
CONTRIBUTING and 607 in an old changelog entry, all at once.

Two rules keep it that way:

- **A count git can answer is not written down.** Commit totals and diff
  stats are the commands above, not figures. A figure would be stale by the
  next commit.
- **A count inside a dated changelog entry stays.** "638 tests" under v0.4.0
  is a fact about that release, and history does not go out of date.

The one live figure stated here is the test total, and
`tests/test_docs_numbers.py` fails when it stops being true:

**673 tests** (`python -m unittest discover -s tests`), with fixtures cut
from real captures of the game.

## What already came from the original

Automatic detection of the visible 5x5 grid over ADB, exploration by
priority (oranges, items, right, pyramids, dash), safety stops on a doubtful
board or overlay, the Windows launchers (`INSTALL.cmd`, `START.cmd`,
`CHECK.cmd` and their `.ps1`), packaging with a local Python environment,
and the release scheme. That is the backbone, and RobinTh0r wrote it.

## What this fork built on top

**The paw receipt (`step_ledger.py`).** The piece that changed everything
else. The HUD paw counter is the authority on what the game charged: if it
did not charge, the tap never happened. The bot used to believe its own
taps, and nearly every desync came out of that faith. Order of authority:
receipt, then pixels, then guess.

**Conveyor physics.** The grid is fixed furniture; its contents move, and
they advance exactly one column when a CHARGED step carries the player from
column 1 to column 2. All world memory (remembered items, phantom
obstacles, vetoes, bans) shifts by that rule instead of by a pixel
heuristic.

**World model (`world_model.py`).** Cells stopped being re-judged every
frame. They are tracks with identity, classified by their ORIGIN at birth:
an item entering through the right edge is explained and believed on sight,
while anything born without an explanation (pickup confetti) stays a
suspect.

**Replay harness (`replay_harness.py`).** Every saved run becomes an
end-to-end regression test: it replays the real PNGs and audits the
invariants GHOST, PLAYER-LAW, STARVATION, BLIND-TOUR, PING-PONG, INDECISION
and BACKSTEP. That is what lets a planning defect be fixed and checked
against real footage.

**Planning on measured economy.** A tour over every pickup instead of panic
rescues; real prices (step 40 shards, garra 200, dash 400) and scroll
budgets so perishable items are not eroded; back-step vetoes backed by the
receipt.

**Adaptive pacing.** Waits between taps answer the device: a swallowed tap
stretches the rhythm, a clean frame relaxes it back to the measured floor.

**Test suite.** See the count above, with fixtures from real captures.

**Launcher.** A resource estimate before anything is touched (how many
paws, garras and dashes the planned run costs, and whether they are
enough), a Spanish interface, and the fix to the prompt that cancelled
whatever you answered.

## Work log

The `docs/review-*.md` files are the durable record: every defect found in a
live run, the evidence that proved it, the fix, and also what was tried and
**dropped with a measurement** (a row lock that caused a new deadlock, a
wait shortcut the telemetry showed was useless).
