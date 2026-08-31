<div align="center">

# ⚡ DigiWorldExplorer_Bot ⚡

![Version](https://img.shields.io/badge/version-0.5.1-yellow) ![Status](https://img.shields.io/badge/status-beta-orange) ![Platform](https://img.shields.io/badge/platform-Windows-blue) ![Tests](https://img.shields.io/badge/tests-passing-green)

[Español](README.md) · **English**

### 🦖 Automated DigiWorld exploration for Digimon UP

**✨ Fork by [Niveku](https://github.com/niveku) · base by [RobinTh0r](https://github.com/RobinTh0r/DigiWorldExplorer_Bot) ✨**

`Local` · `Deterministic` · `ADB only` · `No cloud AI`

</div>

> [!WARNING]
> A fan project, unaffiliated with the developers of Digimon UP. Automating the game may break their rules. Use it at your own risk.

> [!IMPORTANT]
> **This repository is a fork.** The base is RobinTh0r's, published in July 2026; everything on top of it belongs to this fork. What changed is in [`docs/UPSTREAM.md`](docs/UPSTREAM.md); authorship and licence status (the original **declares no licence**) in [`NOTICE.md`](NOTICE.md).

> [!NOTE]
> 🔗 The original author's sister project: [DigiWorldExplorer_Android_Bot](https://github.com/RobinTh0r/DigiWorldExplorer_Android_Bot), the native Android port, no PC or BlueStacks needed.

> [!NOTE]
> The bot's terminal interface is in **Spanish**: prompts, progress lines and the final report. Everything else here works the same either way.

## 🌟 What it does

It plays DigiWorld for you. It looks at the 5×5 board, decides where to go and taps the screen.

It goes for what pays best, in this order:

1. 🟠 energy
2. 🟣 purple and 🟢 green items on the way
3. ➡️ move right
4. 🔺 walk around a pyramid or break it
5. 💨 dash only when two pyramids stand in a row

It also grinds the screens that repeat on their own, dungeons and lost sector, through `LOOP.cmd`.

## 🛡️ Safety

- It takes a fresh capture before every decision.
- If the grid, the player or an overlay look unclear, it waits or stops.
- `CHECK.cmd` only watches: it never taps.
- `Ctrl+C` stops it at once.
- Nothing leaves your PC. No cloud, no accounts, no telemetry.

## 🚀 Getting started

You need Windows 10 or 11, BlueStacks 5, Digimon UP and Python 3.10 or newer. If Python is missing, `INSTALL.cmd` offers to install it with `winget`, and installs nothing without your confirmation.

### BlueStacks

| Setting | Value |
|---|---:|
| Orientation | Portrait |
| Resolution | 720 × 1280 |
| Density | 240 DPI |
| Interface scaling | 100 % |
| Android Debug Bridge | Enabled |

> [!TIP]
> In this beta **Botamon** is detected most reliably: a small sprite in a sharp colour. Other Digimon work, but they are less calibrated.

### Steps

1. Download or clone the repository.
2. Double-click `INSTALL.cmd`.
3. Open BlueStacks and enter DigiWorld.
4. Run `CHECK.cmd` and look at the image in `runs/checks/`: the green grid must frame the 25 cells.
5. Run `START.cmd`.

## 🎮 Using it

`START.cmd` asks how many actions you want and **quotes the run before touching anything**: how many paws, garras and dashes it costs, what you are carrying, and whether it is enough. Type another number and it quotes again. Enter starts, `n` cancels.

The bot sets its own waits from what the game animates, and stretches them when the device swallows taps. During the run you get progress every 2 %. At the end: total time, energy gained, energy per minute and projected per hour, and how many taps the game charged against the ones you asked for.

`LOOP.cmd` grinds repeating screens. Pick a profile, it checks for 12 seconds that it recognises what is on screen, then it runs. Two profiles ship ready, `lost_sector` and `dungeon`. Teaching it a new one takes six captures and one command: [`SCREEN_LOOPS.md`](SCREEN_LOOPS.md).

```powershell
.\LOOP.cmd -Loop lost_sector -Yes            # no questions
.\LOOP.cmd -Loop dungeon -Yes -Cycles 50     # bounded
```

### 🔧 Debug mode

**A normal run writes nothing to disk.** `START_DEBUG.cmd` and `LOOP_DEBUG.cmd` save an annotated capture per action, the safety-stop diagnostics and a record of every decision under `runs/<id>/`. It costs around 57 MB per 200 actions. Turn it on when something goes wrong and you want to report it.

## 🧯 Common problems

| Problem | Fix |
|---|---|
| Python missing | Run `INSTALL.cmd` and accept the `winget` install |
| ADB not found | Enable it in BlueStacks, **Settings → Advanced** |
| No device | Open BlueStacks fully and run `CHECK.cmd` again |
| Grid in the wrong place | Do not start. Check Portrait, 720×1280 and 240 DPI |
| Player not detected | Wait for the animation to finish and run `CHECK.cmd` again |

## 🔬 How it works

Everything goes through **ADB**, the debug channel Android already ships. The bot asks it for a screenshot and sends a tap with coordinates, the same way a finger would. It does not read game memory, patch the APK or talk to the servers: to the game, a tap from the bot and a tap from you are the same thing. That is why it is slow compared to a cheat, and why there is nothing to patch.

Nothing is pinned to the Windows window. In every capture the bot **finds the grid** and works out everything relative to it, so you can move BlueStacks around the desktop without breaking anything.

```text
ADB capture → find the 5×5 board → read player, items and pyramids
   → pick the safest action → ADB tap → check the game charged it
```

With items in sight it plans two actions before looking again; with none, three. An attack or a dash always forces a fresh capture.

Two decisions hold up the rest:

- **The HUD counter outranks faith.** The game either charges the tap or it does not, and that is how you know the belt moved. The bot believes the counter, not the fact that it sent a tap.
- **The board is memory, not a photograph.** Every cell is a track with a history: how often it was seen, where it came from, whether it can be trusted. A short animation no longer makes it forget an energy it has been looking at for a while.

The offline tests run against real captures of the game, and `replay_harness.py` turns every recorded run into a regression case. How many there are is in [`docs/UPSTREAM.md`](docs/UPSTREAM.md).

## 📂 Files

| File | Purpose |
|---|---|
| `INSTALL.cmd` · `Setup.ps1` | Install and local environment |
| `CHECK.cmd` · `Check-Setup.ps1` | Diagnostics without sending taps |
| `START.cmd` · `START_DEBUG.cmd` | The explorer, quiet or with a record |
| `LOOP.cmd` · `LOOP_DEBUG.cmd` | Screen loops, see [`SCREEN_LOOPS.md`](SCREEN_LOOPS.md) |
| `digiworld_bot.py` | ADB, captures, grid and taps |
| `auto_digiworld.py` | Player, item and pyramid detection |
| `auto_digiworld_batch2.py` | Planning and safety control |
| `world_model.py` · `step_ledger.py` | Board memory and the game's receipt |
| `replay_harness.py` · `tests/` | Regression over recorded runs |
| `screen_loop.py` · `screen_loops.py` | Loop engine and CLI |

## 📦 Why not a portable executable?

Bundling Python, NumPy and Pillow whole would make the release enormous. Instead `INSTALL.cmd` creates a local `.venv` with two dependencies, and the environment rebuilds the same way on a new PC.

## 📝 Versions

The current version lives in `VERSION`, in the terminal banner and in `python auto_digiworld_batch2.py --version`.

**v0.5.1 (31.08.2026)**: the run quote finally splits the cost the right way. Measured over 20 runs, a run burns two dashes for every garra, and the old figures reserved almost the same of each.

**v0.5.0 (31.08.2026)**: the bot stops mistaking two things the game paints on top of the board for board content: the light marking a cell as steppable, which read as a pyramid, and the confetti of a pickup, which read as new items. It also remembers what it has already seen, spots incoming pyramids sooner and stops paying for dashes that break nothing.

Full history in [`docs/CHANGELOG.md`](docs/CHANGELOG.md), in Spanish. The defect diary with the evidence behind each fix is in [`docs/`](docs/).

## 🔗 Related projects

| Project | Platform |
|---|---|
| [RobinTh0r/DigiWorldExplorer_Bot](https://github.com/RobinTh0r/DigiWorldExplorer_Bot) (original) | Windows + BlueStacks |
| [RobinTh0r/DigiWorldExplorer_Android_Bot](https://github.com/RobinTh0r/DigiWorldExplorer_Android_Bot) | Native Android |

---
<div align="center">

## ⚒️ Niveku × Gatomon 🦖

**✨ Fork maintained by [Niveku](https://github.com/niveku) · original base by [RobinTh0r](https://github.com/RobinTh0r) ✨**

*Explore smart. Stop safe. Collect everything.*

</div>
