# fitness-functions-ai

[![CI](https://github.com/rsaglobaltech/fitness-functions-ai/actions/workflows/ci.yml/badge.svg?branch=develop)](https://github.com/rsaglobaltech/fitness-functions-ai/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12-blue)
![uv](https://img.shields.io/badge/managed%20by-uv-de5fe9)

Guardián Arquitectónico con IA. Sistema de fitness functions arquitectónicas asistido por IA, agnóstico al estilo arquitectónico (Hexagonal, MVC, Microservicios, Modular Monolith, FSD, etc.).

Analiza PRs, detecta violaciones contra reglas declaradas o detectadas heurísticamente, y publica feedback contextual en el flujo de revisión.

## Uso

```bash
uv sync --all-packages

# Escaneo completo del repo
uv run guardian analyze .

# Solo hallazgos nuevos respecto al merge-base con main (modo PR)
uv run guardian analyze . --base origin/main

# SARIF para GitHub code scanning
uv run guardian analyze . --base origin/main -f sarif -o guardian.sarif
```

| Opción | Valores | Default |
|---|---|---|
| `--format/-f` | `text`, `json`, `sarif`, `github` (anotaciones) | `text` |
| `--fail-on` | `critical`, `warning`, `suggestion`, `never` | `critical` |
| `--base` | ref git; reporta solo hallazgos nuevos desde el merge-base | — |
| `--head` | ref a analizar; `HEAD` usa el working tree tal cual | `HEAD` |
| `--report` | `FORMAT:PATH` extra de la misma corrida (repetible) | — |
| `--allow-invalid-config` | no falla si `.architecture.yaml` es inválido | off |

Códigos de salida: `0` sin hallazgos bloqueantes · `1` hallazgos ≥ `--fail-on` · `2` error de uso/configuración/git · `3` error interno.

En CI, el modo `--base` necesita historial completo (`actions/checkout` con `fetch-depth: 0`). Los logs van a stderr; stdout queda limpio para JSON/SARIF.

## GitHub Action

```yaml
# .github/workflows/architecture.yml
on: pull_request
permissions:
  contents: read
  # security-events: write   # solo si upload-sarif: true
jobs:
  guardian:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0          # obligatorio: compara contra el merge-base
      - uses: rsaglobaltech/fitness-functions-ai@v0   # o un SHA para máxima reproducibilidad
        with:
          fail-on: critical       # critical | warning | suggestion | never
          upload-sarif: "false"   # "true" → GitHub code scanning (GHAS en repos privados)
```

- En `pull_request` compara automáticamente contra `origin/<rama base>`: solo reporta lo que el PR introduce.
- Hallazgos como anotaciones inline en el PR (sin GHAS) + resumen en la pestaña del job.
- Outputs: `exit-code`, `sarif-file`. Clon superficial → error explícito, no un falso verde.

## Docker

```bash
docker run --rm -v "$PWD:/workspace" ghcr.io/rsaglobaltech/arch-guardian:0 analyze . --base origin/main
```

Imagen no-root, solo con el venv y `git`; publicada con SBOM y provenance en cada release.

## Releases

1. Subir `__version__` en `packages/engine/src/arch_guardian_engine/__init__.py` (única fuente de versión).
2. Merge a `main`, luego `git tag vX.Y.Z && git push origin vX.Y.Z`.
3. El workflow `Release` verifica tag = versión, construye wheel/sdist (con smoke test), publica la imagen en GHCR, crea el GitHub Release y mueve el tag flotante `vX` usado por la Action.

## Configuración adicional

- `exclude: ["generated/**", "**/fixtures/**"]` — paths que nunca se analizan.

## Reglas de capas (`layout.layers`)

Deterministas, sin LLM. Aplican a cualquier estilo que declare `layers` (hexagonal, layered, clean…):

```yaml
architecture:
  style: hexagonal
  rule_pack_version: "1.0.0"
  strict_mode: true          # true → critical (bloquea); false → warning
layout:
  layers:
    domain:
      paths: ["src/domain/**"]
      can_depend_on: []
      forbidden_imports: ["@prisma/*", "sqlalchemy", "express"]   # paquetes externos
    application:
      paths: ["src/application/**"]
      can_depend_on: ["domain"]
    infrastructure:
      paths: ["src/infrastructure/**"]
      can_depend_on: ["domain", "application"]
```

- Un archivo pertenece a la capa cuyo glob coincidente es más específico.
- Imports dentro de la misma capa siempre permitidos; archivos fuera de toda capa no se evalúan.
- Feature-Sliced Design puede usar `layers_order` + `paths`: cada capa solo importa capas inferiores.
- Hallazgos: `<style>.layer_violation` — silenciables con `exceptions` (`suppress_rules: ["layer_violation"]`).
- Un `layout` mal formado (capa desconocida en `can_depend_on`, sin `paths`…) termina con exit 2.

## Documentación

- [Plan de Implementación](./PLAN_IMPLEMENTACION.md) — Roadmap completo por hitos (H0–H7) para MVP en 13 semanas.

## Estado

v0.1 — CLI determinista lista para uso real (reglas universales + capas, modo PR, SARIF, GitHub Action). Capa LLM (H3+) en desarrollo; se instala aparte con el extra `[llm]`.

## Branching

- `main` — rama estable, releases.
- `develop` — rama de integración, donde se mergean features.
