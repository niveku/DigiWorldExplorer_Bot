#!/usr/bin/env python3
"""CLI for the repeatable-screen loops (dungeons, defense, summons).

The engine lives in `screen_loop.py`; this is the part that talks to ADB
and to the person calibrating it. Nothing here carries hand-written pixel
constants: a loop is taught from captures of the screens it has to
recognize, on the machine and resolution it will run on.

Typical session for a dungeon that repeats:

    # 1. Open the challenge dialog in the game, then:
    python screen_loops.py capture --state challenge --count 4

    # 2. Let a run finish and open the reward screen, then:
    python screen_loops.py capture --state reward --count 4

    # 3. Turn the captures into a profile set. Taps are given in pixels
    #    of the capture (or as 0..1 fractions).
    python screen_loops.py learn --name attack_trials \\
        --tap challenge=460,1000 --tap reward=360,845 \\
        --start challenge --cycle challenge --needs-session reward

    # 4. Watch it recognize screens WITHOUT touching anything:
    python screen_loops.py watch --loop attack_trials

    # 5. Only when step 4 looks right:
    python screen_loops.py run --loop attack_trials --cycles 5

`watch` is not an afterthought: a loop that taps a screen it misread is
how a bot spends tickets on the wrong dialog, so the dry run is the
supported way to find out what the profiles actually see.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import digiworld_bot as bot
import safe_tap
import screen_loop

LOOPS_DIR = Path(__file__).with_name("screen_profiles")
CAPTURES_DIR = LOOPS_DIR / "captures"


def _stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")


def _device(args):
    adb_path = bot.resolve_adb(args.adb)
    serial = bot.resolve_serial(adb_path, args.serial)
    return adb_path, serial


def capture(args):
    """Save N screenshots of one screen, for learning it later."""
    adb_path, serial = _device(args)
    folder = CAPTURES_DIR / args.loop / args.state
    folder.mkdir(parents=True, exist_ok=True)
    for index in range(args.count):
        image = bot.screenshot(adb_path, serial)
        path = folder / f"{_stamp()}.png"
        image.save(path)
        print(f"[{index + 1}/{args.count}] {path}  {image.size[0]}x{image.size[1]}")
        if index + 1 < args.count:
            time.sleep(args.interval)
    print(f"\nCapturas de '{args.state}' en {folder}")
    print("Repite con la pantalla en distintos momentos (animaciones "
          "incluidas): cuantas mas capturas, mejor sabe el perfil que "
          "partes de la pantalla NO deciden.")
    return 0


def _parse_point(raw, size):
    x, y = (float(part) for part in raw.split(","))
    if x > 1 or y > 1:      # pixels of the capture
        return x / size[0], y / size[1]
    return x, y


def learn(args):
    """Build the profile set for a loop out of its captures."""
    from PIL import Image

    folder = CAPTURES_DIR / args.loop
    if not folder.exists():
        print(f"No hay capturas en {folder}. Corre 'capture' primero.")
        return 2
    taps = dict(item.split("=", 1) for item in args.tap)
    profiles, states = [], []
    for state_dir in sorted(p for p in folder.iterdir() if p.is_dir()):
        images = sorted(state_dir.glob("*.png"))
        if not images:
            continue
        grids, size = [], None
        for path in images:
            with Image.open(path) as image:
                size = image.size
                grids.append(screen_loop.downsample(image))
        name = state_dir.name
        tap = _parse_point(taps[name], size) if name in taps else None
        profiles.append(screen_loop.ScreenProfile.learn(name, grids, tap=tap))
        states.append(screen_loop.StateSpec(
            name=name,
            action="stop" if name in args.stop else "tap" if tap else "wait",
            stop_reason=f"pantalla {name}" if name in args.stop else None,
            starts_session=name in args.start,
            requires_session=name in args.needs_session,
            counts_cycle=name in args.cycle,
            taps_max=args.taps_max, settle=args.settle, retry=args.retry))
        print(f"{name:>16}: {len(grids)} capturas, umbral "
              f"{profiles[-1].threshold:.4f}, tap {tap}")
    if not profiles:
        print("Ninguna carpeta de estado tenia capturas.")
        return 2
    _report_separation(profiles)
    policy = screen_loop.LoopPolicy(inactivity_timeout=args.inactivity,
                                    session_timeout=args.session_timeout,
                                    max_cycles=args.cycles)
    path = LOOPS_DIR / f"{args.loop}.json"
    screen_loop.save_profiles(path, profiles, states, policy)
    print(f"\nPerfil guardado en {path}")
    return 0


def _report_separation(profiles):
    """How far each screen sits from the others, in units of its threshold.

    Anything below 1.0 means two screens can be confused and the captures
    are not enough to tell them apart - that is a calibration problem, and
    it is better found here than by a tap on the wrong dialog.
    """
    if len(profiles) < 2:
        return
    print("\nSeparacion entre pantallas (1.0 = en el limite de confundirse):")
    for profile in profiles:
        mean, _ = profile.arrays()
        others = [(other.name, other.distance(mean) / other.threshold)
                  for other in profiles if other is not profile]
        worst = min(others, key=lambda item: item[1])
        flag = "  <-- REVISAR" if worst[1] < 1.0 else ""
        print(f"  {profile.name:>16} vs {worst[0]:<16} {worst[1]:5.2f}x{flag}")


def _load(args):
    path = LOOPS_DIR / f"{args.loop}.json"
    if not path.exists():
        print(f"No existe {path}. Corre 'learn' primero.")
        return None
    profiles, states, policy = screen_loop.load_profiles(path)
    if args.cycles is not None:
        policy = policy or screen_loop.LoopPolicy()
        policy.max_cycles = args.cycles
    if getattr(args, "adopt_session", False):
        policy = policy or screen_loop.LoopPolicy()
        policy.adopt_session = True
    return screen_loop.LoopRunner(profiles, states, policy)


def watch(args):
    """Dry run: recognize screens and print what it WOULD do. No taps."""
    args.dry_run = True
    return run(args)


def run(args):
    loop = _load(args)
    if loop is None:
        return 2
    adb_path, serial = _device(args)
    jitter = safe_tap.TapJitter()
    log_dir = Path("outputs") / f"{_stamp()}_{args.loop}"
    log_dir.mkdir(parents=True, exist_ok=True)
    log = (log_dir / "events.jsonl").open("a", encoding="utf-8")
    previous_hash = None
    started = time.monotonic()
    mode = "SIMULACION (no toca nada)" if args.dry_run else "ACTIVO"
    print(f"Loop '{args.loop}' - {mode}. Ctrl+C para parar.")
    if args.dry_run:
        print("  La simulacion NO envia el tap, asi que la pantalla no puede")
        print("  avanzar: se queda en la misma y termina en el tope de taps.")
        print("  Eso es lo normal. Lo que hay que mirar es el NOMBRE de cada")
        print("  pantalla y el punto del tap, no que el loop progrese.")
    frames = 0
    try:
        while args.max_frames is None or frames < args.max_frames:
            frames += 1
            image = bot.screenshot(adb_path, serial)
            grid = screen_loop.downsample(image)
            current_hash = screen_loop.frame_hash(image)
            now = time.monotonic() - started
            decision = loop.observe(now, grid, current_hash, previous_hash)
            previous_hash = current_hash
            event = {"time_utc": datetime.now(timezone.utc).isoformat(),
                     "t": round(now, 2), "kind": decision.kind,
                     "state": decision.state, "reason": decision.reason,
                     "cycles": loop.cycles, "detail": decision.detail}
            if decision.kind == "tap" and decision.tap is not None:
                width, height = image.size
                x, y = jitter.point(decision.state or "?",
                                    decision.tap[0] * width,
                                    decision.tap[1] * height,
                                    decision.tap_radius[0] * width,
                                    decision.tap_radius[1] * height,
                                    bounds=image.size)
                event["tap_xy"] = [x, y]
                if not args.dry_run:
                    bot.adb(adb_path, serial, "shell", "input", "tap",
                            str(x), str(y))
            log.write(json.dumps(event) + "\n")
            log.flush()
            print(f"  t={now:7.1f}s  {str(decision.state):>16}  "
                  f"{decision.kind:<6} {decision.reason}"
                  + (f"  -> {event['tap_xy']}" if "tap_xy" in event else ""))
            # Nothing further can be learned once the cap is hit in a dry
            # run: without a real tap the screen stays put, so every later
            # frame repeats this line and hides the useful ones above it.
            if args.dry_run and decision.reason == screen_loop.TAP_CAP_REASON:
                print(f"\nFIN de la simulacion: la pantalla '{decision.state}' "
                      f"ya recibio sus taps simulados y no puede cambiar sola.\n"
                      f"Si el nombre y el punto de arriba son correctos, "
                      f"arranca el loop activo.")
                return 0
            if decision.kind == "stop":
                print(f"\nFIN: {decision.reason}. Vueltas completadas: "
                      f"{loop.cycles}, taps enviados: {loop.taps_sent}.")
                return 0
            time.sleep(args.poll)
        print(f"\nLimite de {args.max_frames} frames alcanzado. Vueltas: "
              f"{loop.cycles}, taps: {loop.taps_sent}.")
        return 0
    except KeyboardInterrupt:
        print(f"\nInterrumpido. Vueltas: {loop.cycles}, taps: {loop.taps_sent}.")
        return 130
    finally:
        log.close()
        print(f"Registro: {log_dir / 'events.jsonl'}")


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--adb", default=bot.ADB_DEFAULT)
    parser.add_argument("--serial", default=bot.SERIAL_DEFAULT)
    sub = parser.add_subparsers(dest="command", required=True)

    take = sub.add_parser("capture", help="guardar capturas de una pantalla")
    take.add_argument("--loop", default="dungeon")
    take.add_argument("--state", required=True)
    take.add_argument("--count", type=int, default=4)
    take.add_argument("--interval", type=float, default=1.0)
    take.set_defaults(func=capture)

    teach = sub.add_parser("learn", help="construir el perfil desde capturas")
    teach.add_argument("--loop", default="dungeon")
    teach.add_argument("--tap", action="append", default=[],
                       metavar="ESTADO=X,Y",
                       help="punto de tap en pixeles de la captura o en 0..1")
    teach.add_argument("--start", action="append", default=[],
                       help="pantalla que inicia una vuelta")
    teach.add_argument("--cycle", action="append", default=[],
                       help="pantalla cuya llegada cuenta una vuelta")
    teach.add_argument("--needs-session", action="append", default=[],
                       help="pantalla que solo se toca si abrimos la vuelta")
    teach.add_argument("--stop", action="append", default=[],
                       help="pantalla que termina el loop (coste en rojo...)")
    teach.add_argument("--taps-max", type=int, default=2)
    teach.add_argument("--settle", type=float, default=.6)
    teach.add_argument("--retry", type=float, default=2.0)
    teach.add_argument("--inactivity", type=float, default=20.0)
    teach.add_argument("--session-timeout", type=float, default=300.0)
    teach.add_argument("--cycles", type=int, default=None)
    teach.set_defaults(func=learn)

    for name, function, help_text in (
            ("watch", watch, "simulacion: reconoce y explica, no toca"),
            ("run", run, "ejecuta el loop")):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("--loop", default="dungeon")
        command.add_argument("--cycles", type=int, default=None)
        command.add_argument("--poll", type=float, default=1.0)
        command.add_argument("--dry-run", action="store_true")
        command.add_argument("--adopt-session", action="store_true",
                             help="adoptar UNA vuelta ya en pantalla al "
                                  "arrancar (destraba un relanzamiento "
                                  "sobre una pantalla de recompensa)")
        command.add_argument("--max-frames", type=int, default=None,
                             help="parar despues de N frames (pruebas)")
        command.set_defaults(func=function)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
