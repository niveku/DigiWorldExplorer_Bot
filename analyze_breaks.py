#!/usr/bin/env python3
"""Aggregate pyramid-break and dash statistics from events.jsonl run logs.

Reads every runs/<id>/events.jsonl produced by auto_digiworld_batch2.py and
reports drop rates for destroyed pyramids, HUD energy deltas around dashes,
and an estimated Data-Shard spend per action type.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


# Data-Shard shop prices: 2000 buys 50 stamina steps, 200 one attack, 400 one dash.
SHARD_COSTS = {"move": 40, "attack": 200, "dash": 400}
Z_95 = 1.959963984540054


def wilson_interval(successes, total, z=Z_95):
    """95% Wilson score interval for a binomial proportion."""
    if total == 0:
        return (0.0, 1.0)
    phat = successes / total
    denom = 1 + z * z / total
    center = (phat + z * z / (2 * total)) / denom
    half = z * math.sqrt(phat * (1 - phat) / total + z * z / (4 * total * total)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def _collect_counter_deltas(dest, before, after):
    """Append after-minus-before per counter when both reads are known."""
    before, after = before or {}, after or {}
    for key, deltas in dest.items():
        if before.get(key) is not None and after.get(key) is not None:
            deltas.append(after[key] - before[key])


def aggregate(events):
    stats = {
        "attacks_evaluated": 0,
        "broken": 0,
        "revealed": {"orange": 0, "pink": 0, "green": 0, "none": 0},
        "dashes": 0,
        "dash_pyramids": 0,
        "dash_energy_deltas": [],
        "attack_inventory_deltas": [],
        "dash_attack_deltas": [],
        "dash_dash_deltas": [],
        "attack_counter_deltas": {"steps": [], "attacks": [], "dashes": [],
                                  "green_tickets": [], "purple_tickets": []},
        "dash_counter_deltas": {"steps": [], "attacks": [], "dashes": [],
                                "green_tickets": [], "purple_tickets": []},
        "actions": {"move": 0, "attack": 0, "dash": 0},
        "shards_estimate": 0,
    }
    for event in events:
        result = event.get("pyramid_result")
        if result:
            stats["attacks_evaluated"] += 1
            if result["broken"]:
                stats["broken"] += 1
                stats["revealed"][result["revealed"] or "none"] += 1
            before, after = result.get("attacks_before"), result.get("attacks_after")
            if before is not None and after is not None:
                stats["attack_inventory_deltas"].append(after - before)
            _collect_counter_deltas(stats["attack_counter_deltas"],
                                    result.get("counters_before"),
                                    result.get("counters_after"))
        dash = event.get("dash_result")
        if dash:
            stats["dashes"] += 1
            stats["dash_pyramids"] += dash.get("pyramids_in_path", 0)
            if dash.get("energy_delta") is not None:
                stats["dash_energy_deltas"].append(dash["energy_delta"])
            inv_before = dash.get("inventory_before") or {}
            inv_after = dash.get("inventory_after") or {}
            for key, dest in (("attacks", "dash_attack_deltas"),
                              ("dashes", "dash_dash_deltas")):
                if inv_before.get(key) is not None and inv_after.get(key) is not None:
                    stats[dest].append(inv_after[key] - inv_before[key])
            _collect_counter_deltas(stats["dash_counter_deltas"], inv_before, inv_after)
        action = event.get("action")
        if isinstance(action, list):
            for sent in action:
                kind = sent.get("type")
                if kind in stats["actions"]:
                    stats["actions"][kind] += 1
                    stats["shards_estimate"] += SHARD_COSTS[kind]
    return stats


def iter_events(paths):
    for path in paths:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("dirs", nargs="*", default=["runs", "outputs"],
                   help="run directories to scan for events.jsonl")
    args = p.parse_args()

    files = []
    for name in args.dirs:
        base = Path(name)
        if base.exists():
            files.extend(sorted(base.glob("**/events.jsonl")))
    if not files:
        print("Sin datos: no se encontró ningún events.jsonl en", ", ".join(args.dirs))
        return 1

    stats = aggregate(iter_events(files))

    print(f"Runs analizados: {len(files)}")
    print()
    print("— Ataques (garra) —")
    print(f"  Evaluados: {stats['attacks_evaluated']} | Pirámides rotas: {stats['broken']}")
    revealed = stats["revealed"]
    drops = revealed["orange"] + revealed["pink"] + revealed["green"]
    print(f"  Drops revelados: naranja {revealed['orange']}, lila {revealed['pink']}, "
          f"verde {revealed['green']}, nada {revealed['none']}")
    if stats["broken"]:
        low, high = wilson_interval(drops, stats["broken"])
        rate = drops / stats["broken"]
        print(f"  P(drop | pirámide rota): {rate:.1%} (IC95% {low:.1%}–{high:.1%}, "
              f"n={stats['broken']})")
    print()
    print("— Dashes (kameha) —")
    print(f"  Dashes: {stats['dashes']} | Pirámides en trayectoria: {stats['dash_pyramids']}")
    deltas = stats["dash_energy_deltas"]
    if deltas:
        mean = sum(deltas) / len(deltas)
        print(f"  Δ energía HUD conocido en {len(deltas)} dash(es): media {mean:+.1f} "
              f"(valores: {deltas})")
    else:
        print("  Δ energía HUD: sin lecturas fiables todavía")
    print()
    print("— Drops de consumibles (deltas de inventario HUD) —")
    attack_deltas = stats["attack_inventory_deltas"]
    if attack_deltas:
        drops = [delta + 1 for delta in attack_deltas]  # each attack consumes one garra
        print(f"  Garras alrededor de ataques (n={len(attack_deltas)}): "
              f"drops netos {sum(drops):+d} (deltas {attack_deltas})")
    else:
        print("  Garras alrededor de ataques: sin lecturas todavía")
    if stats["dash_attack_deltas"] or stats["dash_dash_deltas"]:
        print(f"  Alrededor de dashes: garras {stats['dash_attack_deltas']}, "
              f"dashes {stats['dash_dash_deltas']} (un dash consume 1)")
    else:
        print("  Alrededor de dashes: sin lecturas todavía")
    for label, deltas in (("ataques", stats["attack_counter_deltas"]),
                          ("dashes", stats["dash_counter_deltas"])):
        tickets = {key: value for key, value in deltas.items()
                   if key in ("green_tickets", "purple_tickets", "steps") and value}
        if tickets:
            print(f"  Tickets/pasos alrededor de {label}: "
                  + ", ".join(f"{key} {value}" for key, value in tickets.items()))
    print()
    print("— Gasto estimado (Data Shards) —")
    actions = stats["actions"]
    print(f"  Movimientos: {actions['move']} ×{SHARD_COSTS['move']} | "
          f"Ataques: {actions['attack']} ×{SHARD_COSTS['attack']} | "
          f"Dashes: {actions['dash']} ×{SHARD_COSTS['dash']}")
    print(f"  Total estimado: {stats['shards_estimate']:,} shards".replace(",", "."))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
