# Benchmark v0.1 — repositorios reales

Fecha: 2026-10-04 · Engine 0.1.0 · MacBook (8 CPU, Apple Silicon) · `guardian analyze <repo> -f json`, sin `.architecture.yaml` (solo reglas universales, umbrales por defecto).

## Rendimiento (escaneo completo)

| Repositorio | Commit | Archivos fuente | Tiempo | RSS proceso principal | Hallazgos |
|---|---|---:|---:|---:|---:|
| django/django | `a461af8` | 3.0k (Py) | 4.6 s | 94 MB | 309 |
| nestjs/nest | `35142c3` | 2.0k (TS) | 3.1 s | 78 MB | 35 |
| spring-projects/spring-framework | `aacad27` | 9.3k (Java) | 9.5 s | 178 MB | 552 |
| microsoft/vscode | `5e86c7c4` | 14.5k (TS/JS) | 29.6 s | 307 MB | 3 543 |

Evolución durante la preparación de v0.1 (VS Code): 145 s → 55 s (escaneo de AST en una pasada) → 29.6 s (parseo en paralelo, `--jobs`).
Los workers paralelos usan memoria adicional propia (~1 parser por CPU, máx. 8).

## Modo PR (`--base`)

Django, últimos 30 commits (114 archivos, +1 403 / −1 732 líneas):

- **11.4 s** de punta a punta (incluye `git worktree` del merge-base y análisis de ambos lados).
- **308 hallazgos pre-existentes ocultos, 1 nuevo**: una clase de tests que creció por encima de los umbrales de God Object (26 métodos públicos, 534 LOC). Correcto.

Este es el modo recomendado para CI: el ruido es proporcional al cambio, no al tamaño del repo.

## Precisión (muestreo manual)

| Regla | Muestra | Resultado |
|---|---|---|
| Ciclos (Django) | 3 ciclos de 2 módulos | 3/3 reales: dependencias bidireccionales rotas en runtime con imports diferidos dentro de funciones. |
| Ciclos (Nest) | 4 ciclos de 2 módulos | 4/4 reales: fixtures de tests de integración que crean ciclos a propósito (`circular-modules`). |
| Complejidad | — | Modelo por función más interna (igual que ESLint `complexity`): un callback no suma a la función que lo define. |

### Defectos encontrados y corregidos por este benchmark

1. **Doble conteo de complejidad**: las decisiones de funciones anidadas (callbacks, arrows) se sumaban también a la función contenedora. VS Code: 1 160 → 514 críticos.
2. **Recorrido cuadrático del AST**: varias pasadas por archivo y una más por función.
3. **Nodos inexistentes en las gramáticas**: `comprehension_if_clause` (Python) y `for_of_statement` (TS) no existen; ahora un test valida cada tipo de nodo contra la gramática real.
4. **Métricas de clase Python**: métodos decorados (`@property`…) no se contaban; los campos siempre daban 0.
5. **Mensaje de ciclo engañoso**: listaba miembros en orden alfabético con `→`; ahora muestra el ciclo real más corto y el tamaño del grupo (Django tiene un grupo de 172 módulos).
6. **Modo PR penalizaba mejoras**: achicar un ciclo cambiaba su identidad y se reportaba como nuevo; ahora un ciclo solo es nuevo si no estaba contenido en un ciclo de la base.

## Recomendaciones de adopción

- **Empezar en modo PR con `fail-on: critical`**: el volumen de escaneo completo (cientos de hallazgos en repos maduros) no es accionable de golpe.
- Los ciclos con imports diferidos (Python) son reales a nivel de diseño, pero el equipo puede decidir tolerarlos: usar `exceptions` con fecha de expiración.
- Ajustar `god_object_threshold` / `cyclomatic_complexity` por repo: Spring y VS Code tienen clases y funciones grandes por diseño; los umbrales por defecto generan muchos `warning` (no bloqueantes).

## Reproducir

```bash
git clone --depth 1 https://github.com/django/django.git
uv run guardian analyze django -f json --fail-on never -o django.json
```
