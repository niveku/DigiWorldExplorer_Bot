"""Replay harness: run TODAY's perception/memory/decision code against
RECORDED runs (debug PNGs + events.jsonl) and check end-to-end
invariants that unit tests cannot see.

Why it exists (user mandate 2026-08-22, after three layer-interaction
regressions in one day): every recent field bug - the sprite anchoring
the scroll sensor, the TTL that killed covered real items, the
suspect-vs-memory tap starvation - passed every unit test, because each
lived in the seams BETWEEN layers. This harness replays the seams.

How it works (open-loop replay):
- The recorded frames and the recorded ACTIONS drive the world: state
  that depends on what was actually sent (scroll shifts, expected
  player, pickups popping memory) follows the log, so the belief
  pipeline sees exactly what the live run saw.
- The perception/memory pipeline is TODAY's code, called through the
  real helpers in the runner in main()'s order.
- choose() is evaluated each frame as a PROBE (what would today's brain
  do here) - its result is checked, not applied.

Invariants (each one is a bug class we shipped and fixed):
  GHOST      remembered left-band item whose cell reads clean-empty 4+
             consecutive frames (decay must kill at 3 - firing means a
             decay regression).
  PLAYER-LAW resolved player beyond column 1.
  STARVATION choose() proposes a move the tap gate itself would refuse
             (decision/guard contradiction - the four-skip starvation).
  BLIND-TOUR choose() says 'explore' while a non-suspect orange is
             known (detected or remembered) on the board.

Usage:
    python replay_harness.py runs/20260822T194747_257468Z [more runs]
    python replay_harness.py --all-recent 5
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys

from PIL import Image

import auto_digiworld as strategy
import auto_digiworld_batch2 as runner
import digiworld_bot as bot


def load_run(run_dir):
    """Return (frames, actions_by_n): PNGs in shot order + logged acts."""
    with open(os.path.join(run_dir, "events.jsonl"), encoding="utf-8") as fh:
        events = [json.loads(line) for line in fh]
    actions = {}
    for e in events:
        n = e.get("next_index")
        a = e.get("action")
        if n is None or isinstance(a, str) or a is None:
            continue
        acts = a if isinstance(a, list) else [a]
        actions[n] = [m for m in acts if isinstance(m, dict)]
    frames = []
    for path in sorted(glob.glob(os.path.join(run_dir, "debug_*.png"))):
        m = re.match(r"debug_(\d+)_", os.path.basename(path))
        if m:
            frames.append((int(m.group(1)), path))
    return frames, actions


class Replay:
    def __init__(self):
        self.remembered = {}
        self.mem_misses = {}
        self.phantoms = {}
        self.pending_reveals = {}
        self.recent_pickups = []
        self.prev_item_cells = None
        self.prev_fresh = set()
        self.prev_suspects = set()
        self.sticky_ages = {}
        self.prev_strip = None
        self.slide_waits = 0
        self.expected_player = None
        self.prev_action = None
        self.prev_attack_target = None
        self.prev_dash_player = None
        self.last_player = None
        self.claimed = 0
        self.done = 0
        self.ghost_streaks = {}
        self.unseen_streaks = {}
        self.unseen_last_n = {}
        self.violations = []
        self.debug_n = None

    def flag(self, n, kind, detail):
        self.violations.append((n, kind, detail))

    def shift_left(self, times=1):
        for _ in range(times):
            self.remembered = runner.shift_items_left(self.remembered)
            self.mem_misses = runner.shift_items_left(self.mem_misses)
            self.phantoms = runner.shift_items_left(self.phantoms)
            self.pending_reveals = runner.shift_items_left(self.pending_reveals)
            self.recent_pickups = runner.shift_pickup_log_left(self.recent_pickups)
            self.ghost_streaks = runner.shift_items_left(self.ghost_streaks)
            self.unseen_streaks = runner.shift_items_left(self.unseen_streaks)
            self.unseen_last_n = runner.shift_items_left(self.unseen_last_n)

    def process_frame(self, n, path):
        img = Image.open(path).convert("RGB")
        det = bot.classify(img)
        if det.state != "digiworld" or det.board is None:
            return
        info = strategy.cells(img, det.board)
        player, score, source = runner.resolve_player(info, self.expected_player)
        large = strategy.find_large_player(
            img, det.board,
            item_cells={c for c, v in info.items() if v["item"] > .06})
        player, score, source = runner.veto_with_blob(player, score, source, large)
        if player is None or (source == "vision" and score < .08):
            return
        if player[1] > 1:
            self.flag(n, "PLAYER-LAW", f"player resolved at {player}")
            return
        self.last_player = tuple(player)
        detected = dict(info)

        # pixel scroll reconciliation (grace collapsed: offline frames
        # already embody whatever landed late)
        strip = runner.board_strip(img, det.board)
        measured, sliding = runner.measure_scroll_px(self.prev_strip, strip,
                                                     max_cols=2)
        if runner.should_wait_for_slide(sliding, self.slide_waits):
            self.slide_waits += 1
            return
        if sliding:
            measured = None
        self.slide_waits = 0
        self.prev_strip = strip
        if measured is not None and self.claimed <= 2 and measured != self.claimed:
            delta = self.claimed - measured
            if delta > 0:
                for _ in range(delta):
                    self.remembered = runner.shift_items_right(self.remembered)
                    self.mem_misses = runner.shift_items_right(self.mem_misses)
                    self.phantoms = runner.shift_items_right(self.phantoms)
                    self.pending_reveals = runner.shift_items_right(
                        self.pending_reveals)
                    self.ghost_streaks = runner.shift_items_right(
                        self.ghost_streaks)
                    self.unseen_streaks = runner.shift_items_right(
                        self.unseen_streaks)
                    self.unseen_last_n = runner.shift_items_right(
                        self.unseen_last_n)
            else:
                self.shift_left(-delta)
            self.claimed = measured

        self.phantoms.pop(tuple(player), None)
        self.remembered.pop(tuple(player), None)
        self.mem_misses.pop(tuple(player), None)
        for cell in set(self.remembered) & set(self.phantoms):
            self.remembered.pop(cell, None)
            self.phantoms.pop(cell, None)
            self.mem_misses.pop(cell, None)
        for cell in [c for c in self.remembered
                     if strategy.is_obstacle(detected[c])]:
            self.remembered.pop(cell, None)
            self.mem_misses.pop(cell, None)
        self.phantoms = {c: e for c, e in self.phantoms.items() if e > self.done}
        merged = runner.merge_remembered_items(info, self.remembered, player)
        merged = runner.merge_phantom_obstacles(merged, self.phantoms, self.done)

        current = runner.item_cells_of(merged)
        fresh = runner.suspect_appearances(
            current, self.prev_item_cells, shift=self.claimed,
            attack_cell=(self.prev_attack_target
                         if self.prev_action == "attack" else None),
            revealed_cells=runner.live_reveal_cells(self.pending_reveals,
                                                    self.done),
            confetti_risk=(self.prev_action == "dash"
                           or any(self.done - when < 2
                                  for _, when in self.recent_pickups)),
            confetti_rows=runner.confetti_rows_of(
                self.prev_dash_player if self.prev_action == "dash" else None,
                self.recent_pickups, self.done))
        suspects = runner.combined_suspects(fresh, self.prev_fresh, current,
                                            shift=self.claimed)
        suspects = runner.drop_remembered_suspects(suspects, self.remembered)
        suspects |= runner.burst_holds(self.prev_fresh, current,
                                       self.recent_pickups, self.done,
                                       shift=self.claimed)
        shifted_prev = {(r, c - self.claimed) for r, c in self.prev_suspects
                        if c - self.claimed >= 0}
        shifted_ages = {(r, c - self.claimed): v
                        for (r, c), v in self.sticky_ages.items()
                        if c - self.claimed >= 0}
        held, self.sticky_ages = runner.sticky_left_band_suspects(
            shifted_prev, current, shifted_ages)
        suspects |= held
        suspects = runner.drop_remembered_suspects(suspects, self.remembered)
        self.prev_suspects = set(suspects)
        self.prev_fresh = fresh
        self.prev_item_cells = current
        self.claimed = 0

        self.remembered = runner.remember_confirmed_items(
            self.remembered, detected, player, suspects, self.done)
        self.remembered = runner.drop_shift_ghosts(self.remembered, detected)
        self.remembered, self.mem_misses = runner.decay_unseen_left_band(
            self.remembered, self.mem_misses,
            runner.item_cells_of(detected), suspects, player)
        self.remembered = runner.prune_remembered_items(
            self.remembered, self.done, player)

        # ---- invariants ----
        detected_cells = runner.item_cells_of(detected)
        # Hard cap, any column, near-player included: a remembered item
        # vision has not confirmed for 6 straight frames is a ghost.
        # The player-adjacency exemption below is legitimate for
        # pickups in progress, but run 20260822T201927 showed a bot
        # CIRCLING its own confetti ghost - always adjacent, so the
        # clean-miss decay never counted and the soft invariant never
        # fired. Real items stay detected; confetti cover is suspect
        # (excluded); nothing legitimate hides for 6 frames.
        for cell in set(self.unseen_streaks) - set(self.remembered):
            self.unseen_streaks.pop(cell, None)
            self.unseen_last_n.pop(cell, None)
        for cell in list(self.remembered):
            # Same-row +-2-column detection is a scroll-desync SHADOW,
            # not a ghost: an item only ever moves by column (scroll),
            # so open-loop replay over skipped frames (run
            # 20260822T194747 n=16-17 were never saved - board in
            # motion) can leave memory up to two columns off a REAL
            # item. A confetti ghost has no physical counterpart on
            # its row.
            shadow = any((cell[0], cell[1] + dc) in detected_cells
                         for dc in (-2, -1, 1, 2))
            unseen = (cell not in detected_cells and cell not in suspects
                      and not shadow)
            if not unseen:
                self.unseen_streaks[cell] = 0
                continue
            # One count per GAME index: the runner saves several PNGs
            # under one index while it waits/rescans (n=20 of run
            # 20260822T194747 has five), and a frozen board must not
            # age the streak five times.
            if self.unseen_last_n.get(cell) == n:
                continue
            self.unseen_last_n[cell] = n
            streak = self.unseen_streaks.get(cell, 0) + 1
            self.unseen_streaks[cell] = streak
            if streak >= 6:
                self.flag(n, "GHOST",
                          f"remembered {self.remembered[cell][0]} at {cell} "
                          f"undetected {streak} straight frames")
        for cell in list(self.remembered):
            if cell[1] > 2:
                self.ghost_streaks.pop(cell, None)
                continue
            near = (abs(cell[0] - player[0]) <= 1
                    and abs(cell[1] - player[1]) <= 1)
            clean = (cell not in detected_cells and cell not in suspects
                     and not near)
            streak = self.ghost_streaks.get(cell, 0) + 1 if clean else 0
            self.ghost_streaks[cell] = streak
            if streak >= 4:
                self.flag(n, "GHOST",
                          f"remembered {self.remembered[cell][0]} at {cell} "
                          f"clean-empty {streak} frames")

        action, reason = strategy.choose(
            merged, ignored_targets=set(suspects), player=player,
            suspect_cells=suspects)
        if self.debug_n == n:
            print(f"[debug n={n}] player={player} suspects={sorted(suspects)}")
            print(f"  remembered={self.remembered}")
            print(f"  choose -> {action} / {reason}")
            for c, v in sorted(merged.items()):
                if v["item"] > .06 or v.get("claw", 0) > .10:
                    print(f"  item cell {c}: item={v['item']:.3f} "
                          f"type={strategy.pickup_type(v)} "
                          f"suspect={c in suspects}")
        if action is not None and action[0] == "move":
            target = tuple(action[1])
            if runner.unsafe_move_tap(merged, target, suspects,
                                      self.remembered):
                self.flag(n, "STARVATION",
                          f"choose() proposes move to {target} that the tap "
                          f"gate refuses (reason: {reason})")
        if str(reason).startswith("explore"):
            # The player's own cell is excluded: the pickup card drawn
            # over the sprite scores as a non-suspect orange there.
            known = [c for c, v in detected.items()
                     if strategy.pickup_type(v) == "orange"
                     and c not in suspects and c != tuple(player)]
            known += [c for c, (cat, _) in self.remembered.items()
                      if cat == "orange" and c != tuple(player)]
            if known:
                self.flag(n, "BLIND-TOUR",
                          f"explore while oranges known at {sorted(set(known))}")

        self.done += 1

    def apply_recorded(self, n, acts):
        for m in acts:
            kind = m.get("type")
            target = tuple(m.get("target_cell") or ())
            if kind == "move":
                self.remembered.pop(target, None)
                self.prev_action = "move"
                # A recorded move onto a visible item is a pickup: it
                # feeds burst_holds and the confetti_risk window just
                # like the live runner's pickup log.
                if (self.prev_item_cells
                        and target in self.prev_item_cells):
                    self.recent_pickups.append((target, self.done))
                if len(target) == 2 and target[1] >= 2:
                    self.shift_left(1)
                    self.claimed += 1
            elif kind == "attack":
                self.prev_action = "attack"
                self.prev_attack_target = target if target else None
                if target:
                    self.pending_reveals = runner.remember_pending_reveals(
                        self.pending_reveals, [target], self.done)
            elif kind == "dash":
                self.prev_action = "dash"
                self.prev_dash_player = self.last_player
                # The launch column IS known offline (the frame before
                # the dash resolved the player), and a dash scrolls
                # launch_col + 2: hardcoding 3 manufactured exactly the
                # desyncs the harness exists to audit for col-0
                # launches (review 2026-08-22).
                shift = (runner.dash_scroll_count(self.last_player[1])
                         if self.last_player else 3)
                self.shift_left(shift)
                self.claimed += shift


def replay_run(run_dir, debug_n=None):
    frames, actions = load_run(run_dir)
    rep = Replay()
    rep.debug_n = debug_n
    seen_n = None
    for idx, (n, path) in enumerate(frames):
        rep.process_frame(n, path)
        last_of_n = idx + 1 >= len(frames) or frames[idx + 1][0] != n
        if last_of_n and n in actions:
            rep.apply_recorded(n, actions[n])
    return rep.violations


def main(argv):
    targets = []
    if argv and argv[0] == "--all-recent":
        count = int(argv[1]) if len(argv) > 1 else 5
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "runs")
        dirs = sorted(d for d in os.listdir(base) if d.startswith("2026"))
        targets = [os.path.join(base, d) for d in dirs[-count:]]
    else:
        targets = argv
    total = 0
    for run_dir in targets:
        try:
            violations = replay_run(run_dir)
        except FileNotFoundError as exc:
            print(f"{os.path.basename(run_dir)}: sin datos ({exc})")
            continue
        total += len(violations)
        print(f"{os.path.basename(run_dir)}: {len(violations)} violaciones")
        for n, kind, detail in violations:
            print(f"  n={n:3d} {kind:10s} {detail}")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
