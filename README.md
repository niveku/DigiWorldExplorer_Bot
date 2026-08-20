<div align="center">

# ⚡ DigiWorldExplorer_Bot ⚡

![Version](https://img.shields.io/badge/version-0.2.0-yellow) ![Status](https://img.shields.io/badge/status-beta-orange) ![Platform](https://img.shields.io/badge/platform-Windows-blue)

### 🦖 Exploración automatizada de DigiWorld para Digimon UP

**✨ RobinTh0r Guild Edition · Exclusive for Germon Members ✨**

`Local` · `Determinista` · `Solo ADB` · `Sin IA en la nube` · `Safety first`

</div>

> [!WARNING]
> Este proyecto privado de fans no está vinculado a los desarrolladores de Digimon UP. La automatización del juego puede violar sus reglas. Uso exclusivamente bajo tu propia responsabilidad y sin garantía.

> [!NOTE]
> 🔗 Proyecto hermano: [DigiWorldExplorer_Android_Bot](https://github.com/RobinTh0r/DigiWorldExplorer_Android_Bot)
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

`START.cmd` pregunta primero el número de acciones y después, brevemente, si quieres usar ajustes experimentales. El valor por defecto es `N`: el bot arranca de inmediato con el intervalo seguro de `0,50 segundos` y sin imágenes de debug. Solo con `S` se preguntan además el intervalo y las imágenes de diagnóstico. Al terminar un run puede lanzarse otro directamente; la secuencia de preguntas vuelve a empezar por el número de acciones.

El intervalo mínimo está limitado a `0,35 segundos` por seguridad. Con `Ctrl+C` el bot se detiene de inmediato en cualquier momento. En modo normal aparece aproximadamente cada 2 % una actualización compacta con progreso, tiempo transcurrido y tiempo restante estimado. Al final se muestran el tiempo total, la energía inicial, la final, la diferencia real, y la energía por minuto y proyectada por hora. Además queda visible el conteo interno de items detectados y recogidos a propósito. Si el contador del HUD no puede leerse con certeza, se indica explícitamente **no legible con certeza**.

### 🔧 Modo debug

`START_DEBUG.cmd` activa las imágenes de diagnóstico y muestra en cada escaneo o replanificación una línea de estado compacta, por ejemplo `10/100: ¡Energía a la vista! Recalculando ruta`. Los datos de máquina completos siguen en `runs/<id-del-run>/events.jsonl`.

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
| `START_DEBUG.cmd` | Run de desarrollo con estado por escaneo e imágenes de diagnóstico |
| `Setup.ps1` | Verificar Python y preparar el entorno local |
| `Check-Setup.ps1` | Ejecutar el modo de diagnóstico seguro |
| `Start-Bot.ps1` | Preguntar opciones de inicio y lanzar el run |
| `digiworld_bot.py` | ADB, screenshots, detección de cuadrícula y taps |
| `auto_digiworld.py` | Detección de jugador, items y obstáculos |
| `auto_digiworld_batch2.py` | Planificación adaptativa y control de seguridad |
| `tests/test_core.py` | Tests de regresión offline sin entradas al juego |
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
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
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

### Unreleased

- Interfaz de usuario completa en español (runner, launchers PowerShell y esta README).

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
| DigiWorldExplorer_Bot (este repo) | Windows + BlueStacks, ADB | – |
| DigiWorldExplorer Android Bot | Android, nativo, sin ADB | [RobinTh0r/DigiWorldExplorer_Android_Bot](https://github.com/RobinTh0r/DigiWorldExplorer_Android_Bot) |

---
<div align="center">

## ⚒️ RobinTh0r × Agumon 🦖

**✨ Built for the guild · Exclusive for Germon Members ✨**

*Explore smart. Stop safe. Collect everything.*

</div>
