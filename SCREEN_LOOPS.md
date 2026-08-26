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

Doble clic en **`LOOP.cmd`** — el equivalente de `START.cmd`, pero para los
loops. Son dos entradas distintas a propósito: el Explorador pregunta
cuántas acciones y cotiza el inventario antes de arrancar; un loop
pregunta cuál perfil y cuántas vueltas. Meterlos en un mismo `START.cmd`
añadiría una pregunta de modo a cada arranque del Explorador, que es el
que más se usa. El banner sí lo comparten (`NivekuBanner.ps1`).

`LOOP.cmd` hace, en este orden:

1. lista los perfiles que hay en `screen_profiles/` y te deja elegir;
2. corre **siempre la simulación primero** (15 frames, no toca nada);
3. sólo si dices que sí, pregunta cuántas vueltas y arranca el loop activo.

Enter en «¿Cuántas vueltas?» lo deja **sin límite** — se para con Ctrl+C,
o solo, por cualquiera de las reglas de seguridad de abajo.

Desde consola, si prefieres saltarte el menú:

```powershell
.\LOOP.cmd -Loop sp_trials -Active -Cycles 20
```

## Receta

```bash
# 1. Abre la pantalla en el juego y captúrala varias veces
python screen_loops.py capture --loop attack_trials --state challenge --count 6
python screen_loops.py capture --loop attack_trials --state reward --count 6

# 2. Aprende el perfil. El tap va en píxeles de la captura (o en 0..1)
python screen_loops.py learn --loop attack_trials \
    --tap challenge=460,1000 --tap reward=360,845 \
    --start challenge --cycle challenge --needs-session reward

# 3. SIMULACIÓN: reconoce y explica, no toca nada
python screen_loops.py watch --loop attack_trials --max-frames 60

# 4. Sólo cuando el paso 3 se ve bien
python screen_loops.py run --loop attack_trials --cycles 5
```

`learn` imprime la **separación** entre pantallas en múltiplos del umbral.
Por debajo de `1.00x` dos pantallas se pueden confundir: eso es un
problema de calibración y hay que resolverlo con más capturas o con
estados mejor separados, nunca ejecutando `run` a ver qué pasa.

### Los modos, en términos de esta configuración

| Loop | Estados y banderas |
| --- | --- |
| **Lost Sector Tower** | `offer` (`--start`, `--cycle`, tap en *Subjugate*), y nada más. Es el más simple de los tres: al perder no hay panel de recompensa ni de derrota — el juego vuelve solo al mismo diálogo. Sin estado `--needs-session`, así que tampoco existe el problema de adopción al relanzar. |
| **Attack Type Trials / CREST** | `challenge` (`--start`, `--cycle`, tap en *Attempt*), `reward` (`--needs-session`, tap para cerrar). La batalla no necesita estado: es "pantalla desconocida" y el loop espera. |
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
   Adoptada la primera, la regla vuelve a estar entera. `LOOP.cmd` lo
   pregunta antes de arrancar en activo.
3. **Ningún tap se cree a sí mismo.** El estado avanza cuando la pantalla
   reconocida *deja* de reconocerse. Un tap que no cambió ni la pantalla
   ni el frame se cuenta como tap perdido: 3 seguidos estiran el intervalo
   ×1.5, 6 paran el loop. Es la ley del recibo de paticas aplicada a
   menús.
4. **Silencio = parada.** Si el hash del frame no se mueve durante
   `--inactivity` segundos, el loop se apaga (pantalla de derrota, diálogo
   no clasificado, juego colgado).
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

Perfil aprendido de 6 capturas del diálogo, umbral 0,0200, tap en
(0,500 · 0,786). Tres vueltas de verificación: **3 taps, 3 vueltas,
~18 s por vuelta**, un solo tap por vuelta y ningún tap perdido.

La forma del ciclo se midió muestreando cada 0,5 s tras un tap manual:
diálogo → *Now Loading* (~1,5 s) → batalla (~8 s, con su propio
*Give Up* y un cronómetro de 00:35) → *Now Loading* → el mismo
diálogo. La derrota no abre panel; por eso el perfil tiene un único
estado y todo lo demás es «pantalla desconocida», que es esperar.

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
