# Changelog

Cambios por versión. El detalle técnico de cada arreglo, con la corrida que lo
probó, está en los diarios de `docs/review-*.md`.

## Sin publicar

- 🌍 **README bilingüe.** `README.md` en español y `README.en.md` en inglés,
  enlazados entre sí. `NOTICE.md` y `docs/UPSTREAM.md` pasaron a inglés y se
  quedan solo en inglés: sus lectores son el autor original y quien evalúa si
  puede reutilizar este código.
- 🔢 **Un conteo vivo, un solo documento.** El total de tests se leía 638 en el
  badge, 638 en la nota del fork, 520 en CONTRIBUTING y 607 en una entrada
  vieja del changelog, todo a la vez. Ahora vive solo en `docs/UPSTREAM.md` y
  lo demás enlaza. Lo que git puede contestar (commits, líneas cambiadas) ya no
  se escribe: se pone el comando. `tests/test_docs_numbers.py` falla si el
  número deja de ser cierto, si un badge se desvía de `VERSION`, o si los dos
  README dejan de tener las mismas secciones.

## v0.5.1 - 31.08.2026

- 📊 **La cotización del run estaba mal repartida.** Decía que un run gasta
  casi tantas garras como dashes, y el jugador lo notó antes que la medición:
  «se gastan muchos más DASH que garras». Remedido sobre 20 corridas y 4.690
  acciones, todas con las reglas de hoy, un dash se gasta el doble de veces
  que una garra. Los números que había salían de dos corridas y 158 acciones.

  | por acción | antes | ahora | peor corrida |
  | --- | ---: | ---: | ---: |
  | pasos | 0,85 | **0,86** | 0,909 |
  | garras | 0,020 | **0,012** | 0,024 |
  | dashes | 0,025 | **0,022** | 0,032 |

  El recibo del juego (inventario del HUD al empezar contra al terminar, 12
  corridas) da todavía menos, 0,004 garras y 0,016 dashes, porque una garra
  recogida devuelve una garra. La reserva se queda en el número bruto: pasarse
  cuesta un número más grande en pantalla, quedarse corto cuesta la sesión.
- 🧮 **El ratio que imprime el lanzador ya se calcula.** Estaba escrito a mano
  («24 pasos : 1 garra : 0,8 dashes») y quedó desactualizado en una semana.
  Ahora sale de las mismas constantes que gasta la recomendación.
- 📦 **`Build-Release.ps1`**: arma el ZIP del release con `git archive`, así
  que lleva exactamente lo que git rastrea y nada de `.venv`, `runs/`,
  `outputs/` ni configuración local. Las fixtures de tests se quedan fuera por
  `.gitattributes` (son 9,5 de los 11 MB): el ZIP pesa 0,22 MB.

## v0.5.0 - 31.08.2026

Nueve revisiones seguidas. Cada una la abrió el usuario parando una corrida y
diciendo qué había visto en pantalla.

**Ya no confunde con pirámides lo que no lo es**

- 💡 **La luz de «puedes pisar aquí».** El juego ilumina de azul la casilla a la
  que puedes moverte, y ese azul pasaba el test de pirámide. Cada vez que el bot
  se paraba al lado de una energía, la casilla se iluminaba, el bot la leía como
  pirámide y se iba. Una corrida perdió cinco paticas así.
- 🔺 **Una casilla, una cosa.** Una pirámide no puede tener un item encima: el
  color que se ve sobre ella es confeti pintado por una recogida. Las casillas
  que el bot ofrecía como recogida teniendo una pirámide bajaron de 7,2 % a
  1,0 %. Cada una de esas era un tap sobre una pirámide, que el juego cobra como
  una garra de 200 shards sin avisar.
- 🌫️ **Una pirámide medio tapada sigue ahí.** Si la lectura de una pirámide se
  cae por un cuadro, el bot la daba por rota, trazaba ruta a través de ella y
  pagaba otra garra oculta. Ahora una lectura dudosa lo deja ciego en esa
  casilla en vez de borrarle la memoria.

**Recuerda lo que ya había visto**

- 🎊 **El confeti ya no le hace olvidar.** Cuando el bot recoge algo, la
  animación llena el tablero de destellos de colores que parecen items. La
  versión anterior desconfiaba de cualquier tablero con cuatro items o más, y se
  perdía las veces en que los cuatro eran de verdad. Ahora sólo desconfía de lo
  que **aparece justo después de una recogida** y donde nada podía haber
  llegado. Lo que ya sabía que estaba ahí lo sigue yendo a buscar, con confeti o
  sin él. Los pasos hacia un destello bajaron del 33 % al 3 %.
- 🔋 **El contador del juego firma la recogida.** Antes el bot decidía por la
  vista si había recogido algo, y a veces se le pasaba. La energía subiendo es
  prueba que no se discute.
- ⏳ **Una tapa que nunca se levanta no es una tapa.** Una pirámide tapada por
  confeti se quedaba en la memoria para siempre y viajaba con la banda borrando
  items reales por donde pasaba. El confeti dura uno o dos cuadros; lo que
  sigue ahí al tercero es un item.
- ⏱️ **Confirma en dos vistas, no en tres.** Esperar tres frenaba todas las
  recogidas por igual sin filtrar confeti. Con dos recoge más energía real y
  pisa menos destellos.

**Ve mejor y gasta menos**

- 🔭 **La columna que asoma por la derecha.** La rendija que deja ver si viene
  una pirámide pasó de acertar 87 % a 94 %, midiendo contra lo que la propia
  corrida confirma un cuadro después. La clave estaba en distinguir el vidrio de
  la pirámide del marco azulado del tablero.
- 💨 **Menos dashes tirados.** El dash de pasillo se cobra porque rompe varias
  pirámides seguidas, y salía tras garras que no habían roto nada. De los cuatro
  que existen en todas las grabaciones, tres eran de esos.
- 🐾 **Una garra a medio romper ya no cuenta como fallida.** Dos lecturas
  «sin efecto» seguidas apagan las garras para el resto de la corrida, y con las
  garras apagadas una barrera de pirámides deja al bot dando vueltas sin ninguna
  jugada posible. Ese era el loop.

**Sigue abierto**

- Garras ignoradas de vez en cuando, sin caso reproducible todavía.
- Un loop al final de una corrida del 30.08 que no quedó grabado.

- 🧪 668 tests offline. El corpus de replay cierra en 0 violaciones.

Evidencia y mediciones de cada punto, incluidas las tres cosas que se midieron y
se decidió no construir, en [`review-2026-08-29.md`](review-2026-08-29.md).

## v0.4.0 - 29.08.2026

Una noche entera de corridas reportadas y arregladas una por una. Casi todo lo
de abajo salió de un fallo concreto que el usuario vio en pantalla.

**Ve lo que estaba viendo el jugador**

- 🐾 **Una garra tras el hielo sigue siendo una garra.** El score de una
  recogida es la fracción de amarillo de la celda, así que cualquier oclusión
  lo diluye — y las losas de hielo del primer plano se comen el tercio inferior
  de la fila 4. Una garra leyó 0.091 contra un umbral de 0.100 y el bot pasó de
  largo. El área no se podía rescatar (0.091 cae dentro de la banda de
  destellos de pirámide, percentil 99 = 0.094), así que ahora se **reconoce el
  sprite**: ~500 píxeles a un tercio de llenado de su propia caja, y un
  mordisco quita píxeles sin cambiar el llenado. 21 garras recuperadas en
  12.250 capturas, revisadas una por una.
- 🟢 **Y un orbe de dash mordido sigue siendo un orbe.** Mismo mecanismo, otro
  canal: 0.0575 contra 0.060, un paso por debajo del bot. 20 recuperadas — 14
  orbes y 6 tickets, sin confundirlos entre sí.
- 🚫 Medir la fila 4 sobre su 80% superior se probó y se **refutó** sobre el
  mismo corpus: gana 101 detecciones y pierde 77 reales, porque un sprite de
  esa fila se dibuja bajo y el recorte lo corta.

**Deja de dar pasos que no llevan a nada**

- 🔄 **Una carta que se desliza sola no es la cinta.** El re-sync de scroll no
  facturado exige ahora un segundo testigo con el mismo desplazamiento. Sin él,
  una naranja recién comida le entregó sus seis avistamientos a una carta de
  confeti y el bot caminó hacia atrás a recogerla.
- ↩️ **El agarre libre no camina hacia atrás sobre una sospechosa.** En todo el
  resto de la estrategia una sospechosa de la banda izquierda es confeti que no
  se puede creer ni perseguir; esta regla era la única que igual iba.
- 🧱 **La pared en formación no promete nada que el lanzamiento pueda cobrar.**
  Caminar a un lanzamiento de la columna 0 no hace scroll, así que ni la
  pirámide de la columna 4 ni la que promete el preview entran nunca en el
  camino del dash. Contarlas rompía la regla que el propio archivo declara:
  quien camina y quien dispara tienen que usar el mismo criterio. Costó cuatro
  paticas y una garra en una corrida.
- 🗺️ **No vuelvas a una celda que ya te dio su respuesta.** 351 de 3.062
  cambios de celda eran un regreso estéril: unos 6.400 de energía.

**No se queda tieso ni se muere**

- 🩹 El primer cuadro moría con `UnboundLocalError`, y **nadie ejecutaba
  `main()`** para verlo. Ahora hay pruebas de humo que corren el bucle de
  verdad contra capturas grabadas.
- 💤 Quedarse sin paticas **termina la corrida** con su propio código de salida
  en vez de seguir tocando la pantalla: una corrida gastó sus últimos 17
  cuadros así.
- 🐞 Una variable local tapaba una función del módulo y el bot moría en la
  acción 25.

**Más rápido**

- ⚡ La rejilla se busca **una vez**, no 29.600 veces por cuadro: 298 ms → 2,6 ms
  (115×), y la suite de tests pasó de 303 s a ~52 s. Verificado bit a bit sobre
  1.706 cuadros grabados.

**Economía remedida**

- 💱 Energía por shard: **paso 0,455 · garra 0,265 · dash 0,048.** Una garra
  empata con rodear (84 contra 80 shards); un dash solo paga contra una pared
  sin vuelta. Se retiraron 427 dashes de pareja pelada (~170.800 shards).
- 🔋 Quema por acción recalculada tras una corrida que se quedó sin pasos
  diciendo que no lo haría.

**Medido y escrito, no arreglado**

- 🔭 La **sexta columna** acierta casi todo lo que llega (recall 0,928) y se
  inventa la mitad de lo que anuncia (precisión 0,509). No se pudo refinar:
  blancura, luminancia, contraste, ventana estrecha, palpitación y persistencia
  fallan todas contra un holdout partido por corrida. La rendija es el bisel
  del tablero, no la columna siguiente, y le faltan píxeles que el juego no
  dibuja. Su coste real está medido: **680 shards en 15.015 cuadros**, así que
  se deja como está.

- 🧪 638 tests offline, incluidas pruebas que ejecutan el bucle real del runner.

Diario completo con las cifras en [`docs/review-2026-08-28.md`](docs/review-2026-08-28.md).

## v0.3.1 - 28.08.2026

- 🍊 **Una energía vale 125, no 20.** El +20 con el que se tasaba desde el
  20.08 era el tick de regeneración pasiva, no la recogida. Remedido sobre
  todas las grabaciones (n=623 frames cuyo plan pisó un naranja conocido: el
  salto es +125 y nunca +20 más de lo que sube un frame que no recoge nada).
  Un paso cuesta 18,2 de energía de media sobre 3.014 pasos cobrados.
- 🐛 **Ya no se salta una energía adyacente.** El guard que la descartaba
  cuando el resto de objetivos quedaba al otro lado de la fila salía de esa
  cuenta invertida: el rodeo cuesta dos paticas (~36) y la energía da 125.
  Caso de campo, run `20260828T150835` n=12: el bot tomó una del par, la
  cinta puso la otra justo debajo, y se fue por un dash orb; dos pasos
  después la energía se había salido del tablero.
- 🧹 Con el guard se va su andamiaje: el compromiso de objetivo de v0.3.0
  existía solo para cancelar sus falsos positivos. El A/B del harness sobre
  cuatro corridas grabadas da violaciones idénticas antes y después.

## v0.3.0 - 27.08.2026 (fork de Niveku)

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
  forma, y el A/B sobre las mismas grabaciones cambia 51 decisiones. (Retirado
  en v0.3.1 junto con el guard cuyos falsos positivos corregía.)
- 🧪 607 tests offline.
- 🗣️ Interfaz de usuario completa en español (runner, launchers PowerShell y esta README).

Diario completo de defectos y evidencia en [`docs/`](docs/).

## v0.2.0 – 29.07.2026

- 🟢 El inicio normal muestra aproximadamente cada 2 % el progreso, tiempo transcurrido y tiempo restante estimado.
- 📊 Al final del run aparecen el tiempo total y la energía inicial, final y su diferencia real.
- 🔎 El OCR de energía trabaja local y descarta valores inseguros.
- 🚀 Tras el número de acciones arranca el estándar seguro con una sola pregunta experimental breve.
- 🔁 Al terminar puede lanzarse directamente otro run con nuevo número de acciones.
- ⚡ La estadística final muestra energía por minuto y proyectada por hora.

## v0.1.0 – 29.07.2026

- 🧭 Detección automática de la cuadrícula 5×5 visible de DigiWorld
- 🟠 Recolección priorizada de energía e items visibles
- 🔺 Manejo seguro de pirámides, ataques y dash
- 🛑 Paradas de seguridad ante cuadrícula, jugador u overlay inseguros
- 🔧 Inicio de debug separado con mensaje de estado en cada escaneo y replanificación
- ⚡ Branding de terminal RobinTh0r / Germon
- 📦 ZIP de release ligero con preparación local automática de Python


## Reglas para futuros releases

En cada versión se actualizan juntos:

1. `VERSION`
2. Este changelog
3. Tag de git `vX.Y.Z`
4. `.\Build-Release.ps1` (empaqueta el tag, no el árbol de trabajo)
5. Release de GitHub con las mismas notas y el ZIP adjunto
