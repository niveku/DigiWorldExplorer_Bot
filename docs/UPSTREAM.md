# Qué cambió respecto al proyecto original

Trazabilidad del fork. El historial de git es la fuente de verdad; esto es
el resumen legible.

- **Base**: [RobinTh0r/DigiWorldExplorer_Bot](https://github.com/RobinTh0r/DigiWorldExplorer_Bot),
  último commit del autor original `d7d8548` (2026-07-31).
- **Este fork**: 169 commits encima, +23.093 / −484 líneas en 76 archivos.
- Para ver exactamente la diferencia:

  ```bash
  git remote add upstream https://github.com/RobinTh0r/DigiWorldExplorer_Bot.git
  git fetch upstream
  git log --oneline upstream/main..HEAD     # los 169 commits
  git diff --stat upstream/main..HEAD       # el alcance
  ```

## Lo que ya venía del original

Detección automática de la cuadrícula 5×5 por ADB, exploración con
prioridades (naranjas, items, derecha, pirámides, dash), paradas de
seguridad ante tablero u overlay dudoso, los launchers de Windows
(`INSTALL.cmd`, `START.cmd`, `CHECK.cmd` y sus `.ps1`), el empaquetado con
entorno local de Python y el esquema de releases. Esa es la columna
vertebral y no la escribí yo.

## Lo que se construyó encima

**El recibo de paticas (`step_ledger.py`).** La pieza que cambió todo lo
demás. El contador de paticas del HUD es la autoridad sobre lo que el juego
cobró: si no cobró, el tap no existió. Antes el bot creía en sus propios
taps, y de esa fe salían casi todos los desincronismos. Orden de autoridad:
recibo → píxeles → suposición.

**Física de la banda transportadora.** La cuadrícula es mobiliario fijo; lo
que se mueve es su contenido, y avanza exactamente una columna cuando un
paso COBRADO lleva al jugador de la columna 1 a la 2. Toda la memoria del
mundo (items recordados, obstáculos fantasma, vetos, baneos) se desplaza con
esa regla en vez de con un heurístico de píxeles.

**Modelo del mundo (`world_model.py`).** Las celdas dejaron de re-juzgarse
cada frame: ahora son pistas con identidad, clasificadas por su ORIGEN al
nacer. Un item que entra por el borde derecho está explicado y se cree en el
acto; lo que nace sin explicación (confeti de recogida) queda en sospecha.

**Harness de replay (`replay_harness.py`).** Cada corrida guardada se vuelve
un test de regresión de punta a punta: reproduce los PNG reales y audita
invariantes — GHOST, PLAYER-LAW, STARVATION, BLIND-TOUR, PING-PONG,
INDECISION, BACKSTEP. Es lo que permite arreglar un defecto de planificación
y comprobar contra footage real que no volvió.

**Planificación con economía medida.** Un tour sobre todos los pickups en
vez de rescates de pánico; precios reales (paso 40 fragmentos, garra 200,
dash 400) y presupuestos de scroll para no erosionar lo perecedero; vetos de
retroceso respaldados por el recibo.

**Ritmo adaptativo.** Las esperas entre taps responden al aparato: cada tap
tragado estira el ritmo, cada frame limpio lo relaja hasta la base medida.

**Suite de tests.** 668 tests (`python -m unittest discover -s tests`), con
fixtures de capturas reales del juego.

**Lanzador.** Estimación de recursos antes de tocar nada (dice cuántas
paticas, garras y dashes cuesta el run planeado y si alcanzan), interfaz en
español, y el arreglo del prompt que cancelaba respondiera lo que
respondiera.

## Diario de trabajo

Los `docs/review-*.md` son el registro
durable: cada defecto encontrado en corridas en vivo, la evidencia que lo
probó, el arreglo, y también lo que se intentó y se **descartó con
medición** (un candado de fila que causó un bloqueo nuevo, un atajo de
espera que la telemetría demostró inútil).
