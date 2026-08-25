#!/usr/bin/env python3
"""Who owns the frame when something covers the board.

Before this module the bot handled covers in two unrelated places: the
tutorial/toast branch in the main loop, and the unreliable-board branch
that tapped blindly outside a suspected popup on strikes 2 and 4. Both
worked, neither knew about the other, and neither could say "the board is
not mine right now" to the rest of the frame.

The Android companion (`feed/StageFailedFrameAnalyzer`) has the missing
idea: while a cover is positively recognized, one handler takes
**exclusive** control of the frame, and the mode that was running resumes
afterwards. Four things are added here on top of theirs:

1. **A ladder of dismiss points instead of one.** Their handler taps a
   single spot forever. This bot already knows two independently safe
   spots for a centred dialog - the inert left margin and the strip below
   the panel and above the home button - so an attempt that changed
   nothing tries the other one instead of the same one again.
2. **A cap on attempts, with a verdict.** Theirs retries every 30s
   without end. Here every cover has an attempt budget, and exhausting it
   returns `stop` with the reason, which is what turns a stuck run into a
   clear exit instead of five silent waits.
3. **Release on evidence, never on a dispatched tap.** The owner is
   released when the detector stops seeing the cover, in line with the
   ledger's rule for movement.
4. **The resumed mode is told what happened.** `freeze_reckoning` marks
   the covers that prove the world did not move (a rejection toast), so
   dead reckoning does not credit a step that the game refused.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class OverlayKind:
    """One recognizable cover and how to get rid of it."""

    name: str
    priority: int
    detect: object                       # callable(image, det) -> dict | None
    points: tuple = ()                   # ladder of normalized (x, y)
    cooldown: float = 1.5                # seconds between attempts
    max_attempts: int = 4
    freeze_reckoning: bool = False       # the world did not move behind it
    dismissable: bool = True             # False: only report, never tap


@dataclass
class OverlayDecision:
    kind: str                            # "none" | "dismiss" | "wait" | "stop"
    owner: str | None = None
    point: tuple | None = None           # absolute pixels
    reason: str = ""
    attempt: int = 0
    evidence: dict = field(default_factory=dict)
    freeze_reckoning: bool = False

    @property
    def owns_frame(self):
        return self.kind in ("dismiss", "wait", "stop")


class OverlayArbiter:
    """Decides, per frame, whether a cover owns the board and what to tap."""

    def __init__(self, kinds):
        # Highest priority first; ties keep the declared order.
        self._kinds = sorted(kinds, key=lambda k: -k.priority)
        self._owner = None
        self._attempts = 0
        self._last_attempt_at = None
        self._history = []

    @property
    def owner(self):
        return self._owner

    @property
    def attempts(self):
        return self._attempts

    def observe(self, now, image, det=None, size=None):
        """What to do with this frame."""
        found = None
        evidence = {}
        for kind in self._kinds:
            result = kind.detect(image, det)
            if result is not None:
                found, evidence = kind, (result if isinstance(result, dict)
                                         else {})
                break

        if found is None:
            if self._owner is not None:
                # Released on evidence: the cover is gone from the frame.
                self._history.append({"overlay": self._owner,
                                      "attempts": self._attempts,
                                      "resolved": True})
                self._owner = None
                self._attempts = 0
                self._last_attempt_at = None
            return OverlayDecision("none")

        if found.name != self._owner:
            if self._owner is not None:
                self._history.append({"overlay": self._owner,
                                      "attempts": self._attempts,
                                      "resolved": False})
            self._owner = found.name
            self._attempts = 0
            self._last_attempt_at = None

        if not found.dismissable:
            return OverlayDecision("wait", found.name, None,
                                   "cubierta reconocida, no se toca",
                                   self._attempts, evidence,
                                   found.freeze_reckoning)

        if self._attempts >= found.max_attempts:
            return OverlayDecision("stop", found.name, None,
                                   f"{found.name}: {self._attempts} intentos "
                                   "sin cerrarla", self._attempts, evidence,
                                   found.freeze_reckoning)

        if self._last_attempt_at is not None and \
                now - self._last_attempt_at < found.cooldown:
            return OverlayDecision("wait", found.name, None,
                                   "esperando entre intentos", self._attempts,
                                   evidence, found.freeze_reckoning)

        point = self._next_point(found, size)
        if point is None:
            return OverlayDecision("wait", found.name, None,
                                   "sin punto de cierre conocido",
                                   self._attempts, evidence,
                                   found.freeze_reckoning)
        self._attempts += 1
        self._last_attempt_at = now
        return OverlayDecision("dismiss", found.name, point,
                               "cerrando la cubierta", self._attempts,
                               evidence, found.freeze_reckoning)

    def _next_point(self, kind, size):
        if not kind.points:
            return None
        # An attempt that changed nothing tries the next known-safe spot
        # before repeating the first one.
        normalized = kind.points[self._attempts % len(kind.points)]
        if size is None:
            return tuple(normalized)
        width, height = size
        return (int(round(normalized[0] * width)),
                int(round(normalized[1] * height)))

    def report(self):
        """Closed episodes, for the run log."""
        return list(self._history)
