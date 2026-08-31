<div align="center">

# ⚡ DigiWorldExplorer_Bot ⚡

![Version](https://img.shields.io/badge/version-0.5.0-yellow) ![Status](https://img.shields.io/badge/status-beta-orange) ![Platform](https://img.shields.io/badge/platform-Windows-blue) ![Tests](https://img.shields.io/badge/tests-668-green)

### 🦖 Exploración automatizada de DigiWorld para Digimon UP

**✨ Fork de [Niveku](https://github.com/niveku) · base de [RobinTh0r](https://github.com/RobinTh0r/DigiWorldExplorer_Bot) ✨**

`Local` · `Determinista` · `Solo ADB` · `Sin IA en la nube`

</div>

> [!WARNING]
> Proyecto de fans, sin relación con los desarrolladores de Digimon UP. Automatizar el juego puede violar sus reglas. Úsalo bajo tu responsabilidad.

> [!IMPORTANT]
> **Este repositorio es un fork.** La base es de [RobinTh0r](https://github.com/RobinTh0r/DigiWorldExplorer_Bot), publicada en julio de 2026. Encima van 170 commits míos. Detalle en [`docs/UPSTREAM.md`](docs/UPSTREAM.md); autoría y licencia (el original **no declara licencia**) en [`NOTICE.md`](NOTICE.md).

> [!NOTE]
> 🔗 Proyecto hermano del autor original: [DigiWorldExplorer_Android_Bot](https://github.com/RobinTh0r/DigiWorldExplorer_Android_Bot), el port nativo a Android, sin PC ni BlueStacks.

## 🌟 ¿Qué hace?

Juega DigiWorld por ti. Mira el tablero 5×5, decide a dónde ir y toca la pantalla.

Va por lo que más rinde, en este orden:

1. 🟠 energía
2. 🟣 items lilas y 🟢 verdes que estén de camino
3. ➡️ avanzar a la derecha
4. 🔺 rodear o romper pirámides
5. 💨 dash sólo cuando hay dos pirámides seguidas

También repite las pantallas que se repiten solas, como dungeons y lost sector, con `LOOP.cmd`.

## 🛡️ Seguridad

- Mira una captura nueva antes de cada decisión.
- Si la cuadrícula, el jugador o un overlay no se ven claros, espera o para.
- `CHECK.cmd` sólo observa: nunca toca la pantalla.
- `Ctrl+C` corta de inmediato.
- Nada sale de tu PC. Sin nube, sin cuentas, sin telemetría.

## 🚀 Empezar

Necesitas Windows 10 u 11, BlueStacks 5, Digimon UP y Python 3.10 o superior. Si falta Python, `INSTALL.cmd` te ofrece instalarlo con `winget`, y sin tu confirmación no instala nada.

### BlueStacks

| Ajuste | Valor |
|---|---:|
| Orientación | Portrait |
| Resolución | 720 × 1280 |
| Densidad | 240 DPI |
| Escalado de interfaz | 100 % |
| Android Debug Bridge | Activado |

> [!TIP]
> En esta beta **Botamon** es el que mejor se detecta: sprite pequeño y de color nítido. Otros Digimon funcionan, pero están menos calibrados.

### Pasos

1. Descarga o clona el repositorio.
2. Doble clic en `INSTALL.cmd`.
3. Abre BlueStacks y entra a DigiWorld.
4. Ejecuta `CHECK.cmd` y mira la imagen en `runs/checks/`: la cuadrícula verde debe enmarcar las 25 celdas.
5. Ejecuta `START.cmd`.

## 🎮 Usarlo

`START.cmd` te pregunta cuántas acciones quieres y **cotiza el run antes de tocar nada**: cuántas paticas, garras y dashes cuesta, cuánto tienes y si te alcanza. Puedes teclear otro número y vuelve a cotizar. Enter arranca, `n` cancela.

Las esperas las pone el bot solo, según lo que el juego anima, y se estiran cuando el aparato se traga taps. Durante el run ves el progreso cada 2 %. Al final tienes el tiempo total, la energía ganada, la energía por minuto y proyectada por hora, y cuántos taps te cobró el juego contra los que pediste.

`LOOP.cmd` corre las pantallas repetidas. Eliges perfil, comprueba durante 12 segundos que reconoce lo que hay y arranca. Vienen dos perfiles listos, `lost_sector` y `dungeon`. Enseñarle uno nuevo son seis capturas y un comando: [`SCREEN_LOOPS.md`](SCREEN_LOOPS.md).

```powershell
.\LOOP.cmd -Loop lost_sector -Yes            # sin preguntas
.\LOOP.cmd -Loop dungeon -Yes -Cycles 50     # acotado
```

### 🔧 Modo debug

**Un run normal no escribe nada en disco.** `START_DEBUG.cmd` y `LOOP_DEBUG.cmd` guardan en `runs/<id>/` una captura anotada por acción, los diagnósticos de las paradas y un registro de cada decisión. Cuesta unos 57 MB por cada 200 acciones. Enciéndelo cuando algo salga mal y quieras reportarlo.

## 🧯 Problemas frecuentes

| Problema | Solución |
|---|---|
| Falta Python | Ejecuta `INSTALL.cmd` y acepta la instalación con `winget` |
| ADB no encontrado | Actívalo en BlueStacks, **Ajustes → Avanzado** |
| Ningún dispositivo | Abre BlueStacks del todo y repite `CHECK.cmd` |
| Cuadrícula mal ubicada | No arranques. Revisa Portrait, 720×1280 y 240 DPI |
| Jugador no detectado | Espera a que acabe la animación y repite `CHECK.cmd` |

## 🔬 Cómo funciona

Todo pasa por **ADB**, el canal de depuración que Android ya trae de fábrica. El bot le pide una captura y le envía un tap con coordenadas, igual que haría un dedo. No lee la memoria del juego, no modifica el APK y no habla con los servidores: para el juego, un tap del bot y uno tuyo son la misma cosa. Por eso el bot es lento comparado con un cheat, y por eso no hay nada que parchear.

Nada está fijo a la ventana de Windows. En cada captura el bot **busca la cuadrícula** y calcula todo relativo a ella, así que puedes mover BlueStacks por el escritorio sin romper nada.

```text
Captura ADB → encuentra el tablero 5×5 → lee jugador, items y pirámides
   → elige la acción más segura → tap ADB → verifica que el juego la cobró
```

Con items a la vista planifica dos acciones antes de volver a mirar; sin items, tres. Un ataque o un dash siempre fuerzan una captura nueva.

Dos decisiones sostienen el resto:

- **El contador del HUD manda sobre la fe.** El juego cobra el tap o no lo cobra, y ahí se sabe si la banda avanzó. El bot le cree al contador, no a haber enviado el tap.
- **El tablero es memoria, no una foto.** Cada casilla es una pista con historia: cuántas veces se vio, de dónde salió, si es de fiar. Una animación corta ya no le hace olvidar una energía que lleva rato viendo.

Los 668 tests offline corren con capturas reales, y `replay_harness.py` convierte cada run grabado en un caso de regresión.

## 📂 Archivos

| Archivo | Función |
|---|---|
| `INSTALL.cmd` · `Setup.ps1` | Instalación y entorno local |
| `CHECK.cmd` · `Check-Setup.ps1` | Diagnóstico sin enviar taps |
| `START.cmd` · `START_DEBUG.cmd` | El explorador, tranquilo o con registro |
| `LOOP.cmd` · `LOOP_DEBUG.cmd` | Loops de pantalla, ver [`SCREEN_LOOPS.md`](SCREEN_LOOPS.md) |
| `digiworld_bot.py` | ADB, capturas, cuadrícula y taps |
| `auto_digiworld.py` | Detección de jugador, items y pirámides |
| `auto_digiworld_batch2.py` | Planificación y control de seguridad |
| `world_model.py` · `step_ledger.py` | La memoria del tablero y el recibo del juego |
| `replay_harness.py` · `tests/` | Regresión sobre runs grabados |
| `screen_loop.py` · `screen_loops.py` | Motor y CLI de los loops |

## 📦 ¿Por qué no un ejecutable portable?

Empaquetar Python, NumPy y Pillow completos haría el release enorme. En vez de eso `INSTALL.cmd` crea una `.venv` local con dos dependencias, y en un PC nuevo el entorno se reconstruye igual.

## 📝 Versiones

La versión actual está en `VERSION`, en el banner de la terminal y en `python auto_digiworld_batch2.py --version`.

**v0.5.0 (31.08.2026)**: el bot deja de confundirse con dos cosas que el juego pinta encima del tablero: la luz que marca una casilla como pisable, que leía como pirámide, y el confeti de una recogida, que leía como items nuevos. Además recuerda mejor lo que ya vio, distingue antes las pirámides que entran por la derecha y deja de gastar dashes que no rompen nada.

Historia completa en [`docs/CHANGELOG.md`](docs/CHANGELOG.md). Diario de defectos con la evidencia de cada arreglo en [`docs/`](docs/).

## 🔗 Proyectos relacionados

| Proyecto | Plataforma |
|---|---|
| [RobinTh0r/DigiWorldExplorer_Bot](https://github.com/RobinTh0r/DigiWorldExplorer_Bot) (original) | Windows + BlueStacks |
| [RobinTh0r/DigiWorldExplorer_Android_Bot](https://github.com/RobinTh0r/DigiWorldExplorer_Android_Bot) | Android nativo |

---
<div align="center">

## ⚒️ Niveku × Gatomon 🦖

**✨ Fork mantenido por [Niveku](https://github.com/niveku) · base original de [RobinTh0r](https://github.com/RobinTh0r) ✨**

*Explore smart. Stop safe. Collect everything.*

</div>
