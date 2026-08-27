<div align="center">

# ⚡ DigiWorldExplorer_Bot ⚡

![Version](https://img.shields.io/badge/version-0.3.0-yellow) ![Status](https://img.shields.io/badge/status-beta-orange) ![Platform](https://img.shields.io/badge/platform-Windows-blue) ![Tests](https://img.shields.io/badge/tests-607-green)

### 🦖 Exploración automatizada de DigiWorld para Digimon UP

**✨ Fork de [Niveku](https://github.com/niveku) · base de [RobinTh0r](https://github.com/RobinTh0r/DigiWorldExplorer_Bot) ✨**

`Local` · `Determinista` · `Solo ADB` · `Sin IA en la nube` · `Safety first`

</div>

> [!WARNING]
> Este proyecto privado de fans no está vinculado a los desarrolladores de Digimon UP. La automatización del juego puede violar sus reglas. Uso exclusivamente bajo tu propia responsabilidad y sin garantía.

> [!IMPORTANT]
> **Este repositorio es un fork.** La base — detección de la cuadrícula por ADB,
> exploración, launchers de Windows, empaquetado — es de
> [RobinTh0r](https://github.com/RobinTh0r/DigiWorldExplorer_Bot), que la publicó en
> julio de 2026. Encima van 127 commits míos: el recibo de paticas, el modelo del
> mundo, el harness de replay y 607 tests.
> Detalle en [`docs/UPSTREAM.md`](docs/UPSTREAM.md); autoría y estado de licencia
> — el original **no declara licencia** — en [`NOTICE.md`](NOTICE.md).

> [!NOTE]
> 🔗 Proyecto hermano del autor original: [DigiWorldExplorer_Android_Bot](https://github.com/RobinTh0r/DigiWorldExplorer_Android_Bot)
> es el port nativo a Android – corre directo en el dispositivo sin PC, BlueStacks ni ADB.

## 🌟 ¿Qué hace el bot?

El DigiWorldExplorer_Bot observa el tablero directamente por Android Debug Bridge (ADB), reconoce la **cuadrícula 5×5** visible y planifica movimientos seguros. Todas las entradas se calculan relativas al tablero detectado automáticamente – sin importar dónde esté la ventana de BlueStacks en el escritorio.

El bot intenta explorar el mayor tiempo posible y prioriza:

1. 🟠 piezas naranjas
2. 🟣 items lilas y 🟢 verdes en rutas que valgan la pena
3. ➡️ exploración segura hacia la derecha
4. 🔺 desvíos o ataques ante pirámides
5. 💨 dash solo con al menos dos obstáculos directamente consecutivos

## 🛡️ Principio de seguridad

- 📸 Antes de cada decisión se evalúa un screenshot ADB nuevo.
- 🧭 Sin coordenadas fijas de Windows, ratón ni ventana.
- 🛑 Con cuadrícula dudosa, overlay o detección insegura del jugador se espera o se detiene.
- 🔁 Tras ataques, dash y animaciones se vuelve a verificar.
- 🚫 Un ataque o dash sin efecto queda desactivado por el resto del run.
- 👁️ `CHECK.cmd` es modo de solo observación y garantiza que no envía taps.
- ☁️ Sin API en la nube ni modelo de IA durante la ejecución.

## 🚀 Inicio rápido

### Requisitos

- Windows 10 u 11
- BlueStacks 5
- Digimon UP
- Python 3.10 o superior

Si falta Python, `INSTALL.cmd` pregunta si puede instalar **Python 3.12 vía `winget`**. Sin confirmación no se instala nada.

### Configurar BlueStacks

| Ajuste | Valor recomendado |
|---|---:|
| Orientación | Portrait |
| Resolución | 720 × 1280 |
| Densidad de píxeles | 240 DPI |
| Escalado de interfaz | 100 % |
| Android Debug Bridge | Activado |

> [!TIP]
> **Recomendación para la beta:** usa en lo posible **Botamon**. Su sprite pequeño
> y de color nítido es hoy el que se detecta con más fiabilidad. Otras formas de
> Digimon pueden funcionar, pero en esta beta aún no están igual de bien calibradas.

### Instalación e inicio

1. Descarga o clona el repositorio.
2. Doble clic en `INSTALL.cmd`.
3. Inicia BlueStacks y abre DigiWorld por completo.
4. Ejecuta `CHECK.cmd` – no envía **ninguna entrada**.
5. Revisa la imagen de diagnóstico en `runs/checks/`: la cuadrícula verde debe enmarcar correctamente las 25 celdas.
6. Ejecuta `START.cmd`.

## 🎮 Inicio interactivo

`START.cmd` pregunta cuántas acciones debe ejecutar el bot y luego **cotiza el run
antes de tocar nada**: lee el HUD y dice cuántas paticas, garras y dashes cuesta lo
que pediste, cuánto tienes y si alcanza. Se puede teclear otro número ahí mismo y
vuelve a cotizar; Enter o `s` arranca, `n` cancela. Al terminar puede lanzarse otro run.

Los tiempos entre acciones ya no se preguntan: los fija el propio bot según lo que el
juego anima, y se estiran solos cuando el aparato se traga taps. Con `Ctrl+C` se
detiene de inmediato. En modo normal aparece cada 2 % una actualización compacta con
progreso, tiempo transcurrido y restante. Al final se muestran el tiempo total, la
energía inicial y final, la diferencia real, la energía por minuto y proyectada por
hora, y una línea de eficiencia: taps cobrados contra reclamados, esperas, segundos
por acción y energía por patica. Si el contador del HUD no puede leerse con certeza,
se indica explícitamente **no legible con certeza**.

### 🔧 Modo debug

**Un run normal no escribe nada en disco.** Ni capturas, ni diagnósticos, ni
registro: `START.cmd` y `LOOP.cmd` sólo dejan lo que ves en la terminal.

`START_DEBUG.cmd` y `LOOP_DEBUG.cmd` encienden lo demás. El bot crea entonces
`runs/<id-del-run>/` con `events.jsonl` (una línea por decisión), una captura
anotada por acción, los diagnósticos de las paradas de seguridad y las dos
imágenes finales. Además imprime una línea de estado en cada escaneo, del tipo
`10/100: ¡Energía a la vista! Recalculando ruta`.

Cuenta unos 57 MB por cada 200 acciones. Enciéndelo cuando algo vaya mal y
quieras diagnosticarlo, o cuando quieras convertir el run en un caso de
regresión: `replay_harness.py` y `tests/test_replay.py` se alimentan de esas
carpetas.

| | `START.cmd` / `LOOP.cmd` | `START_DEBUG.cmd` / `LOOP_DEBUG.cmd` |
|---|---|---|
| Capturas y diagnósticos | no | sí |
| `events.jsonl` | no | sí |
| Estado por escaneo | cada 2 % | cada escaneo |

## 🔁 Loops de pantalla

Un dungeon que se repite es una secuencia de cuatro pantallas: oferta,
batalla, recompensa, oferta otra vez. `LOOP.cmd` las recorre. Tiene entrada
propia porque las preguntas del explorador (cuántas acciones, cuánto cuesta)
no significan nada aquí.

Doble clic en **`LOOP.cmd`**: eliges el perfil (sólo pregunta si hay más de
uno), comprueba durante 12 s que reconoce lo que hay en pantalla y te hace
**una** pregunta, `Arrancar [S/n]`. Corre sin límite de vueltas hasta que lo
pares con `Ctrl+C`.

```powershell
.\LOOP.cmd -Loop lost_sector -Yes            # sin preguntas
.\LOOP.cmd -Loop dungeon -Yes -Cycles 50     # acotado
```

Vienen dos perfiles: `lost_sector` y `dungeon`, que cubre los tres tipos que
el juego rota (Attack, Defense y SP Type). Ninguno trae constantes de píxeles.
Cada loop **aprende** las pantallas de capturas que tomas en tu propio
BlueStacks, así que enseñarle uno nuevo son seis capturas y un comando:
[`SCREEN_LOOPS.md`](SCREEN_LOOPS.md) lo explica, junto con las reglas de
seguridad y lo que rinde cada modo.

`LOOP_DEBUG.cmd` hace lo mismo guardando el registro de cada frame.

## 🧠 Flujo de decisión

```text
Screenshot ADB
      ↓
Detectar automáticamente el tablero 5×5
      ↓
Evaluar jugador, items, rutas y pirámides
      ↓
Elegir la acción más segura relativa a la cuadrícula
      ↓
Enviar tap ADB
      ↓
Verificar el efecto y el nuevo estado
```

Con items visibles el controlador planifica como máximo dos acciones hasta el siguiente screenshot. Sin item visible son posibles hasta tres acciones seguras. Ataque y dash fuerzan siempre una verificación inmediata.

## 📂 Estructura del proyecto

| Archivo | Función |
|---|---|
| `INSTALL.cmd` | Iniciar la instalación simple |
| `CHECK.cmd` | Verificar ADB y cuadrícula sin enviar entradas |
| `START.cmd` | Iniciar el modo bot tranquilo con branding |
| `START_DEBUG.cmd` | Lo mismo que `START.cmd`, guardando capturas, diagnósticos y `events.jsonl` |
| `LOOP.cmd` | Loops de pantalla repetible (dungeon, defensa, invocación); ver `SCREEN_LOOPS.md` |
| `LOOP_DEBUG.cmd` | Lo mismo que `LOOP.cmd`, guardando el registro de cada frame |
| `Setup.ps1` | Verificar Python y preparar el entorno local |
| `Check-Setup.ps1` | Ejecutar el modo de diagnóstico seguro |
| `Start-Bot.ps1` | Preguntar opciones de inicio y lanzar el run |
| `Start-Loop.ps1` | Elegir perfil de loop, simular y luego ejecutarlo |
| `NivekuBanner.ps1` | El banner que comparten los dos lanzadores |
| `digiworld_bot.py` | ADB, screenshots, detección de cuadrícula y taps |
| `auto_digiworld.py` | Detección de jugador, items y obstáculos |
| `auto_digiworld_batch2.py` | Planificación adaptativa y control de seguridad |
| `step_ledger.py` | El recibo del juego: qué taps cobró y cuánto avanzó la banda |
| `world_model.py` | Pistas con identidad: qué se cree, qué se sospecha y por qué |
| `replay_harness.py` | Convierte corridas guardadas en tests de regresión con invariantes |
| `analyze_breaks.py` | Análisis offline de los logs de corridas |
| `screen_loop.py` | Motor de los loops: reconocer pantalla, decidir, contar vueltas |
| `screen_loops.py` | CLI de los loops: capturar, aprender, simular, ejecutar |
| `safe_tap.py` | Variación acotada del punto y el ritmo de cada tap |
| `overlays.py` | Quién manda en el frame cuando algo tapa el tablero |
| `SCREEN_LOOPS.md` | Cómo se enseña, se lanza y se acota un loop |
| `tests/` | 607 tests offline, con fixtures de capturas reales |
| `requirements.txt` | Dependencias mínimas de Python |

## 📦 ¿Por qué no un paquete portable gigante?

Empaquetar Python, NumPy y Pillow completos sería técnicamente posible, pero haría el release mucho más grande y difícil de mantener. En su lugar la descarga se mantiene pequeña:

- `INSTALL.cmd` crea una `.venv` local.
- Solo se instalan NumPy y Pillow.
- `.venv`, screenshots, logs y datos de desarrollo nunca entran a Git.
- En un PC nuevo el entorno se reconstruye de forma reproducible.

## 🧪 Probar offline

Tras una instalación exitosa:

```powershell
.\.venv\Scripts\python.exe -m py_compile digiworld_bot.py auto_digiworld.py auto_digiworld_batch2.py
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

Estos tests no envían entradas ADB.

## 🧯 Problemas frecuentes

| Problema | Solución |
|---|---|
| Falta Python | Ejecutar `INSTALL.cmd` y confirmar la instalación opcional con `winget` |
| ADB no encontrado | Activar ADB en BlueStacks en **Ajustes → Avanzado** |
| Ningún dispositivo | Iniciar BlueStacks por completo y volver a ejecutar `CHECK.cmd` |
| Cuadrícula mal ubicada | No iniciar; verificar Portrait, 720×1280 y 240 DPI |
| Jugador no detectado | Esperar la animación y volver a ejecutar `CHECK.cmd` |

## 📝 Versiones y changelog

La versión actual está en `VERSION` y se muestra en el banner de la terminal y con
`python auto_digiworld_batch2.py --version`.

### v0.3.0 - 27.08.2026 (fork de Niveku)

- 🧾 **Recibo de paticas**: el contador del HUD es la autoridad sobre qué taps cobró
  el juego; la banda transportadora avanza con el recibo, no con la fe en los taps.
- 🌍 **Modelo del mundo**: las celdas son pistas clasificadas por su origen, no
  juicios rehechos cada frame.
- 🔁 **Harness de replay**: cada corrida guardada es un test de punta a punta con
  invariantes (GHOST, PLAYER-LAW, STARVATION, BLIND-TOUR, PING-PONG, INDECISION).
- 💰 **Economía medida**: tour planificado sobre todos los pickups, precios reales
  (paso 40, garra 200, dash 400) y presupuestos de scroll para lo perecedero.
- ⏱️ **Ritmo adaptativo**: las esperas responden al aparato — un tap tragado las
  estira, un frame limpio las relaja.
- 💸 El lanzador cotiza el run antes de empezar y ya no cancela por error.
- 🤫 **Silencio por defecto**: un run ya no deja nada en disco. Las capturas de
  diagnóstico venían encendidas en el arranque normal (`if (-not $NoDebugShots)`),
  así que cada run escribía cientos de PNG y un log que nadie había pedido. Ahora
  eso vive en `START_DEBUG.cmd` y `LOOP_DEBUG.cmd`.
- 🔁 **Loops de pantalla** (`LOOP.cmd`): motor genérico para las pantallas que
  se repiten, con perfiles aprendidos de capturas propias. Una pantalla que otro
  proceso dejó abierta no se toca; el frame que detiene un loop se guarda.
- 🎯 **Compromiso de objetivo**: llegar al lado de un item ya no es lo que lo
  descarta. Medido sobre 857 frames: 20 de los 40 encogimientos de plan eran esa
  forma, y el A/B sobre las mismas grabaciones cambia 51 decisiones.
- 🧪 607 tests offline.
- 🗣️ Interfaz de usuario completa en español (runner, launchers PowerShell y esta README).

Diario completo de defectos y evidencia en [`docs/`](docs/).

### v0.2.0 – 29.07.2026

- 🟢 El inicio normal muestra aproximadamente cada 2 % el progreso, tiempo transcurrido y tiempo restante estimado.
- 📊 Al final del run aparecen el tiempo total y la energía inicial, final y su diferencia real.
- 🔎 El OCR de energía trabaja local y descarta valores inseguros.
- 🚀 Tras el número de acciones arranca el estándar seguro con una sola pregunta experimental breve.
- 🔁 Al terminar puede lanzarse directamente otro run con nuevo número de acciones.
- ⚡ La estadística final muestra energía por minuto y proyectada por hora.

### v0.1.0 – 29.07.2026

- 🧭 Detección automática de la cuadrícula 5×5 visible de DigiWorld
- 🟠 Recolección priorizada de energía e items visibles
- 🔺 Manejo seguro de pirámides, ataques y dash
- 🛑 Paradas de seguridad ante cuadrícula, jugador u overlay inseguros
- 🔧 Inicio de debug separado con mensaje de estado en cada escaneo y replanificación
- ⚡ Branding de terminal RobinTh0r / Germon
- 📦 ZIP de release ligero con preparación local automática de Python

### Reglas para futuros releases

En cada versión nueva se actualizan en conjunto:

1. Número de versión en `VERSION`
2. Changelog en esta README
3. Tag de Git en formato `vX.Y.Z`
4. Release de GitHub con el mismo changelog como release notes
5. ZIP recién construido sin `.venv`, datos de runs, screenshots ni configuración local

## 🔗 Proyecto relacionado

| Proyecto | Plataforma | Repo |
| --- | --- | --- |
| DigiWorldExplorer_Bot (este fork) | Windows + BlueStacks, ADB | – |
| DigiWorldExplorer_Bot (original) | Windows + BlueStacks, ADB | [RobinTh0r/DigiWorldExplorer_Bot](https://github.com/RobinTh0r/DigiWorldExplorer_Bot) |
| DigiWorldExplorer Android Bot | Android, nativo, sin ADB | [RobinTh0r/DigiWorldExplorer_Android_Bot](https://github.com/RobinTh0r/DigiWorldExplorer_Android_Bot) |

---
<div align="center">

## ⚒️ Niveku × Gatomon 🦖

**✨ Fork mantenido por [Niveku](https://github.com/niveku) · base original de [RobinTh0r](https://github.com/RobinTh0r) ✨**

*Explore smart. Stop safe. Collect everything.*

</div>
