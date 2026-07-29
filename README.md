<div align="center">

# ⚡ DigiWorldExplorer_Bot ⚡

![Version](https://img.shields.io/badge/version-0.2.0-yellow) ![Status](https://img.shields.io/badge/status-beta-orange) ![Platform](https://img.shields.io/badge/platform-Windows-blue)

### 🦖 Automatisierte DigiWorld-Erkundung für Digimon UP

**✨ RobinTh0r Guild Edition · Exclusive for Germon Members ✨**

`Lokal` · `Deterministisch` · `ADB-only` · `Keine Cloud-KI` · `Safety first`

</div>

> [!WARNING]
> Dieses private Fanprojekt ist nicht mit den Entwicklern von Digimon UP verbunden. Spielautomatisierung kann gegen Spielregeln verstoßen. Nutzung ausschließlich auf eigene Verantwortung und ohne Gewährleistung.

## 🌟 Was macht der Bot?

Der DigiWorldExplorer_Bot beobachtet das Spielfeld direkt über Android Debug Bridge (ADB), erkennt das sichtbare **5×5-Raster** und plant sichere Bewegungen. Alle Eingaben werden relativ zum automatisch erkannten Spielfeld berechnet – unabhängig davon, wo das BlueStacks-Fenster auf dem Desktop liegt.

Der Bot versucht möglichst lange zu erkunden und priorisiert dabei:

1. 🟠 orange Teile
2. 🟣 lilane und 🟢 grüne Items auf sinnvollen Wegen
3. ➡️ sichere Erkundung nach rechts
4. 🔺 Umwege oder Angriffe bei Pyramiden
5. 💨 Dash nur bei mindestens zwei direkt aufeinanderfolgenden Hindernissen

## 🛡️ Sicherheitsprinzip

- 📸 Vor Entscheidungen wird ein neuer ADB-Screenshot ausgewertet.
- 🧭 Keine festen Windows-, Maus- oder Fensterkoordinaten.
- 🛑 Bei unklarem Raster, Overlay oder unsicherer Spielererkennung wird gewartet oder gestoppt.
- 🔁 Nach Angriffen, Dash und Animationen wird erneut geprüft.
- 🚫 Ein wirkungsloser Angriff oder Dash wird für den restlichen Lauf deaktiviert.
- 👁️ `CHECK.cmd` ist reiner Beobachtungsmodus und sendet garantiert keine Taps.
- ☁️ Keine Cloud-API und kein KI-Modell während der Laufzeit.

## 🚀 Schnellstart

### Voraussetzungen

- Windows 10 oder 11
- BlueStacks 5
- Digimon UP
- Python 3.10 oder neuer

Fehlt Python, fragt `INSTALL.cmd`, ob **Python 3.12 über `winget`** installiert werden darf. Ohne Bestätigung wird nichts installiert.

### BlueStacks einstellen

| Einstellung | Empfohlener Wert |
|---|---:|
| Ausrichtung | Portrait |
| Auflösung | 720 × 1280 |
| Pixeldichte | 240 DPI |
| Interface-Skalierung | 100 % |
| Android Debug Bridge | Aktiviert |

> [!TIP]
> **Empfehlung für den Betatest:** Verwendet möglichst **Botamon**. Sein kleiner,
> farblich klarer Sprite lässt sich aktuell am zuverlässigsten erkennen. Andere
> Digimon-Formen können funktionieren, sind in dieser Beta aber noch nicht gleich
> gut kalibriert.

### Installation und Start

1. Repository herunterladen oder klonen.
2. `INSTALL.cmd` doppelklicken.
3. BlueStacks starten und DigiWorld vollständig öffnen.
4. `CHECK.cmd` ausführen – dabei erfolgen **keine Eingaben**.
5. Diagnosebild unter `runs/checks/` prüfen: Das grüne Raster muss alle 25 Felder korrekt umrahmen.
6. `START.cmd` ausführen.

## 🎮 Interaktiver Start

`START.cmd` fragt zuerst nach der Aktionszahl und danach nur kurz, ob experimentelle Einstellungen verwendet werden sollen. Standard ist `N`: Der Bot startet sofort mit dem sicheren Intervall `0,50 Sekunden` und ohne Debugbilder. Nur bei `J` werden Intervall und Diagnosebilder zusätzlich abgefragt. Nach Laufende kann direkt ein weiterer Lauf gestartet werden; dabei beginnt die Abfrage wieder bei der Schrittzahl.

Das Mindestintervall ist aus Sicherheitsgründen auf `0,35 Sekunden` begrenzt. Mit `Ctrl+C` kann der Bot jederzeit sofort gestoppt werden. Im normalen Modus erscheint ungefähr alle 2 % ein kompaktes Update mit Fortschritt, Laufzeit und geschätzter Restzeit. Am Ende folgen Gesamtzeit, Energie-Startwert, Endwert, echte Differenz sowie Energie pro Minute und hochgerechnet pro Stunde. Zusätzlich bleibt die interne Zählung der erkannten und gezielt betretenen Items sichtbar. Kann der HUD-Zähler nicht sicher gelesen werden, wird ausdrücklich **nicht sicher lesbar** angezeigt.

### 🔧 Debugmodus

`START_DEBUG.cmd` aktiviert Diagnosebilder und zeigt bei jedem Scan beziehungsweise jeder Neuplanung eine kompakte Statuszeile, zum Beispiel `10/100: Energie gesichtet! Route wird neu berechnet`. Die vollständigen Maschinendaten stehen weiterhin in `runs/<Lauf-ID>/events.jsonl`.

## 🧠 Entscheidungsablauf

```text
ADB-Screenshot
      ↓
5×5-Spielfeld automatisch erkennen
      ↓
Spieler, Items, Wege und Pyramiden bewerten
      ↓
Sicherste Aktion relativ zum Raster wählen
      ↓
ADB-Tap senden
      ↓
Wirkung und neuen Zustand erneut prüfen
```

Bei sichtbaren Items plant der Controller höchstens zwei Aktionen bis zum nächsten Screenshot. Ohne sichtbares Item sind bis zu drei sichere Aktionen möglich. Angriff und Dash erzwingen immer sofort eine neue Prüfung.

## 📂 Übersichtliche Projektstruktur

| Datei | Aufgabe |
|---|---|
| `INSTALL.cmd` | Einfache Installation starten |
| `CHECK.cmd` | ADB und Raster ohne Eingaben prüfen |
| `START.cmd` | Ruhigen, gebrandeten Botmodus starten |
| `START_DEBUG.cmd` | Entwicklerlauf mit Status je Scan und Diagnosebildern |
| `Setup.ps1` | Python prüfen und lokale Umgebung einrichten |
| `Check-Setup.ps1` | Sicheren Diagnosemodus ausführen |
| `Start-Bot.ps1` | Startoptionen abfragen und Lauf starten |
| `digiworld_bot.py` | ADB, Screenshots, Rastererkennung und Taps |
| `auto_digiworld.py` | Spieler-, Item- und Hinderniserkennung |
| `auto_digiworld_batch2.py` | Adaptive Planung und Sicherheitskontrolle |
| `tests/test_core.py` | Offline-Regressionstests ohne Spieleingaben |
| `requirements.txt` | Minimale Python-Abhängigkeiten |

## 📦 Warum kein riesiges Portable-Paket?

Python, NumPy und Pillow vollständig mitzuliefern wäre technisch möglich, würde das Release aber deutlich größer und wartungsintensiver machen. Stattdessen bleibt der Download klein:

- `INSTALL.cmd` erzeugt lokal eine `.venv`.
- Nur NumPy und Pillow werden installiert.
- `.venv`, Screenshots, Logs und Entwicklungsdaten landen niemals in Git.
- Auf einem neuen PC wird die Umgebung reproduzierbar neu aufgebaut.

## 🧪 Offline testen

Nach erfolgreicher Installation:

```powershell
.\.venv\Scripts\python.exe -m py_compile digiworld_bot.py auto_digiworld.py auto_digiworld_batch2.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Diese Tests senden keine ADB-Eingaben.

## 🧯 Häufige Probleme

| Problem | Lösung |
|---|---|
| Python fehlt | `INSTALL.cmd` starten und die optionale `winget`-Installation bestätigen |
| ADB nicht gefunden | In BlueStacks unter **Einstellungen → Erweitert** ADB aktivieren |
| Kein Gerät gefunden | BlueStacks vollständig starten und danach `CHECK.cmd` erneut ausführen |
| Raster sitzt falsch | Nicht starten; Portrait, 720×1280 und 240 DPI kontrollieren |
| Spieler wird nicht erkannt | Animation abwarten und `CHECK.cmd` erneut ausführen |

## 📝 Versionen und Changelog

Die aktuelle Version steht in `VERSION` und wird im Terminalbanner sowie über
`python auto_digiworld_batch2.py --version` angezeigt.

### Unreleased

- Noch keine Änderungen.

### v0.2.0 – 29.07.2026

- 🟢 Der normale Start zeigt etwa alle 2 % Fortschritt, Laufzeit und geschätzte Restzeit.
- 📊 Am Laufende erscheinen Gesamtzeit sowie Energie-Start, -Ende und echte Differenz.
- 🔎 Die Energie-Ziffernerkennung arbeitet lokal und verwirft unsichere Werte.
- 🚀 Nach der Schrittzahl startet der sichere Standard mit nur einer kurzen Experimental-Abfrage.
- 🔁 Nach Laufende kann direkt ein weiterer Lauf mit neuer Schrittzahl gestartet werden.
- ⚡ Die Abschlussstatistik zeigt Energie pro Minute und hochgerechnet pro Stunde.

### v0.1.0 – 29.07.2026

- 🧭 Automatische Erkennung des sichtbaren 5×5-DigiWorld-Rasters
- 🟠 Priorisierte Sammlung von Energie und sichtbaren Items
- 🔺 Sichere Behandlung von Pyramiden, Angriffen und Dash
- 🛑 Sicherheitsstopps bei unsicherem Raster, Spieler oder Overlay
- 🔧 Separater Debugstart mit Statusmeldung bei jedem Scan und jeder Neuplanung
- ⚡ RobinTh0r-/Germon-Terminalbranding
- 📦 Schlankes Release-ZIP mit automatischer lokaler Python-Einrichtung

### Regeln für zukünftige Releases

Bei jeder neuen Version werden gemeinsam aktualisiert:

1. Versionsnummer in `VERSION`
2. Changelog in dieser README
3. Git-Tag im Format `vX.Y.Z`
4. GitHub-Release mit demselben Changelog als Release Notes
5. Neu gebautes ZIP ohne `.venv`, Laufdaten, Screenshots oder lokale Konfiguration

---
<div align="center">

## ⚒️ RobinTh0r × Agumon 🦖

**✨ Built for the guild · Exclusive for Germon Members ✨**

*Explore smart. Stop safe. Collect everything.*

</div>