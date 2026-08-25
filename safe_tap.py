#!/usr/bin/env python3
"""Bounded variation for taps: where inside the target, and how long after.

Ported from the Android companion's `input/SafeTapRandomizer` (RobinTh0r,
`DigiWorldExplorer_Android_Bot`) and reworked for this bot. The idea is
theirs: the caller names a point it already knows is safe plus the radius
that stays safe, and the randomizer may only move the tap inside that
promise. The four corrections below came out of reading their 18-line
version against how this bot actually taps through ADB.

1. **The safe area is an ellipse, not a rectangle.** Sampling `x +- rx`
   and `y +- ry` independently puts the corner of the box at 1.41x the
   promised radius. On a 720x1280 board a cell is ~110px wide, so a
   +-45px "safe" radius reaches 63px diagonally - into the neighbouring
   cell, which is how a move tap turns into a garra on a pyramid nobody
   aimed at. Polar sampling with `sqrt(u)` keeps the point inside the
   promise and still spreads uniformly over the area.
2. **Screen bounds are clamped.** Their version can return a negative
   coordinate for a button near an edge; `adb shell input tap` accepts it
   and the gesture lands nowhere.
3. **Integers.** ADB takes integer pixels, so rounding is part of the
   contract instead of an afterthought at the call site.
4. **No two identical taps in a row on the same target.** A human never
   hits the same pixel twice; a macro always does. `TapJitter` remembers
   the last point per target key and resamples (bounded tries) when the
   new one lands on it.

`delay()` is two-sided around the base, which is what a retry loop wants:
the mean stays at the measured interval. The explorer's own pacing
(`action_delay`) is deliberately one-sided - there the base is a floor an
animation needs - so it keeps its own helper and is not routed through
here. Their version also silently collapses to `+-base` when the caller
passes a spread larger than the base (a 350ms base with 400ms spread can
produce a 0ms delay); ours clamps the result to a documented floor.
"""

from __future__ import annotations

import math
import random

# Never return a delay below this fraction of the base, whatever spread the
# caller asks for: a tap that fires immediately after the previous one is
# the swallowed-tap generator this bot spent runs 20260822T165752 and
# 20260824T0139 learning to avoid.
MIN_DELAY_FRACTION = .35


def point(x, y, safe_radius_x, safe_radius_y, bounds=None, rand=None):
    """A random point inside the ellipse (`safe_radius_x`, `safe_radius_y`).

    `bounds` is `(width, height)` of the screen when the caller wants the
    result clamped to it. Returns integer pixels.
    """
    rng = rand or random
    rx = max(0.0, float(safe_radius_x))
    ry = max(0.0, float(safe_radius_y))
    if rx == 0.0 and ry == 0.0:
        px, py = float(x), float(y)
    else:
        angle = rng.random() * 2.0 * math.pi
        # sqrt keeps the sample uniform over the AREA; without it the
        # points bunch in the middle and the variation stops looking like
        # variation.
        radius = math.sqrt(rng.random())
        px = x + math.cos(angle) * rx * radius
        py = y + math.sin(angle) * ry * radius
    px, py = int(round(px)), int(round(py))
    if bounds is not None:
        width, height = bounds
        px = min(max(px, 0), max(0, int(width) - 1))
        py = min(max(py, 0), max(0, int(height) - 1))
    return px, py


def delay(base, spread, rand=None):
    """A pacing delay of `base` +- `spread`, floored, never negative."""
    rng = rand or random
    base = max(0.0, float(base))
    spread = max(0.0, float(spread))
    if base == 0.0:
        return 0.0
    value = base + (rng.random() * 2.0 - 1.0) * spread
    return max(base * MIN_DELAY_FRACTION, value)


class TapJitter:
    """Stateful wrapper that refuses to repeat a point on the same target.

    `key` names the target (a button, a cell) so two different buttons do
    not fight over one another's history.
    """

    RESAMPLE_TRIES = 4

    def __init__(self, rand=None):
        self._rand = rand or random
        self._last = {}

    def point(self, key, x, y, safe_radius_x, safe_radius_y, bounds=None):
        previous = self._last.get(key)
        result = None
        for _ in range(self.RESAMPLE_TRIES):
            result = point(x, y, safe_radius_x, safe_radius_y, bounds,
                           self._rand)
            if result != previous:
                break
        # A zero radius has exactly one legal point: repeating it is the
        # caller's decision, not a defect, so the last try is accepted.
        self._last[key] = result
        return result

    def delay(self, base, spread):
        return delay(base, spread, self._rand)

    def forget(self, key=None):
        if key is None:
            self._last.clear()
        else:
            self._last.pop(key, None)
