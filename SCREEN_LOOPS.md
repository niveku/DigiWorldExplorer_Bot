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

### Los tres loops, en términos de esta configuración

| Loop | Estados y banderas |
| --- | --- |
| **Attack Type Trials / CREST** | `challenge` (`--start`, `--cycle`, tap en *Attempt*), `reward` (`--needs-session`, tap para cerrar). La batalla no necesita estado: es "pantalla desconocida" y el loop espera. |
| **Network Defense (rendirse en el jefe)** | `start` (`--start`, `--cycle`, tap en *Attempt*), `final_boss` (`--needs-session`, tap en *Give up*), y si hace falta `battle` como estado de espera. |
| **Summon (tickets / Crest)** | `summon` (`--start`, `--cycle`, tap en el botón amarillo), `confirm` (`--needs-session`, confirmar), `unaffordable` (`--stop`) — la pantalla con el coste en rojo termina el loop. |

## Las reglas que hacen que esto sea seguro

1. **Tope de taps por pantalla** (`--taps-max`, 2 por defecto). Un diálogo
   mal clasificado recibe dos taps, no doscientos.
2. **La sesión es nuestra o no se toca.** Una pantalla marcada
   `--needs-session` sólo se toca si este loop abrió la vuelta. Sin eso,
   una recompensa que dejó abierta el jugador recibe taps ajenos.
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

Nada de esto sabe aún cómo se ven Attack Type Trials ni CREST: los
perfiles se aprenden de capturas que hay que tomar en el emulador. Hasta
que existan, `watch` es lo único que se debe correr, y el propio `watch`
está para eso.

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
