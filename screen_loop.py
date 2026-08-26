#!/usr/bin/env python3
"""A generic screen-state loop: recognize a screen, tap it, prove it moved.

This is the machinery the repeatable dungeons need (VS. Dungeon, Network
Defense Ops, summon screens). The shape comes from the Android companion
(`dungeon/`, `network/`, `purchase/` in RobinTh0r's
`DigiWorldExplorer_Android_Bot`): a small state machine over screens that
are recognized by layout instead of by translated text, with a hard cap on
taps per screen and a stop when nothing on screen changes any more.

Three things are done differently here, and the differences are the point:

**The profile is measured, not written by hand.** Their detector carries
hand-tuned colour ratios plus a 12x16 grid of hard-coded RGB values, one
point-sampled pixel per cell. Sampling a single pixel makes one sprite or
one compression artifact flip a cell, so the thresholds have to be loose,
and a loose threshold is what makes a bot tap the wrong dialog. Here a
profile is *learned* from captures of that screen (`ScreenProfile.learn`):
each cell keeps the mean over the whole cell area and the spread that cell
showed across the captures, and the distance is weighted by that spread.
Cells that animate (the battle itself, a spinning reward) weigh almost
nothing; the frame, the panel and the buttons - the parts that make the
screen that screen - carry the decision. The accept threshold is derived
from the captures too, so it is a measurement, not a guess.

**Nothing is believed until the screen proves it.** A dispatched tap is
not progress. This is the same law the step ledger enforces for movement:
the receipt outranks the intention. Here the receipt is the screen itself
- the state advances when the recognized screen *stops* being recognized,
and taps that change nothing are counted, back off and finally stop.

**A run costs something, so the budget is explicit.** These loops spend
tickets, stamina and stones. The runner stops on a cycle budget, on a
session timeout, on a screen the profile set marks as a stop (an
unaffordable cost lit up in red), and on silence.

The module is pure: it decides, it never touches ADB or the clock. The
runner CLI passes frames in and executes what comes out, which is also
what makes the whole thing testable without an emulator.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

import numpy as np

# Fingerprint resolution. 12x16 matches the Android original's grid; it is
# coarse enough to survive scaling between 720x1280 and a phone, fine
# enough that a panel, its title bar and its buttons occupy different
# cells.
FINGERPRINT_COLS = 12
FINGERPRINT_ROWS = 16
# Progress hash resolution, and how many of its 64 bits must flip before
# the screen counts as "something happened". Both from the Android
# original (8x8, 5 bits) - measured there, kept here as a starting point
# and adjustable per loop.
HASH_SIDE = 8
HASH_MIN_BITS = 5
# A cell that never varied across the captures would divide by zero and
# would also be suspiciously perfect; this floor keeps the weights finite.
MIN_SPREAD = 4.0
# The learned threshold is the worst calibration frame plus this margin.
# 1.6 was chosen so a screen recorded on three captures still admits a
# fourth with ordinary animation noise, while a different dialog - which
# in practice sits 3-10x further away - stays out.
THRESHOLD_MARGIN = 1.6
MIN_THRESHOLD = .02


def downsample(image, cols=FINGERPRINT_COLS, rows=FINGERPRINT_ROWS):
    """Mean RGB per grid cell, shape (rows, cols, 3), float.

    The mean over the cell area is what makes this robust where the
    original's centre-pixel sample is not.
    """
    array = np.asarray(image.convert("RGB"), dtype=float)
    height, width = array.shape[:2]
    y_edges = np.linspace(0, height, rows + 1).astype(int)
    x_edges = np.linspace(0, width, cols + 1).astype(int)
    out = np.zeros((rows, cols, 3), dtype=float)
    for r in range(rows):
        for c in range(cols):
            block = array[y_edges[r]:max(y_edges[r] + 1, y_edges[r + 1]),
                          x_edges[c]:max(x_edges[c] + 1, x_edges[c + 1])]
            out[r, c] = block.reshape(-1, 3).mean(axis=0)
    return out


def frame_hash(image, side=HASH_SIDE):
    """Average hash of the frame as an int of `side*side` bits."""
    grid = downsample(image, cols=side, rows=side)
    gray = grid @ np.array([.299, .587, .114])
    bits = (gray >= gray.mean()).flatten()
    value = 0
    for index, bit in enumerate(bits):
        if bit:
            value |= 1 << index
    return value


def hash_changed(previous, current, min_bits=HASH_MIN_BITS):
    """True when the frame moved enough to count as progress."""
    if previous is None:
        return True
    return bin(previous ^ current).count("1") >= min_bits


@dataclass
class ScreenProfile:
    """What one screen looks like, learned from captures of it."""

    name: str
    mean: list          # rows*cols*3 floats, flattened
    spread: list        # rows*cols floats, flattened
    threshold: float
    cols: int = FINGERPRINT_COLS
    rows: int = FINGERPRINT_ROWS
    tap: tuple | None = None            # normalized (x, y)
    tap_radius: tuple = (.02, .012)     # normalized safe radii
    sample_count: int = 0

    @classmethod
    def learn(cls, name, grids, tap=None, tap_radius=(.02, .012)):
        """Build a profile from >=1 downsampled captures of one screen."""
        if not len(grids):
            raise ValueError("a profile needs at least one capture")
        stack = np.stack([np.asarray(g, dtype=float) for g in grids])
        mean = stack.mean(axis=0)
        spread = np.maximum(stack.std(axis=0).mean(axis=2), MIN_SPREAD)
        distances = [_distance(mean, spread, grid) for grid in stack]
        threshold = max(MIN_THRESHOLD, max(distances) * THRESHOLD_MARGIN)
        rows, cols = mean.shape[:2]
        return cls(name=name, mean=mean.flatten().tolist(),
                   spread=spread.flatten().tolist(), threshold=threshold,
                   cols=cols, rows=rows, tap=tap, tap_radius=tap_radius,
                   sample_count=len(stack))

    def arrays(self):
        mean = np.asarray(self.mean, dtype=float).reshape(self.rows,
                                                          self.cols, 3)
        spread = np.asarray(self.spread, dtype=float).reshape(self.rows,
                                                              self.cols)
        return mean, spread

    def distance(self, grid):
        mean, spread = self.arrays()
        return _distance(mean, spread, np.asarray(grid, dtype=float))

    def matches(self, grid):
        return self.distance(grid) <= self.threshold


def _distance(mean, spread, grid):
    """Spread-weighted mean absolute colour distance, normalized to 0..1.

    Cells that varied a lot across the captures are exactly the cells that
    carry no identity (an animating battle, a spinning reward), so their
    weight decays as 1/spread. Without this the animated half of a screen
    dominates a plain average and forces a threshold so loose that a
    different dialog fits under it.
    """
    difference = np.abs(grid - mean).mean(axis=2)
    weights = 1.0 / spread
    return float((difference * weights).sum() / weights.sum() / 255.0)


@dataclass
class StateSpec:
    """The policy for one recognized screen."""

    name: str
    # What to do while this screen is on: tap its profile point, or wait.
    action: str = "tap"                 # "tap" | "wait" | "stop"
    taps_max: int = 2                   # per visit to this screen
    settle: float = .35                 # seconds on screen before tapping
    retry: float = 1.2                  # seconds between taps here
    starts_session: bool = False        # this screen begins one run
    requires_session: bool = False      # only act if we started the run
    counts_cycle: bool = False          # reaching it completes a run
    stop_reason: str | None = None      # for action == "stop"


@dataclass
class LoopPolicy:
    inactivity_timeout: float = 15.0    # seconds of a frozen screen
    session_timeout: float = 300.0      # seconds for one run
    max_cycles: int | None = None       # budget of completed runs
    ineffective_taps_backoff: int = 3   # taps that changed nothing
    ineffective_taps_stop: int = 6
    backoff_factor: float = 1.5
    backoff_cap: float = 4.0
    # Adopt a run that was already on screen when the loop started. Off by
    # default, and deliberately limited to the FIRST session: relaunching
    # while the game sits on a `requires_session` screen (a reward panel
    # left over from the previous process) otherwise deadlocks forever on
    # "sin sesion propia", because the screen that would start a session is
    # behind the one nobody is allowed to close. Adopting once unblocks
    # that and leaves the rule standing for every later run.
    adopt_session: bool = False


# Named because the CLI has to recognize it: in a dry run no tap is ever
# sent, so the screen cannot advance and this reason repeats until the
# frame budget runs out. That looks like a broken profile and is not one.
TAP_CAP_REASON = "tope de taps en esta pantalla"


@dataclass
class Decision:
    kind: str                            # "tap" | "wait" | "stop"
    reason: str
    state: str | None = None
    tap: tuple | None = None             # normalized (x, y)
    tap_radius: tuple = (.02, .012)
    detail: dict = field(default_factory=dict)


class LoopRunner:
    """Screen state machine. Feed it observations, execute its decisions."""

    def __init__(self, profiles, states, policy=None):
        self.profiles = {p.name: p for p in profiles}
        self.states = {s.name: s for s in states}
        self.policy = policy or LoopPolicy()
        self.session_active = False
        self.cycles = 0
        self.taps_sent = 0
        self.ineffective_taps = 0
        self.backoff = 1.0
        self._state = None
        self._state_since = None
        self._taps_on_state = 0
        self._last_tap_at = None
        self._tap_pending_proof = False
        self._session_started_at = None
        self._last_change_at = None
        self._session_ever = False

    # -- observation -----------------------------------------------------
    def classify(self, grid):
        """Best matching profile for a downsampled frame, or None."""
        best, best_distance = None, None
        for profile in self.profiles.values():
            distance = profile.distance(grid)
            if distance <= profile.threshold and (best_distance is None
                                                  or distance < best_distance):
                best, best_distance = profile, distance
        return (best.name if best else None), best_distance

    def observe(self, now, grid, frame_hash_value=None, previous_hash=None,
                min_bits=HASH_MIN_BITS):
        """Decide what to do with this frame."""
        name, distance = self.classify(grid)
        changed = hash_changed(previous_hash, frame_hash_value, min_bits) \
            if frame_hash_value is not None else True
        return self.decide(now, name, changed, distance)

    # -- decision --------------------------------------------------------
    def decide(self, now, state_name, changed=True, distance=None):
        if self._last_change_at is None or changed:
            self._last_change_at = now
        if state_name != self._state:
            self._on_state_change(now, state_name)

        spec = self.states.get(state_name) if state_name else None

        if spec is not None and spec.action == "stop":
            self.session_active = False
            return Decision("stop", spec.stop_reason or f"pantalla {spec.name}",
                            state_name, detail={"distance": distance})

        if spec is not None and spec.starts_session:
            if self.budget_spent():
                # Stop on the screen that would begin the next run, never
                # in the middle of one: a half-run costs the ticket and
                # returns nothing.
                self.session_active = False
                return Decision("stop", "presupuesto de vueltas agotado",
                                state_name, detail={"cycles": self.cycles})
            if not self.session_active:
                self.session_active = True
                self._session_ever = True
                self._session_started_at = now

        if self.session_active and self._session_started_at is not None \
                and now - self._session_started_at >= self.policy.session_timeout:
            self.session_active = False
            return Decision("stop", "timeout de sesion", state_name)

        if self.session_active and \
                now - self._last_change_at >= self.policy.inactivity_timeout:
            self.session_active = False
            return Decision("stop", "sin progreso visible", state_name)

        if spec is None:
            # Unknown screen: this is the loading/battle in between. Keep
            # waiting while the session lives; the inactivity timeout above
            # is what ends a run that got stuck on an unclassified dialog.
            return Decision("wait", "pantalla desconocida", state_name,
                            detail={"distance": distance})

        if spec.requires_session and not self.session_active:
            # The Android original's rule, and it is a good one: never act
            # on a screen that some other part of the game put there.
            if not (self.policy.adopt_session and not self._session_ever):
                return Decision("wait", "sin sesion propia", state_name)
            # First frames of the run and the leftover screen is the only
            # thing between us and the loop: adopt it once, say so, and
            # never again.
            self.session_active = True
            self._session_ever = True
            self._session_started_at = now

        if spec.action == "wait":
            return Decision("wait", "esperando a que el juego avance",
                            state_name)

        if self._taps_on_state >= spec.taps_max:
            return Decision("wait", TAP_CAP_REASON,
                            state_name,
                            detail={"taps": self._taps_on_state})

        if now - self._state_since < spec.settle:
            return Decision("wait", "asentando la pantalla", state_name)

        if self._last_tap_at is not None and \
                now - self._last_tap_at < spec.retry * self.backoff:
            return Decision("wait", "esperando el intervalo de reintento",
                            state_name)

        if self._tap_pending_proof and not changed:
            # The retry interval elapsed, the screen is still the same one
            # and the frame did not move: the game did not take that tap.
            # This is the ledger's rule applied to menus - the tap that
            # left no trace never happened.
            self._tap_pending_proof = False
            self.note_ineffective_tap()

        if self.ineffective_taps >= self.policy.ineffective_taps_stop:
            self.session_active = False
            return Decision("stop", "taps sin efecto", state_name,
                            detail={"ineffective": self.ineffective_taps})

        profile = self.profiles.get(state_name)
        tap = spec_tap(spec, profile)
        if tap is None:
            return Decision("wait", "la pantalla no tiene punto de tap",
                            state_name)
        self._last_tap_at = now
        self._taps_on_state += 1
        self.taps_sent += 1
        self._tap_pending_proof = True
        return Decision("tap", "tap en la pantalla reconocida", state_name,
                        tap=tap,
                        tap_radius=(profile.tap_radius if profile else
                                    (.02, .012)),
                        detail={"taps_on_state": self._taps_on_state,
                                "distance": distance})

    def _on_state_change(self, now, state_name):
        leaving = self._state
        if self._tap_pending_proof and leaving is not None:
            # The screen we tapped is gone: that tap was charged.
            self.ineffective_taps = 0
            self.backoff = 1.0
        self._tap_pending_proof = False
        spec = self.states.get(state_name) if state_name else None
        # A cycle is counted when a run this loop opened comes back
        # around, never on the first sight of the screen: arriving at the
        # challenge dialog is not a completed dungeon, it is the offer of
        # one.
        if spec is not None and spec.counts_cycle and self.session_active:
            self.cycles += 1
        if spec is not None and spec.starts_session:
            # The session clock bounds ONE run, so it restarts every time
            # the screen that opens a run comes back. Setting it once and
            # leaving it turned the guard into a global cap: the live
            # dungeon loop of 2026-08-25 died at 5:01 with 13 clean
            # cycles behind it and nothing wrong on screen.
            self._session_started_at = now
        self._state = state_name
        self._state_since = now
        self._taps_on_state = 0
        self._last_tap_at = None

    def note_ineffective_tap(self):
        """Called when a tap left both the screen and the frame unchanged."""
        self.ineffective_taps += 1
        if self.ineffective_taps >= self.policy.ineffective_taps_backoff:
            self.backoff = min(self.policy.backoff_cap,
                               self.backoff * self.policy.backoff_factor)

    def budget_spent(self):
        return (self.policy.max_cycles is not None
                and self.cycles >= self.policy.max_cycles)


def spec_tap(spec, profile):
    if profile is None or profile.tap is None:
        return None
    return tuple(profile.tap)


# -- persistence ---------------------------------------------------------

def save_profiles(path, profiles, states=None, policy=None):
    payload = {
        "profiles": [asdict(p) for p in profiles],
        "states": [asdict(s) for s in (states or [])],
        "policy": asdict(policy) if policy else None,
    }
    Path(path).write_text(json.dumps(payload, indent=1), encoding="utf-8")


def load_profiles(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    profiles = [ScreenProfile(**dict(p, tap=tuple(p["tap"]) if p.get("tap")
                                     else None,
                                     tap_radius=tuple(p.get("tap_radius",
                                                            (.02, .012)))))
                for p in payload["profiles"]]
    states = [StateSpec(**s) for s in payload.get("states", [])]
    policy = LoopPolicy(**payload["policy"]) if payload.get("policy") else None
    return profiles, states, policy
