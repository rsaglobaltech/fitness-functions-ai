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
| `--format/-f` | `text`, `json`, `sarif` | `text` |
| `--fail-on` | `critical`, `warning`, `suggestion`, `never` | `critical` |
| `--base` | ref git; reporta solo hallazgos nuevos desde el merge-base | — |
| `--head` | ref a analizar; `HEAD` usa el working tree tal cual | `HEAD` |
| `--allow-invalid-config` | no falla si `.architecture.yaml` es inválido | off |

Códigos de salida: `0` sin hallazgos bloqueantes · `1` hallazgos ≥ `--fail-on` · `2` error de uso/configuración/git · `3` error interno.

En CI, el modo `--base` necesita historial completo (`actions/checkout` con `fetch-depth: 0`). Los logs van a stderr; stdout queda limpio para JSON/SARIF.

## Documentación

- [Plan de Implementación](./PLAN_IMPLEMENTACION.md) — Roadmap completo por hitos (H0–H7) para MVP en 13 semanas.

## Estado

En desarrollo activo — Hito H0 (Setup y Fundaciones).

## Branching

- `main` — rama estable, releases.
- `develop` — rama de integración, donde se mergean features.
