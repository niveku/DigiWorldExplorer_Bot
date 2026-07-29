#!/usr/bin/env python3
"""Conservative ADB observer/controller for Digimon UP DigiWorld.

Input is disabled unless --allow-input is supplied. Even then, taps are only
accepted after a playfield has been detected with sufficient confidence.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


ADB_DEFAULT = "auto"
SERIAL_DEFAULT = "auto"


def resolve_adb(requested: str = ADB_DEFAULT) -> str:
    """Find BlueStacks' bundled ADB or a compatible ADB on PATH."""
    explicit = requested if requested and requested.lower() != "auto" else None
    candidates = []
    if explicit:
        candidates.append(explicit)
    if os.environ.get("DIGIWORLD_ADB"):
        candidates.append(os.environ["DIGIWORLD_ADB"])

    for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(env_name)
        if base:
            candidates.extend([
                str(Path(base) / "BlueStacks_nxt" / "HD-Adb.exe"),
                str(Path(base) / "BlueStacks" / "HD-Adb.exe"),
            ])
    for command in ("HD-Adb.exe", "HD-Adb", "adb.exe", "adb"):
        found = shutil.which(command)
        if found:
            candidates.append(found)

    seen = set()
    for candidate in candidates:
        normalized = os.path.normcase(os.path.abspath(os.path.expandvars(candidate)))
        if normalized in seen:
            continue
        seen.add(normalized)
        if Path(candidate).is_file():
            return str(Path(candidate).resolve())

    if explicit:
        raise RuntimeError(f"ADB wurde nicht gefunden: {explicit}")
    raise RuntimeError(
        "ADB wurde nicht gefunden. Installiere BlueStacks 5 oder setze "
        "DIGIWORLD_ADB auf den vollstaendigen Pfad zu HD-Adb.exe."
    )


def _device_rows(adb_path: str):
    result = subprocess.run([adb_path, "devices"], check=True,
                            capture_output=True, text=True)
    rows = []
    for line in result.stdout.splitlines()[1:]:
        parts = line.strip().split()
        if len(parts) >= 2:
            rows.append((parts[0], parts[1]))
    return rows


def resolve_serial(adb_path: str, requested: str = SERIAL_DEFAULT) -> str:
    """Select a connected BlueStacks device without assuming a fixed port."""
    explicit = requested if requested and requested.lower() != "auto" else None
    env_serial = os.environ.get("DIGIWORLD_SERIAL")
    if not explicit and env_serial:
        explicit = env_serial

    if explicit and ":" in explicit:
        subprocess.run([adb_path, "connect", explicit], capture_output=True, text=True)

    rows = _device_rows(adb_path)
    devices = [serial for serial, state in rows if state == "device"]
    if explicit:
        if explicit in devices:
            return explicit
        raise RuntimeError(
            f"ADB-Geraet {explicit!r} ist nicht bereit. Geraete: {rows or 'keine'}"
        )

    if not devices:
        # The default BlueStacks instance commonly exposes this endpoint, but
        # newer/multi-instance installations may advertise another serial.
        subprocess.run([adb_path, "connect", "127.0.0.1:5555"],
                       capture_output=True, text=True)
        rows = _device_rows(adb_path)
        devices = [serial for serial, state in rows if state == "device"]
    if not devices:
        raise RuntimeError(
            "Kein ADB-Geraet gefunden. Starte BlueStacks und aktiviere unter "
            "Einstellungen > Erweitert den Android Debug Bridge-Schalter."
        )

    preferred = ("127.0.0.1:5555", "emulator-5554")
    for serial in preferred:
        if serial in devices:
            return serial
    if len(devices) == 1:
        return devices[0]
    raise RuntimeError(
        "Mehrere ADB-Geraete gefunden. Setze DIGIWORLD_SERIAL oder verwende "
        f"--serial. Geraete: {devices}"
    )


@dataclass
class Detection:
    state: str
    confidence: float
    board: tuple[int, int, int, int] | None
    reason: str


def adb(adb_path: str, serial: str, *args: str, binary: bool = False):
    cmd = [adb_path, "-s", serial, *args]
    return subprocess.run(cmd, check=True, capture_output=True,
                          text=not binary).stdout


def screenshot(adb_path: str, serial: str) -> Image.Image:
    if not adb_path or adb_path.lower() == "auto":
        adb_path = resolve_adb(adb_path)
    if not serial or serial.lower() == "auto":
        serial = resolve_serial(adb_path, serial)
    raw = adb(adb_path, serial, "exec-out", "screencap", "-p", binary=True)
    from io import BytesIO
    return Image.open(BytesIO(raw)).convert("RGB")


def _components(mask: np.ndarray):
    """Connected components on a small boolean mask, without OpenCV/SciPy."""
    seen = np.zeros(mask.shape, dtype=bool)
    result = []
    height, width = mask.shape
    for sy, sx in zip(*np.nonzero(mask & ~seen)):
        if seen[sy, sx]:
            continue
        stack, seen[sy, sx] = [(int(sy), int(sx))], True
        x0 = x1 = int(sx); y0 = y1 = int(sy); area = 0
        while stack:
            y, x = stack.pop(); area += 1
            x0, x1, y0, y1 = min(x0, x), max(x1, x), min(y0, y), max(y1, y)
            for ny, nx in ((y-1,x),(y+1,x),(y,x-1),(y,x+1)):
                if 0 <= ny < height and 0 <= nx < width and mask[ny,nx] and not seen[ny,nx]:
                    seen[ny,nx] = True; stack.append((ny,nx))
        result.append((x0, y0, x1 + 1, y1 + 1, area))
    return result


def _best_six_lines(score: np.ndarray, start_range: range, step_range: range):
    """Find six near-equidistant edges; tolerate one edge hidden by a sprite."""
    best = None
    for step in step_range:
        for start in start_range:
            if start + 5 * step >= len(score):
                continue
            positions, values = [], []
            for i in range(6):
                expected = start + i * step
                lo, hi = max(0, expected - 2), min(len(score), expected + 3)
                offset = int(np.argmax(score[lo:hi]))
                positions.append(lo + offset)
                values.append(float(score[lo + offset]))
            # The second weakest line dominates the score. This prevents two
            # strong panel borders from masquerading as a five-cell grid.
            quality = sorted(values)[1] + 0.10 * float(np.mean(values))
            if best is None or quality > best[0]:
                best = (quality, positions, values)
    return best


def classify(image: Image.Image) -> Detection:
    """Find the board from repeated pale-blue walkable tile regions.

    DigiWorld must yield several similarly sized cyan components in a compact
    area. A screen-sized blue background alone is deliberately rejected.
    """
    w, h = image.size
    gray = np.asarray(image, dtype=float).mean(axis=2)
    # Vertical lines are evaluated through the upper play area, horizontal
    # lines through the centered content area. Coordinates remain framebuffer-
    # relative and are independent of the Windows window position.
    x_edges = np.mean(np.abs(np.diff(gray[int(.30*h):int(.70*h)], axis=1)), axis=0)
    y_edges = np.mean(np.abs(np.diff(gray[:, int(.10*w):int(.90*w)], axis=0)), axis=1)
    xb = _best_six_lines(x_edges,
                         range(int(.05*w), int(.25*w)),
                         range(int(.10*w), int(.22*w)))
    yb = _best_six_lines(y_edges,
                         # The board begins in the upper two fifths. Allowing
                         # later starts can mistake rows 1-5 plus the progress
                         # panel for a shifted six-line grid when row 0 is full
                         # of pyramids.
                         range(int(.20*h), int(.39*h)),
                         range(int(.045*h), int(.10*h)))
    if xb and yb:
        x_quality, xp, xv = xb
        y_quality, yp, yv = yb
        if sorted(xv)[1] >= 15.0 and sorted(yv)[1] >= 15.0:
            # Fit all six lines instead of trusting an outer line that may be
            # partially hidden by the Digimon sprite or an animation.
            xi = np.polyfit(np.arange(6), np.asarray(xp), 1)
            yi = np.polyfit(np.arange(6), np.asarray(yp), 1)
            board = (round(xi[1]), round(yi[1]),
                     round(xi[1] + 5*xi[0]), round(yi[1] + 5*yi[0]))
            bw, bh = board[2] - board[0], board[3] - board[1]
            if .85 <= bw / max(bh, 1) <= 1.55 and .20 <= bw*bh/(w*h) <= .45:
                confidence = min(.98, .70 + .005 * min(x_quality, y_quality))
                return Detection("digiworld", confidence, board,
                                 "six equidistant vertical and horizontal grid edges")

    # Reject the known start/menu layout after trying the stronger grid test.
    lower = np.asarray(image.crop((int(.15*w), int(.78*h), int(.85*w), int(.90*h))))
    lr, lg, lb = lower[:,:,0], lower[:,:,1], lower[:,:,2]
    start_blue = (lb > 100) & (lg > 80) & (lb.astype(int) > lr.astype(int) + 20)
    if np.count_nonzero(start_blue) / start_blue.size > 0.08:
        return Detection("title_or_menu", 0.92, None,
                         "prominent lower-center cyan start/menu region; no board")

    small = image.resize((180, 320), Image.Resampling.BILINEAR)
    rgb = np.asarray(small)
    r, g, b = rgb[:,:,0], rgb[:,:,1], rgb[:,:,2]
    cyan = (b > 105) & (g > 85) & (b.astype(int) > r.astype(int) + 18) & (g.astype(int) > r.astype(int) + 8)
    components = []
    sx_scale, sy_scale = w / 180, h / 320
    for x0s, y0s, x1s, y1s, areas in _components(cyan):
        x, y = round(x0s*sx_scale), round(y0s*sy_scale)
        cw, ch = round((x1s-x0s)*sx_scale), round((y1s-y0s)*sy_scale)
        area = round(areas*sx_scale*sy_scale)
        if 0.025 * w <= cw <= 0.30 * w and 0.018 * h <= ch <= 0.18 * h:
            if area >= 0.20 * cw * ch:
                components.append((int(x), int(y), int(cw), int(ch), int(area)))

    if len(components) >= 6:
        xs = [c[0] for c in components] + [c[0] + c[2] for c in components]
        ys = [c[1] for c in components] + [c[1] + c[3] for c in components]
        x0, x1 = max(0, min(xs)), min(w, max(xs))
        y0, y1 = max(0, min(ys)), min(h, max(ys))
        bw, bh = x1 - x0, y1 - y0
        aspect = bw / max(bh, 1)
        coverage = bw * bh / (w * h)
        confidence = min(0.98, 0.45 + 0.04 * len(components))
        if 0.55 <= aspect <= 2.2 and 0.12 <= coverage <= 0.80:
            return Detection("digiworld", confidence, (x0, y0, x1, y1),
                             f"{len(components)} cyan tile-like regions")

    return Detection("unknown", 0.0, None,
                     f"only {len(components)} tile-like cyan regions")


def cell_center(board: tuple[int, int, int, int], row: int, col: int):
    x0, y0, x1, y1 = board
    return (round(x0 + (col + 0.5) * (x1 - x0) / 5),
            round(y0 + (row + 0.5) * (y1 - y0) / 5))


def attack_button(image: Image.Image) -> tuple[int, int] | None:
    """Detect the yellow claw control in the lower-left HUD."""
    a = np.asarray(image)
    h, w = a.shape[:2]
    r, g, b = a[:,:,0], a[:,:,1], a[:,:,2]
    mask = (r > 150) & (g > 100) & (b < 130)
    mask[:int(.78*h), :] = False
    mask[:, :int(.10*w)] = False
    mask[:, int(.55*w):] = False
    candidates = [c for c in _components(mask) if c[4] >= 80]
    if not candidates:
        return None
    x0, y0, x1, y1, _ = max(candidates, key=lambda c: c[4])
    return ((x0 + x1)//2, (y0 + y1)//2)


def dash_button(image: Image.Image) -> tuple[int, int] | None:
    """Detect the large lime/cyan dash control in the lower HUD."""
    a = np.asarray(image)
    h, w = a.shape[:2]
    r, g, b = a[:,:,0], a[:,:,1], a[:,:,2]
    mask = (g > 175) & (r < 190) & (b < 190)
    mask[:int(.78*h), :] = False
    mask[:, :int(.45*w)] = False
    mask[:, int(.80*w):] = False
    candidates = [c for c in _components(mask) if c[4] >= 250]
    if not candidates:
        return None
    x0, y0, x1, y1, _ = max(candidates, key=lambda c: c[4])
    return ((x0 + x1)//2, (y0 + y1)//2)


def tutorial_overlay_center(image: Image.Image) -> tuple[int, int] | None:
    """Recognize the large centered blue first-use tutorial card."""
    a = np.asarray(image)
    h, w = a.shape[:2]
    center = a[int(.35*h):int(.70*h), int(.12*w):int(.88*w)]
    # Normal boards also contain a large connected blue area. Overlays add a
    # broad near-white title/body text line. Bright sprite fragments and item
    # icons occupy too few columns to qualify.
    white = np.all(center > 225, axis=2)
    if int(np.count_nonzero(np.sum(white, axis=0) >= 2)) < 200:
        return None
    r, g, b = a[:,:,0], a[:,:,1], a[:,:,2]
    mask = (b > 70) & (b.astype(int) > r.astype(int) + 20) & (g > 35)
    for x0, y0, x1, y1, area in _components(mask):
        if (area > .08*w*h and x0 < .30*w and x1 > .70*w and
                y0 < .55*h and y1 > .55*h):
            return ((x0+x1)//2, (y0+y1)//2)
    return None


def diagnostic(image: Image.Image, det: Detection) -> Image.Image:
    out = image.copy(); draw = ImageDraw.Draw(out)
    color = (40, 220, 40) if det.board else (255, 180, 0)
    if det.board:
        x0, y0, x1, y1 = det.board
        for i in range(6):
            x = round(x0 + i * (x1 - x0) / 5)
            y = round(y0 + i * (y1 - y0) / 5)
            draw.line((x, y0, x, y1), fill=color, width=2)
            draw.line((x0, y, x1, y), fill=color, width=2)
        draw.rectangle((x0, y0, x1, y1), outline=color, width=3)
    label = f"STATE={det.state} CONF={det.confidence:.2f}"
    draw.rectangle((8, 8, min(out.width-8, 570), 78), fill=(0, 0, 0))
    font = ImageFont.load_default(size=20)
    small_font = ImageFont.load_default(size=13)
    draw.text((18, 17), label, fill=color, font=font)
    draw.text((18, 50), det.reason[:70], fill=(255,255,255), font=small_font)
    return out


def log_event(path: Path, event: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--adb", default=ADB_DEFAULT)
    p.add_argument("--serial", default=SERIAL_DEFAULT)
    p.add_argument("--out", type=Path, default=Path("outputs"))
    p.add_argument("--allow-input", action="store_true")
    p.add_argument("--tap-cell", nargs=2, type=int, metavar=("ROW", "COL"))
    p.add_argument("--attack-cell", nargs=2, type=int, metavar=("ROW", "COL"))
    p.add_argument("--dash", action="store_true")
    p.add_argument("--dismiss-tutorial", action="store_true")
    p.add_argument("--min-confidence", type=float, default=0.85)
    p.add_argument("--animation-wait", type=float, default=2.0)
    args = p.parse_args()

    try:
        args.adb = resolve_adb(args.adb)
        args.serial = resolve_serial(args.adb, args.serial)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 10
    print(json.dumps({"adb": args.adb, "serial": args.serial,
                      "mode": "input" if args.allow_input else "observe"},
                     ensure_ascii=False))

    args.out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    image = screenshot(args.adb, args.serial)
    det = classify(image)
    raw_path = args.out / f"digiworld_raw_{stamp}.png"
    diag_path = args.out / f"digiworld_diagnostic_{stamp}.png"
    image.save(raw_path)
    diagnostic(image, det).save(diag_path)
    event = {"time_utc": stamp, "mode": "input" if args.allow_input else "observe",
             "detection": asdict(det), "raw": str(raw_path), "diagnostic": str(diag_path)}

    requested_cell = args.attack_cell or args.tap_cell
    if args.dismiss_tutorial:
        control = tutorial_overlay_center(image)
        if not args.allow_input:
            event["action"] = "STOP: tutorial dismissal requested but input is disabled"
        elif control is None:
            event["action"] = "STOP: tutorial overlay was not detected"
        else:
            adb(args.adb, args.serial, "shell", "input", "tap",
                str(control[0]), str(control[1]))
            event["action"] = {"status": "sent", "type": "dismiss_tutorial",
                               "control_xy": list(control)}
            time.sleep(1.5)
            post = screenshot(args.adb, args.serial)
            post_det = classify(post)
            post_raw = args.out / f"digiworld_post_raw_{stamp}.png"
            post_diag = args.out / f"digiworld_post_diagnostic_{stamp}.png"
            post.save(post_raw); diagnostic(post, post_det).save(post_diag)
            event["post_action"] = {"detection": asdict(post_det),
                                    "raw": str(post_raw), "diagnostic": str(post_diag)}
    elif args.dash:
        if not args.allow_input:
            event["action"] = "STOP: dash requested but input is disabled"
        elif det.state != "digiworld" or det.board is None or det.confidence < args.min_confidence:
            event["action"] = "STOP: board recognition is not reliable"
        else:
            control = dash_button(image)
            if control is None:
                event["action"] = "STOP: large dash control was not detected"
            else:
                try:
                    adb(args.adb, args.serial, "shell", "input", "tap",
                        str(control[0]), str(control[1]))
                except subprocess.CalledProcessError as exc:
                    event["action"] = {"status": "STOP: ADB rejected dash",
                                       "adb_exit": exc.returncode}
                else:
                    event["action"] = {"status": "sent", "type": "dash",
                                       "control_xy": list(control)}
                    time.sleep(3.0)
                    post = screenshot(args.adb, args.serial)
                    post_det = classify(post)
                    post_raw = args.out / f"digiworld_post_raw_{stamp}.png"
                    post_diag = args.out / f"digiworld_post_diagnostic_{stamp}.png"
                    post.save(post_raw)
                    diagnostic(post, post_det).save(post_diag)
                    event["post_action"] = {"detection": asdict(post_det),
                                            "raw": str(post_raw),
                                            "diagnostic": str(post_diag)}
    elif args.attack_cell and args.tap_cell:
        event["action"] = "STOP: request only one action at a time"
    elif requested_cell:
        row, col = requested_cell
        if not args.allow_input:
            event["action"] = "STOP: tap requested but input is disabled"
        elif det.state != "digiworld" or det.board is None or det.confidence < args.min_confidence:
            event["action"] = "STOP: board recognition is not reliable"
        elif not (0 <= row < 5 and 0 <= col < 5):
            event["action"] = "STOP: cell must be within row/col 0..4"
        else:
            x, y = cell_center(det.board, row, col)
            try:
                control = None
                adb(args.adb, args.serial, "shell", "input", "tap", str(x), str(y))
            except subprocess.CalledProcessError as exc:
                stderr = exc.stderr.strip() if isinstance(exc.stderr, str) else repr(exc.stderr)
                event["action"] = {
                    "status": "STOP: ADB rejected tap; no input confirmed",
                    "tap_cell": [row, col], "adb_xy": [x, y],
                    "adb_exit": exc.returncode, "adb_stderr": stderr,
                }
            except RuntimeError as exc:
                event["action"] = {"status": f"STOP: {exc}",
                                   "target_cell": [row, col]}
            else:
                event["action"] = {"status": "sent",
                                   "type": "attack" if args.attack_cell else "move",
                                   "target_cell": [row, col], "adb_xy": [x, y]}
                if control:
                    event["action"]["control_xy"] = list(control)
                time.sleep(max(.5, args.animation_wait))
                post = screenshot(args.adb, args.serial)
                post_det = classify(post)
                post_raw = args.out / f"digiworld_post_raw_{stamp}.png"
                post_diag = args.out / f"digiworld_post_diagnostic_{stamp}.png"
                post.save(post_raw)
                diagnostic(post, post_det).save(post_diag)
                event["post_action"] = {
                    "detection": asdict(post_det),
                    "raw": str(post_raw),
                    "diagnostic": str(post_diag),
                }
    else:
        event["action"] = "none"

    log_event(args.out / "digiworld_steps.jsonl", event)
    print(json.dumps(event, ensure_ascii=False, indent=2))
    return 0 if det.state == "digiworld" else 2


if __name__ == "__main__":
    sys.exit(main())
