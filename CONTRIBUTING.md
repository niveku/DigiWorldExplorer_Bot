# Cómo se trabaja en este repositorio

Antes que nada, lee [`NOTICE.md`](NOTICE.md): este es un fork de un proyecto
sin licencia, y eso condiciona qué se puede hacer con el código.

## Reglas duras

**1. Test rojo primero.** Ningún cambio de comportamiento entra sin un test
que falle antes y pase después. Los tests están para prevenir errores, no
para documentar los que ya se arreglaron a mano.

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m unittest discover -s tests
```

La suite tarda alrededor de un minuto; el replay del corpus es la parte
lenta y es la que más vale. Cuántos tests son está en
[`docs/UPSTREAM.md`](docs/UPSTREAM.md), que es el único sitio donde se
escribe un conteo vivo.

**2. La evidencia manda sobre la teoría.** Un arreglo se justifica con una
corrida real, un log o un PNG — no con un razonamiento plausible. Si la
medición dice que el arreglo no sirve, el arreglo se borra, aunque la idea
fuera bonita. Hay varios ejemplos de eso en `docs/review-*.md`.

**3. Los hallazgos se arreglan, no se posponen.** Cualquier defecto que
aparezca en una revisión se soluciona antes de seguir. Si de verdad está
bloqueado, va a un lugar durable — cuerpo del PR o `docs/review-*.md` — con
motivo, plan y evidencia del bloqueo. «Es menor» o «funciona igual» no
cuentan como bloqueo.

**4. Causa raíz antes que síntoma.** Ante un fallo: leer el error completo,
reproducirlo, mirar qué cambió, instrumentar si hace falta. Nada de probar
arreglos a ver cuál pega. Si tres intentos fallan, el problema es de diseño
y hay que discutirlo, no intentar un cuarto.

## Corridas en vivo

Los cambios de planificación se validan corriendo el bot de verdad, en
episodios cortos (20–80 acciones), y pasando la corrida por el harness:

```bash
.venv/Scripts/python.exe auto_digiworld_batch2.py --steps 60 --progress-percent 100
.venv/Scripts/python.exe replay_harness.py runs/<corrida>
```

El harness debe cerrar en **0 violaciones**. Si aparece una, es un defecto
real: los invariantes (GHOST, PLAYER-LAW, STARVATION, BLIND-TOUR, PING-PONG,
INDECISION, BACKSTEP) están escritos a partir de fallos observados.

Las corridas limpias que cubren un caso nuevo se agregan al corpus de
`tests/test_replay.py`, que es como un defecto arreglado se queda arreglado.

## Estilo

- Código, comentarios y commits en **inglés**. La interfaz de usuario (el
  runner y los lanzadores) en **español**.
- Documentos: `README.md` en español con espejo en `README.en.md`, y los dos
  se actualizan juntos — un test lo comprueba. `NOTICE.md` y
  `docs/UPSTREAM.md` van solo en inglés: sus lectores son el autor original
  y quien evalúa si puede reutilizar esto. El changelog y los diarios de
  `docs/review-*.md` van solo en español, porque cambian cada semana y
  traducirlos cada vez es el costo que no se acaba nunca.
- **Un conteo vivo se escribe en un solo sitio**, `docs/UPSTREAM.md`; lo
  demás enlaza. Lo que git puede contestar (commits, líneas) no se escribe:
  se pone el comando. Un número dentro de una entrada fechada del changelog
  sí se queda, porque describe esa versión y no envejece.
- Los comentarios explican **por qué**, con la corrida que lo probó
  (`run 20260823T155501 n=51`). Un comentario que solo repite lo que hace la
  línea siguiente sobra.
- Commits en formato convencional (`fix(runner): ...`), cuerpo explicando la
  evidencia. Nunca `--no-verify`.

## Ramas: solo `main` se publica

Los experimentos se quedan en la máquina. En GitHub la visibilidad es del
repositorio entero — si el repo es público, cualquier rama que empujes lo es
también, y lo empujado sigue siendo accesible por su SHA aunque después
borres la rama. Así que el trabajo en curso vive en ramas locales y solo
`main` sube al fork.

El repositorio ya está configurado para que un `git push origin` distraído
no publique la rama en la que estés parado:

```bash
git config --local remote.origin.push refs/heads/main:refs/heads/main
```

Esa línea es configuración **local**: un clon nuevo no la hereda, hay que
volver a ejecutarla. Empujar una rama a propósito sigue siendo posible
(`git push origin mi-rama`) — el objetivo es que sea una decisión, no un
accidente.

## Qué no hacer

- No borrar ni reescribir el historial de git: la trazabilidad respecto al
  proyecto original depende de que `upstream/main` siga siendo ancestro.
- No subir `runs/` ni `outputs/` (están en `.gitignore`; son gigabytes de
  PNG).
- No agregar un `LICENSE`: ver `NOTICE.md`.
- No redistribuir el proyecto fuera de GitHub.
- No empujar ramas de experimentos al fork público: ver la sección de ramas.
