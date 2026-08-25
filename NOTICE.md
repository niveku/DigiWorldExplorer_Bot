# Origen, autoría y estado de licencia

Este repositorio es un **fork** de
[RobinTh0r/DigiWorldExplorer_Bot](https://github.com/RobinTh0r/DigiWorldExplorer_Bot).

## Quién escribió qué

| Parte | Autor |
| --- | --- |
| Base del proyecto: detección de la cuadrícula por ADB, exploración, launchers PowerShell, empaquetado | **RobinTh0r** (`mail@robinthor.de`) — 11 commits, hasta `d7d8548` (2026-07-31) |
| Todo lo construido encima desde 2026-08 (ver [`docs/UPSTREAM.md`](docs/UPSTREAM.md)) | **Niveku / Kevin Henao** (`kevin.henao@gmail.com`) |

El historial de git está **intacto**: `upstream/main` sigue siendo ancestro
directo de esta rama, así que `git log` distingue commit por commit qué vino
del proyecto original y qué se agregó después. Nada fue reescrito, aplastado
ni re-atribuido.

## Estado de licencia — léelo antes de reutilizar esto

El repositorio original **no declara ninguna licencia**. Según la
documentación de GitHub, sin licencia *"the default copyright laws apply,
meaning that you retain all rights to your source code and no one may
reproduce, distribute, or create derivative works from your work"*. Es decir:
los derechos sobre la base siguen siendo enteramente de RobinTh0r.

Lo único que permite el Términos de Servicio de GitHub (§D.5) es **ver y
forkear dentro de GitHub**:

> By making a repository public, you grant other Users a nonexclusive,
> worldwide license to use, display, perform and reproduce (by forking) Your
> Content through the Service as permitted by GitHub's functionality.

Este fork existe exactamente dentro de ese permiso: vive en GitHub, es un
fork real (no una copia con el historial borrado) y enlaza al original.

Consecuencias prácticas:

- **No hay archivo `LICENSE`** en este fork, y no puede haberlo: nadie puede
  licenciar código ajeno. Ponerle una licencia abierta a este repositorio
  sería afirmar un derecho que no tengo.
- **No redistribuyas esto fuera de GitHub** (ZIP, otro host, mirror) sin
  permiso de RobinTh0r. El permiso del ToS no llega hasta ahí.
- Si eres RobinTh0r y quieres que este fork desaparezca, se borra: escribe a
  `kevin.henao@gmail.com`. Si en cambio quieres los arreglos de vuelta,
  están todos aquí y encantado de mandarte los PR.
- Si algún día el proyecto original adopta una licencia (MIT sería lo
  natural), este archivo se actualiza y el fork la hereda.

## Marca

El branding del proyecto original (banner `ROBINTHOR`, «Guild Edition»,
«Exclusive for Germon Members», títulos de ventana) fue reemplazado por el
de este fork. No es un intento de borrar autoría — la autoría está arriba,
en el historial de git y en el enlace al repo original — sino lo contrario:
evitar que una versión modificada siga firmando con el nombre de su autor y
parezca respaldada por él.

## Sobre el juego

Esto automatiza *Digimon UP*, de Bandai Namco. No está afiliado ni
respaldado por ellos, y automatizar el juego probablemente viole sus
términos de servicio. Úsalo bajo tu propia responsabilidad, con la cuenta
que estés dispuesto a perder.
