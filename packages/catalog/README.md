# arch-rules-catalog

Catálogo de rule packs versionados + datasets gold para entrenamiento/evaluación.

> En el monorepo MVP vive como `packages/catalog/`. Cuando madure, se extrae a repositorio independiente (ver `PLAN_IMPLEMENTACION.md` sección 5).

## Estructura

```
packages/catalog/
├── datasets/
│   └── gold-v1/                 # Dataset gold inicial (F0.5)
│       ├── schema/case.schema.yaml
│       └── cases/
│           ├── hexagonal/
│           ├── mvc/
│           ├── microservices/
│           └── universal/
└── packs/                       # Rule packs (a partir de H3)
    └── hexagonal/
```

## Dataset gold

Cada caso es un YAML que describe un fragmento de código y su etiqueta:

- `id`: identificador estable.
- `style`: estilo arquitectónico al que aplica (`hexagonal`, `mvc`, …, `universal`).
- `language`: lenguaje del fragmento.
- `label`: `violation`, `clean`, o `ambiguous`.
- `rule_id`: regla esperada (sólo si `label == violation`).
- `severity`: severidad esperada.
- `code`: snippet de código (multi-archivo permitido).
- `rationale`: explicación curada por humano.

Ver `schema/case.schema.yaml` para el contrato completo.
