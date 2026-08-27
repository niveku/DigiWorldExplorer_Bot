# Loops de pantalla (laboratorio)

Repetir un dungeon es un problema distinto al de explorar el mundo: no hay
tablero, no hay pasos, no hay recibo de paticas. Lo que hay es una
secuencia corta de pantallas — oferta, batalla, recompensa, oferta otra
vez — y la única pregunta por frame es *qué pantalla es ésta y hay que
tocarla*.

Esto es la maquinaria genérica para eso. La idea viene de la app Android
del autor original (`dungeon/`, `network/`, `purchase/` en
`RobinTh0r/DigiWorldExplorer_Android_Bot`); el código es nuestro y las
diferencias están explicadas en la cabecera de `screen_loop.py`.

- `screen_loop.py` — motor puro: reconocer pantalla, decidir, contar
  vueltas. No toca ADB ni el reloj, así que se prueba sin emulador.
- `screen_loops.py` — CLI: capturar, aprender, simular, ejecutar.
- `safe_tap.py` — variación acotada del punto y del ritmo de cada tap.
- `overlays.py` — quién manda en el frame cuando algo tapa el tablero.

## Por qué no hay constantes de píxeles aquí

Los umbrales de la app Android están calibrados a *su* layout y a *su*
resolución. Copiarlos sería, además, copiar expresión de un repositorio
sin licencia. Aquí un loop se **aprende** de capturas tomadas en tu
BlueStacks: cada celda de una rejilla 12×16 guarda la media del área y la
dispersión que mostró entre capturas, y la distancia pondera por esa
dispersión. La zona que anima (la batalla, la recompensa girando) pesa
casi nada; el marco, el panel y los botones deciden. El umbral sale de las
propias capturas.

## Cómo se lanza

Doble clic en **`LOOP.cmd`**. Pregunta el loop (sólo si hay más de uno),
comprueba durante ~12 s que reconoce lo que hay en pantalla, y pregunta
**una** cosa: `Arrancar [S/n]`. Enter arranca, sin límite de vueltas, y se
para con Ctrl+C o por cualquiera de las reglas de seguridad de abajo.

Son dos entradas distintas a propósito: el Explorador pregunta cuántas
acciones y cotiza el inventario antes de arrancar; un loop no necesita
nada de eso. Meterlos en un mismo `START.cmd` añadiría una pregunta de
modo a cada arranque del Explorador, que es el que más se usa. El banner
sí lo comparten (`NivekuBanner.ps1`).

Lo que antes se preguntaba siempre y ahora no se pregunta nunca:

- **cuántas vueltas** — por defecto sin límite; `-Cycles N` si hace falta;
- **si adoptar una pantalla colgada** — el loop lo detecta solo. Una
  pantalla `--needs-session` que no abrimos nosotros se rechaza 12 frames
  y entonces el loop **para** diciendo qué pasó; `LOOP.cmd` ofrece
  cerrarla ahí, que es el único momento en que la pregunta significa algo.

Desde consola, sin ninguna pregunta:

```powershell
.\LOOP.cmd -Loop lost_sector -Yes
.\LOOP.cmd -Loop lost_sector -Yes -Cycles 50
```

## Receta

`mi_loop` es un nombre de ejemplo: elige el tuyo. **No reutilices
`dungeon` ni `lost_sector`** — existen ya, y `learn` los sobrescribe.

```bash
# 1. Abre la pantalla en el juego y capturala varias veces
python screen_loops.py capture --loop mi_loop --state challenge --count 6
python screen_loops.py capture --loop mi_loop --state reward --count 6

# 2. Aprende el perfil. El tap va en pixeles de la captura (o en 0..1)
python screen_loops.py learn --loop mi_loop \
    --tap challenge=460,1000 --tap reward=360,845 \
    --start challenge --cycle challenge --needs-session reward

# 3. SIMULACION: reconoce y explica, no toca nada
python screen_loops.py watch --loop mi_loop --max-frames 60

# 4. Solo cuando el paso 3 se ve bien
python screen_loops.py run --loop mi_loop --cycles 5
```

Anadir una variante a un perfil que ya existe es el mismo paso 1 con su
nombre y su estado, y despues `learn` otra vez: las capturas se acumulan
en la carpeta del estado. Asi entro Defense Type en `dungeon`.

`learn` imprime la **separación** entre pantallas en múltiplos del umbral.
Por debajo de `1.00x` dos pantallas se pueden confundir: eso es un
problema de calibración y hay que resolverlo con más capturas o con
estados mejor separados, nunca ejecutando `run` a ver qué pasa.

### Los modos, en términos de esta configuración

| Loop | Estados y banderas |
| --- | --- |
| **Lost Sector Tower** | `offer` (`--start`, `--cycle`, tap en *Subjugate*) y `reward` (`--needs-session`, tap en *Tap to close*). El panel de recompensa sale **al ganar**; al perder el juego vuelve solo al diálogo, sin panel. La batalla no necesita estado: es «pantalla desconocida» y el loop espera. |
| **Dungeon (Attack / Defense / SP Type)** | `challenge` (`--start`, `--cycle`, tap en *Attempt*), `reward` y `failed` (`--needs-session`, tap para cerrar), `battle` como estado de espera. El juego rota el tipo que ofrece, y los tres usan el mismo diálogo con otro título, otro jefe y otro fondo: por eso el perfil se llama `dungeon` y se aprende con capturas de **cada** tipo que aparezca. |
| **Network Defense (rendirse en el jefe)** | `start` (`--start`, `--cycle`, tap en *Attempt*), `final_boss` (`--needs-session`, tap en *Give up*), y si hace falta `battle` como estado de espera. |
| **Summon (tickets / Crest)** | `summon` (`--start`, `--cycle`, tap en el botón amarillo), `confirm` (`--needs-session`, confirmar), `unaffordable` (`--stop`) — la pantalla con el coste en rojo termina el loop. |

## Las reglas que hacen que esto sea seguro

1. **Tope de taps por pantalla** (`--taps-max`, 2 por defecto). Un diálogo
   mal clasificado recibe dos taps, no doscientos.
2. **La sesión es nuestra o no se toca.** Una pantalla marcada
   `--needs-session` sólo se toca si este loop abrió la vuelta. Sin eso,
   una recompensa que dejó abierta el jugador recibe taps ajenos.
   La excepción es `--adopt-session`, y está acotada a **una sola vez, la
   primera**: si el proceso anterior murió a mitad de vuelta, el juego se
   queda en la pantalla de recompensa, y la pantalla que abriría una
   sesión está *detrás* de la que nadie tiene permiso de cerrar. Sin la
   excepción, un relanzamiento se queda clavado en «sin sesion propia»
   para siempre (pasó el 2026-08-25 y hubo que dar el tap a mano).
   Adoptada la primera, la regla vuelve a estar entera. El rechazo está
   acotado a `refused_max` frames (12): pasados ésos el loop **para** y
   nombra la solución, y `LOOP.cmd` ofrece cerrarla ahí — no antes.
3. **Ningún tap se cree a sí mismo.** El estado avanza cuando la pantalla
   reconocida *deja* de reconocerse. Un tap que no cambió ni la pantalla
   ni el frame se cuenta como tap perdido: 3 seguidos estiran el intervalo
   ×1.5, 6 paran el loop. Es la ley del recibo de paticas aplicada a
   menús.
4. **Silencio = parada, y la pantalla se guarda.** Si el hash del frame
   no se mueve durante `--inactivity` segundos, el loop se apaga. Si
   ademas la pantalla no estaba reconocida, el frame se escribe en
   `outputs/<stamp>_<loop>/pantalla_desconocida.png`. El juego ya habra
   avanzado cuando alguien vaya a mirar, asi que la foto es el
   diagnóstico entero (2026-08-26: una corrida murió con 10 vueltas
   limpias detrás y no quedó forma de saber qué la paró).
5. **Presupuesto explícito.** `--cycles N` para en la pantalla que
   *ofrece* la siguiente vuelta, nunca a mitad de una: media vuelta cuesta
   el ticket y no devuelve nada.
6. **Cada tap se registra** en `outputs/<stamp>_<loop>/events.jsonl` con
   la pantalla, la razón y el punto.

## Lo que todavía no está medido

**Network Defense** y **Summon** siguen sin perfil: sus capturas no
existen. Hasta que existan, `watch` es lo único que se debe correr
sobre ellos, y el propio `watch` está para eso.

## Medición: Lost Sector Tower 69 (2026-08-26)

Ciclo medido muestreando cada 0,5 s tras un tap manual: diálogo →
*Now Loading* (~1,5 s) → batalla (~8 s, con su propio *Give Up* y un
cronómetro de 00:35) → *Now Loading* → el mismo diálogo. Verificado con
vueltas reales: **~18 s por vuelta, un tap por vuelta, ningún tap
perdido**. Separación `offer` vs `reward`: 6,47x.

**Corrección de la primera versión de este perfil.** Se aprendió con un
solo estado y esta nota decía que Lost Sector «no tiene panel de
recompensa». Salía de cinco vueltas seguidas, y las cinco se perdieron:
la muestra no contenía el caso. El panel existe y sale al ganar, con
siete cartas y un *Tap to close*. Es el mismo error que la regla del
residual del calculador describe — una conclusión sacada de una muestra
que nunca pudo contener el contraejemplo — y aquí la refutó la primera
victoria. La consecuencia importa: si la cuenta gana el nivel 69, este
loop **sí** rinde, al revés de lo que se concluyó con SP-89.

El nivel del piso **no** afecta al reconocimiento: a Lv.71, con otro
jefe y otro número, `offer` da distancia 0,0033 contra un umbral de
0,0200 — 0,17x. El número y el sprite ocupan pocas celdas de la rejilla
y la ponderación por dispersión las descuenta. Corrida larga de
verificación: 43 min, 126 taps, sin un solo fallo de reconocimiento.

Y el rechazo de una pantalla ajena tenía su propio agujero: el panel
animaba su cronómetro, así que la parada por inactividad nunca saltaba y
el loop esperaba en «sin sesion propia» indefinidamente. Ahora el rechazo
está acotado (`refused_max`, 12 frames) y termina nombrando la solución.

## El dungeon rota de tipo, y el perfil tenía un solo tipo (2026-08-26)

El perfil se llamaba `sp_trials` y se aprendió con el diálogo de **SP
Type**. Semanas después el juego ofrecía **Defense Type** y el loop no
reconoció nada: se quedó esperando hasta la parada por inactividad, que
es de dónde salió la impresión de que «demoraba mucho».

Medido contra la captura de esa pantalla: `challenge` daba **1,20x** el
umbral. Se quedó a un 20% — no es que el diálogo sea otro, es que el
título, el jefe y el fondo del banner cambian con el tipo, y el perfil
no había visto más que uno. Añadidas 6 capturas de Defense Type al mismo
estado, la dispersión crece justo en esas celdas y la distancia cae a
**0,43x**. Las capturas viejas de SP Type siguen dentro (peor caso 0,46x),
así que el perfil ahora cubre los dos tipos, no uno a costa del otro.

Por eso el perfil se llama **`dungeon`** y no `sp_trials`: el nombre de
un tipo describe la rotación de un día, no la pantalla. Cuando aparezca
**Attack Type**, se añade igual y se reaprende — no hace falta un perfil
nuevo:

```bash
python screen_loops.py capture --loop dungeon --state challenge --count 6
python screen_loops.py learn --loop dungeon \
    --tap challenge=0.649,0.787 --tap reward=0.5,0.816 --tap failed=0.028,0.5 \
    --start challenge --cycle challenge \
    --needs-session reward --needs-session failed
```

**Regla general que deja esto**: un perfil sólo conoce las variantes que
ha visto. Si una pantalla cambia con el día, la semana o el evento,
el arreglo no es bajar el umbral — eso acerca las pantallas entre sí y
termina en un tap en el diálogo equivocado — sino añadir capturas de la
variante nueva al **mismo** estado.

## Medición: 5,13 h del dungeon VS. SP-Type 89 (2026-08-25)

Primera corrida larga real, y el resultado importa más que la mecánica.

| | |
| --- | --- |
| duración | 5,13 h (terminó porque el proceso fue matado, no por una parada del loop) |
| vueltas | 715, a 25,8 s cada una |
| intentos | 716 · **702 derrotas · 1 victoria** |
| taps | 1.421, todos en las pantallas reconocidas |
| bits | 3.521,2K → 3.528,0K (**+6,8K**) |
| EXP de Tamer | 19.673,1K → 19.682,5K (**+9,4K**) |

**Corrección de una atribución equivocada.** A mitad de la sesión reporté
que cada derrota daba +753,7K bits y +870,5K de EXP. Era falso: esos
números eran la renta pasiva de Binary Road acumulada durante los ~24
minutos entre las dos capturas que comparé, no el premio del dungeon. El
error es exactamente el que la regla de `otherBonuses` del calculador
describe — un delta medido se atribuyó a la causa que estaba mirando en
ese momento, sin aislar la variable. Cinco horas de bucle lo desmienten:
+6,8K bits en 715 intentos.

Y como durante las batallas del dungeon la renta pasiva no corre, el
bucle probablemente **costó** más de lo que rindió.

**Conclusión operativa**: repetir un stage que se pierde 702 de 703 veces
no es farmeo. Un loop de dungeon sólo tiene sentido sobre un nivel que la
cuenta gane de forma fiable, o sobre Network Defense, donde el valor está
en los enemigos derrotados por vuelta y no en el desenlace.
