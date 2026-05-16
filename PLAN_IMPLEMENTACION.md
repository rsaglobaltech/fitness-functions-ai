# Plan de Implementación: Guardián Arquitectónico con IA

> Documento operativo por hitos (milestones), listo para empezar a programar feature por feature.

---

## 1. Visión General

Sistema de fitness functions arquitectónicas asistido por IA, **agnóstico al estilo arquitectónico**. Analiza PRs, detecta violaciones contra reglas declaradas o detectadas heurísticamente, y publica feedback contextual en el flujo de revisión.

### Principios de diseño

1. **Estilo declarativo**: cada repo declara su arquitectura en `.architecture.yaml`.
2. **Motor agnóstico**: el core no conoce estilos; los carga como *rule packs* versionados.
3. **Determinismo primero, LLM después**: análisis estático cubre 60-70% sin invocar LLM.
4. **Reglas universales siempre activas**: ciclos, God Objects, complejidad — independiente del estilo.
5. **Calibración antes de bloqueo**: modo sombra obligatorio previo a go-live.

---

## 2. Stack Tecnológico Consolidado

| Capa | Tecnología | Justificación |
|---|---|---|
| Lenguaje orquestador | Python 3.12 | Ecosistema maduro AST + LLM |
| AST multi-lenguaje | Tree-sitter + parsers nativos (`ast`, `ts-morph`, `javaparser`) | Gramáticas unificadas para 40+ lenguajes |
| Detectores deterministas | `import-linter` (Py), `dependency-cruiser` (JS/TS), ArchUnit (Java), `go-arch-lint` (Go) | Pluggable por lenguaje |
| LLM principal | Claude Sonnet 4.5 (Anthropic) | Razonamiento estructural, ventana amplia |
| LLM filtro rápido | Claude Haiku 4.5 | Pre-clasificación económica |
| LLM privacy-first | Llama 3.3 70B (vLLM on-prem) o Azure OpenAI Private Endpoint | Para clientes regulados |
| Orquestación LLM | LangGraph (sobre LangChain) | Flujos con estado y ramificación |
| Validación de salida | Pydantic | Schema estricto + retry |
| Vector store (RAG) | Qdrant (self-hosted) o Pinecone | Soberanía vs time-to-market |
| Embeddings | Voyage AI (`voyage-3`) o OpenAI `text-embedding-3-large` | Voyage rinde mejor en código |
| Contenedorización | Docker (base `python:3.12-slim`) | Estándar industrial |
| CI/CD | GitHub Actions (primario) + adaptadores GitLab/Bitbucket | ~70% del mercado |
| Persistencia | PostgreSQL 16 + pgvector | Hallazgos, métricas, embeddings |
| Observabilidad LLM | Langfuse (self-hosted) | Trazas, tokens, costos, A/B |
| Secretos | HashiCorp Vault o AWS/Azure equivalente | Nunca en CI vars |
| Feature flags | Unleash o LaunchDarkly | Activación progresiva sin redeploy |
| Dashboards | Metabase | Sin desarrollo frontend |
| Regresión de prompts | Promptfoo | Bloquea merges que degradan precisión |

---

## 3. Arquitectura del Sistema

### 3.1 Tres capas funcionales

```
┌─────────────────────────────────────────────────┐
│ Capa 1: Detector de Estilo Arquitectónico       │
│ - Camino A: .architecture.yaml (explícito)      │
│ - Camino B: heurística estructural              │
│ - Camino C: fallback a reglas universales       │
└─────────────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────┐
│ Capa 2: Motor de Reglas Extensible              │
│ - Carga rule pack desde catálogo                │
│ - Ejecuta detectores deterministas              │
│ - Escala a LLM + RAG para casos ambiguos        │
└─────────────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────┐
│ Capa 3: Reglas Universales (siempre activas)    │
│ - Ciclos, God Objects, complejidad, SOLID, etc. │
└─────────────────────────────────────────────────┘
```

### 3.2 Catálogo de estilos soportados (MVP + roadmap)

| Estilo | MVP | Lenguajes típicos |
|---|---|---|
| Hexagonal / Clean / Onion | ✅ | Java, C#, TS, Python |
| Layered (N-tier clásico) | Post-MVP | Java EE, .NET legacy |
| MVC / MVVM | ✅ | Rails, Django, Laravel |
| Microservicios | ✅ | Polyglot |
| Event-Driven / CQRS | Post-MVP | Kafka/RabbitMQ |
| Modular Monolith | Post-MVP | Spring Modulith, .NET |
| Vertical Slice | Post-MVP | .NET (MediatR), Go |
| Feature-Sliced Design | Post-MVP | React, Vue |
| DDD táctico | Post-MVP | Cualquiera |
| Plugin / Microkernel | Post-MVP | Frameworks extensibles |
| Pipes & Filters | Post-MVP | ETL, data pipelines |

---

## 4. Contrato `.architecture.yaml`

Archivo raíz del repo. Contrato declarativo entre el equipo y el guardián.

### 4.1 Estructura base (común)

```yaml
schema_version: "1.0"

project:
  name: "payments-service"
  language: "typescript"
  runtime: "node20"

architecture:
  style: "hexagonal"
  rule_pack_version: "2.3.0"
  strict_mode: true

layout:
  # específico por estilo

universal_rules:
  circular_dependencies: error
  god_object_threshold:
    severity: warning
    max_methods: 25
    max_loc: 500
  cyclomatic_complexity:
    severity: warning
    max_per_function: 15

knowledge_base:
  adr_path: "docs/adr/"
  conventions_path: "docs/conventions.md"
  exclude_patterns:
    - "docs/adr/archived/**"

exceptions:
  - path: "src/legacy/**"
    reason: "Migración programada Q3 2026, ver TICKET-1234"
    expires: "2026-09-30"
    suppress_rules: ["layer_violation", "circular_dependency"]
```

### 4.2 Ejemplos por estilo

#### Hexagonal / Clean

```yaml
architecture:
  style: hexagonal
  rule_pack_version: "2.3.0"
layout:
  layers:
    domain:
      paths: ["src/domain/**", "src/core/**"]
      can_depend_on: []
    application:
      paths: ["src/application/**", "src/use-cases/**"]
      can_depend_on: ["domain"]
    infrastructure:
      paths: ["src/infrastructure/**", "src/adapters/**"]
      can_depend_on: ["domain", "application"]
    presentation:
      paths: ["src/controllers/**", "src/http/**"]
      can_depend_on: ["application", "domain"]
  ports_and_adapters:
    ports_path: "src/domain/ports/**"
    adapters_must_implement_port: true
```

#### MVC clásico

```yaml
architecture:
  style: mvc
  rule_pack_version: "1.4.0"
layout:
  components:
    models:
      paths: ["app/models/**"]
      forbidden_imports: ["app/views/**", "app/controllers/**"]
    views:
      paths: ["app/views/**", "app/templates/**"]
      forbidden_business_logic: true
    controllers:
      paths: ["app/controllers/**"]
      max_loc_per_action: 30
  fat_model_skinny_controller: true
```

#### Microservicios

```yaml
architecture:
  style: microservices
  rule_pack_version: "3.1.0"
layout:
  service_boundary: "src/"
  external_contracts:
    api_definition: "openapi.yaml"
    events_published: "events/published/*.json"
    events_consumed: "events/consumed/*.json"
  forbidden:
    shared_database_access: true
    sync_calls_to_services: ["user-service", "billing-service"]
    direct_imports_from_monorepo:
      pattern: "../../*/src/**"
```

#### Modular Monolith

```yaml
architecture:
  style: modular_monolith
  rule_pack_version: "1.2.0"
layout:
  modules_root: "src/main/java/com/company/"
  modules:
    - name: "customers"
      public_api: "customers/api/**"
      internal: "customers/internal/**"
    - name: "orders"
      public_api: "orders/api/**"
      internal: "orders/internal/**"
    - name: "billing"
      public_api: "billing/api/**"
      internal: "billing/internal/**"
  rules:
    cross_module_access_via_public_api_only: true
    no_shared_internal_imports: true
    allowed_cross_dependencies:
      orders: ["customers"]
      billing: ["customers", "orders"]
```

#### Feature-Sliced Design

```yaml
architecture:
  style: feature_sliced_design
  rule_pack_version: "2.0.0"
layout:
  layers_order:
    - shared
    - entities
    - features
    - widgets
    - pages
    - app
  paths:
    shared: "src/shared/**"
    entities: "src/entities/**"
    features: "src/features/**"
    widgets: "src/widgets/**"
    pages: "src/pages/**"
    app: "src/app/**"
  rules:
    upper_layer_imports_lower_only: true
    same_layer_no_cross_imports: true
    public_api_only: true
```

#### Vertical Slice

```yaml
architecture:
  style: vertical_slice
  rule_pack_version: "1.0.0"
layout:
  features_root: "src/Features/"
  shared_kernel: "src/Shared/"
  rules:
    no_cross_feature_imports: true
    shared_kernel_only_for_primitives: true
    each_feature_self_contained:
      required_components: ["Handler", "Validator", "Response"]
```

#### Event-Driven / CQRS

```yaml
architecture:
  style: event_driven_cqrs
  rule_pack_version: "1.1.0"
layout:
  commands_path: "src/commands/**"
  queries_path: "src/queries/**"
  events_path: "src/events/**"
  handlers_path: "src/handlers/**"
  rules:
    commands_dont_return_data: true
    queries_are_readonly: true
    events_are_immutable: true
    no_sync_between_bounded_contexts: true
```

---

## 5. Catálogo de Rule Packs

Repositorio Git separado (`arch-rules-catalog/`) gestionado como producto interno.

### 5.1 Estructura del catálogo

```
arch-rules-catalog/
├── README.md
├── CONTRIBUTING.md
├── packs/
│   ├── hexagonal/
│   │   ├── 1.0.0/
│   │   ├── 2.0.0/
│   │   └── 2.3.0/
│   │       ├── manifest.yaml
│   │       ├── detectors/
│   │       │   ├── layer_violation.py
│   │       │   ├── direction_check.py
│   │       │   └── port_adapter.py
│   │       ├── prompts/
│   │       │   ├── system.md
│   │       │   ├── violation_analysis.md
│   │       │   └── few_shot_examples.yaml
│   │       ├── rag_seed/
│   │       │   ├── clean_architecture_principles.md
│   │       │   └── canonical_examples/
│   │       ├── severity_matrix.yaml
│   │       └── tests/
│   │           ├── violations/
│   │           └── clean_code/
│   ├── mvc/
│   ├── microservices/
│   └── ...
├── universal_rules/
│   ├── circular_dependencies/
│   ├── god_object/
│   ├── cyclomatic_complexity/
│   └── solid_violations/
├── style_detector/
│   └── detector.py
└── schema/
    └── architecture_yaml_v1.json
```

### 5.2 `manifest.yaml` de un rule pack

```yaml
name: hexagonal
version: 2.3.0
description: "Reglas para Hexagonal/Clean/Onion Architecture"
maintainers: ["@arch-team"]
applies_to_languages: ["python", "typescript", "java", "csharp", "kotlin"]
min_engine_version: "1.5.0"

detectors:
  - id: layer_violation
    type: deterministic
    severity_default: critical
  - id: dependency_direction
    type: deterministic
    severity_default: critical
  - id: port_without_adapter
    type: deterministic
    severity_default: warning
  - id: domain_logic_leak
    type: llm_based
    severity_default: warning
    requires_rag: true

llm_config:
  recommended_model: "claude-sonnet-4-5"
  temperature: 0.1
  max_tokens_per_analysis: 4000

changelog:
  - version: "2.3.0"
    changes:
      - "Mejorado detector de domain_logic_leak con 15 few-shot examples"
      - "Reducido FP rate en proyectos TypeScript con Nest.js"
```

### 5.3 Versionado SemVer

- **MAJOR**: cambia comportamiento — código antes válido ahora viola (breaking).
- **MINOR**: añade reglas/detectores sin romper existentes.
- **PATCH**: refina precisión, corrige FP.

Consumo desde repos:

- `rule_pack_version: "2.3.0"` — pin exacto (reproducible).
- `rule_pack_version: "2.3.x"` — patches automáticos (recomendado).
- `rule_pack_version: "2.x"` — minors automáticos (equipos maduros).

### 5.4 Ciclo de vida de un rule pack

1. **Propuesta (RFC)**: PR al catálogo con justificación, alcance, ejemplos.
2. **Experimental** (`0.x.y`, `stability: experimental`): opt-in, métricas 4-6 semanas.
3. **Estabilización** (`1.0.0`, `stability: stable`): tras precisión ≥85% y FP ≤10% en 5+ repos.
4. **Mantenimiento**: patches mensuales; majors máx. cada 6 meses.

### 5.5 CI/CD del catálogo

- Tests de cada pack contra su `tests/` (gold dataset).
- Regresión contra muestra de 20 repos reales (compara con versión anterior).
- Validación de schema del `manifest.yaml`.
- Linter de prompts (verifica formato JSON de salida).

### 5.6 Distribución y consumo

El motor al arrancar contra un repo:

1. Lee `.architecture.yaml`.
2. Resuelve `rule_pack_version` contra catálogo (clone o registry interno).
3. Carga detectores, prompts, RAG seed.
4. Cachea localmente (TTL 24h).

Air-gapped: mirror en Artifactory/Nexus como artefactos versionados.

---

## 6. Roadmap por Hitos

> **Estado**: ✅ done · 🚧 in-progress · ⏳ pending

| Hito | Estado | Duración | Foco | Commit |
|---|---|---|---|---|
| H0 | ✅ | Semana 1 | Setup y fundaciones | `d9968cf` |
| H1 | ✅ | Semanas 2-3 | Esquema y detector de estilo | `99c9739` |
| H2 | ✅ | Semanas 4-5 | Motor core + reglas universales | _en proceso de push_ |
| H3 | ⏳ | Semanas 6-7 | Primer rule pack (Hexagonal) + RAG | — |
| H4 | ⏳ | Semana 8 | Rule packs adicionales (MVC, Microservicios) | — |
| H5 | ⏳ | Semanas 9-10 | Integración CI/CD + bot de comentarios | — |
| H6 | ⏳ | Semanas 11-12 | Modo sombra y dashboard | — |
| H7 | ⏳ | Semana 13 | Go-live piloto + capacitación | — |

**Total: 13 semanas para MVP** con 3 estilos arquitectónicos + reglas universales.

### Progreso por feature

#### H0 — Setup y Fundaciones ✅

- ✅ F0.1 Repositorios y estructura monorepo (`packages/engine`, `packages/catalog`)
- ✅ F0.2 Tooling base (uv workspace, ruff, mypy strict, black, pytest, structlog, pydantic-settings, pre-commit, Dockerfile)
- ✅ F0.3 CI del proyecto (GitHub Actions: lint + typecheck + test + docker, dependabot, badges)
- ✅ F0.4 Acceso LLM + observabilidad (AnthropicLLMClient, BudgetGuard, LangfuseTracer/NullTracer, docker-compose.dev.yml, secrets doc)
- ✅ F0.5 Dataset gold inicial (18 casos, JSON Schema, GoldDataset loader)

**Estado engine**: 20 tests passing · coverage 83.78% · mypy strict clean · ruff clean.

#### H1 — Esquema y Detector de Estilo ✅

- ✅ F1.1 JSON Schema del `.architecture.yaml` (`packages/catalog/schema/architecture_yaml_v1.json`)
- ✅ F1.2 Parser y validador con Pydantic (`engine.config`)
- ✅ F1.3 Detector heurístico de estilos (folder + manifest + filename signals, runner-up-weighted confidence)
- ✅ F1.4 Resolver: declarado > detectado (≥0.8) > universal + warning de divergencia
- ✅ F1.5 Tests sobre 6 fixtures sintéticos (hexagonal, mvc, microservices, modular_monolith, fsd, ambiguous)

**Estado engine**: 41 tests passing · coverage 89.35% · mypy strict clean · ruff clean.

#### H2 — Motor Core + Reglas Universales ✅

- ✅ F2.1 Diff extractor (`LocalGitDiff` + `DiffSource` protocol, cap por archivos/changes)
- ✅ F2.2 AST analyzer Tree-sitter (Python, TS, TSX, JS, Java) + import DiGraph
- ✅ F2.3 Circular dependencies (Tarjan vía `networkx`, SCC >1 → Finding crítico)
- ✅ F2.4 God Object (2-of-3 thresholds: methods, LOC, fan-out; LCOM4 diferido)
- ✅ F2.5 Cyclomatic complexity (McCabe sobre AST, dos niveles warn/critical)
- ✅ F2.6 Pydantic `Finding` + `AnalysisReport` (sort, severity counts, JSON)
- ✅ Universal analyzer orchestrator + 10-violation bench fixture (10/10 detectados)
- ✅ ADR-0001 documenta decisiones técnicas

**Estado engine**: 60 tests passing · coverage 82.93% · mypy strict clean · ruff clean.

#### H3 — Primer Rule Pack (Hexagonal) + RAG ⏳

- ⏳ F3.1 Carga de rule packs desde catálogo (cache TTL)
- ⏳ F3.2 Detectores deterministas Hexagonal (layer_violation, dependency_direction, port_without_adapter)
- ⏳ F3.3 Pipeline LLM con LangGraph (retry, validación Pydantic)
- ⏳ F3.4 RAG con Qdrant + Voyage embeddings + LlamaIndex chunking
- ⏳ F3.5 Prompt `domain_logic_leak` con 10-15 few-shot
- ⏳ F3.6 Budget guard de costos integrado en pipeline

#### H4 — Rule Packs MVC y Microservicios ⏳

- ⏳ F4.1 Rule pack MVC v1.0.0
- ⏳ F4.2 Rule pack Microservicios v1.0.0
- ⏳ F4.3 Refactor `engine.detector_base` si emergen abstracciones comunes
- ⏳ F4.4 Documentación "Cómo crear un rule pack" + cookiecutter

#### H5 — Integración CI/CD + Bot de Comentarios ⏳

- ⏳ F5.1 GitHub Action `arch-guardian-action`
- ⏳ F5.2 Cliente GitHub GraphQL para comentarios
- ⏳ F5.3 Mecanismo de bloqueo por severidad
- ⏳ F5.4 Comando `/ai-ignore` con razones tipadas + persistencia PostgreSQL
- ⏳ F5.5 Adaptadores GitLab CI y Bitbucket Pipelines
- ⏳ F5.6 Endpoints `/health` y `/metrics`

#### H6 — Modo Sombra y Calibración ⏳

- ⏳ F6.1 Modo `shadow` (persist findings, no comments)
- ⏳ F6.2 Dashboard Metabase
- ⏳ F6.3 UI Streamlit de etiquetado TP/FP
- ⏳ F6.4 Promptfoo regresión (bloquea PRs que degradan precisión >2%)
- ⏳ F6.5 A/B testing prompts Langfuse
- ⏳ F6.6 Ajuste fino basado en datos

#### H7 — Go-Live Piloto y Capacitación ⏳

- ⏳ F7.1 Activación gradual (shadow → comment-only → block)
- ⏳ F7.2 Material capacitación (slide deck + Loom + FAQ)
- ⏳ F7.3 Canal Slack `#arch-guardian` + bot
- ⏳ F7.4 Runbook de incidentes
- ⏳ F7.5 Métricas ejecutivas (sin métricas individuales)
- ⏳ F7.6 Plan rollout post-piloto

---

## 7. Hitos Detallados

### Hito H0 — Setup y Fundaciones (Semana 1)

**Objetivo**: infraestructura técnica y organizacional lista.

#### Features

- **F0.1** — Repositorios y estructura
  - Crear: `arch-guardian-engine`, `arch-rules-catalog`, `arch-guardian-action`
  - Configurar branch protection, templates de PR/issue
- **F0.2** — Tooling base del motor
  - Python 3.12 con `uv` o Poetry
  - Pre-commit: ruff, mypy, black
  - pytest + coverage
  - Dockerfile multi-stage
  - `structlog`, `pydantic-settings`
- **F0.3** — CI del propio proyecto
  - GitHub Actions: lint, type-check, tests, build Docker, publish GHCR
  - Cobertura mínima: 70%
- **F0.4** — Acceso a LLMs y observabilidad
  - API keys Anthropic en Vault
  - Langfuse self-hosted desplegado
- **F0.5** — Dataset gold inicial
  - 30-50 fragmentos etiquetados en `arch-rules-catalog/datasets/gold-v1/`
  - Versionado YAML, revisado por tech lead

#### Done

- Tres repos con CI verde.
- Llamada de prueba al LLM trazada en Langfuse.
- Dataset gold versionado y revisado.

---

### Hito H1 — Esquema y Detector de Estilo (Semanas 2-3)

**Objetivo**: el sistema sabe qué arquitectura sigue cada repo.

#### Features

- **F1.1** — JSON Schema del `.architecture.yaml`
  - `schema/architecture_yaml_v1.json`, validación estricta
  - Docs HTML con `json-schema-for-humans`
- **F1.2** — Parser y validador
  - Módulo `engine.config`, salida Pydantic tipada
  - Errores legibles (no stack traces)
- **F1.3** — Detector heurístico
  - Módulo `engine.style_detector` → `{style, confidence, evidence}`
  - Cubre los 3 estilos MVP + fallback `unknown`
  - Heurísticas: nombres de carpetas, manifiestos (`package.json`, `pom.xml`), imports
- **F1.4** — Resolver de estilo
  - Módulo `engine.resolver`: archivo > detección (conf >0.8) > universal
  - Loguea decisión y evidencia
- **F1.5** — Tests sobre repos sintéticos
  - 6 fixtures en `tests/fixtures/` (uno por estilo + híbrido)

#### Done

- Repo con `.architecture.yaml` válido: carga sin error.
- Repo sin archivo, estructura clara: detección con conf >0.8.
- Repo ambiguo: fallback universal con warning.

---

### Hito H2 — Motor Core + Reglas Universales (Semanas 4-5)

**Objetivo**: análisis funcional mínimo, valor incluso sin rule pack específico.

#### Features

- **F2.1** — Extractor de diff y contexto
  - Módulo `engine.diff_extractor` vía API GitHub/GitLab
  - Limita tamaño máx (default 50k tokens)
- **F2.2** — Análisis AST con Tree-sitter
  - Módulo `engine.ast_analyzer`: grafo deps, métricas (LOC, complejidad, fan-in/out)
  - Soporte Python, TypeScript, Java
- **F2.3** — Detector de dependencias circulares
  - Tarjan sobre grafo de imports
  - SCC con tamaño >1 = critical
- **F2.4** — Detector de God Objects
  - LOC >500, métodos públicos >25, LCOM4 alto
  - Severidad: warning
- **F2.5** — Detector de complejidad ciclomática
  - >15 warning, >25 error
  - Configurable por `universal_rules`
- **F2.6** — Sistema de severidad y agregación
  - Pydantic `Finding`: rule_id, severity, file, line, message, suggested_fix, rule_pack_source
  - Reporte JSON único por análisis

#### Done

- Repo Py/TS medio (500-2000 archivos) <60s sin LLM.
- Detecta 8/10 violaciones plantadas en repo sintético.
- Reporte JSON valida contra schema.

---

### Hito H3 — Primer Rule Pack (Hexagonal) + RAG (Semanas 6-7)

**Objetivo**: capacidad analítica completa LLM + RAG sobre estilo concreto.

#### Features

- **F3.1** — Carga de rule packs
  - Módulo `engine.rule_pack_loader`: descarga vía git tag o registry
  - Valida manifest, carga detectores y prompts, cache local TTL
- **F3.2** — Detectores deterministas Hexagonal
  - `layer_violation`, `dependency_direction`, `port_without_adapter`
  - Tests aislados por detector
- **F3.3** — Pipeline LLM con LangGraph
  - Determinista → ambiguo → LLM → Pydantic valida → retry si malformado
  - Tracing Langfuse
- **F3.4** — RAG con Qdrant
  - Indexa `knowledge_base.adr_path` + `rag_seed/`
  - Chunking LlamaIndex, embeddings Voyage AI
  - Top-5 chunks por diff inyectados en prompt
- **F3.5** — Prompt `domain_logic_leak`
  - System + 10-15 few-shot examples
  - Validación contra gold del pack
- **F3.6** — Budget guard
  - Cap configurable por PR (default $1 USD)
  - Métricas: tokens in/out, costo, latencia

#### Done

- PR Hexagonal: ≥90% violaciones del gold detectadas.
- FP rate ≤15% en 20 PRs reales.
- Costo promedio ≤$0.20/PR.
- Trazas completas en Langfuse.

---

### Hito H4 — Rule Packs MVC y Microservicios (Semana 8)

**Objetivo**: validar que la abstracción de rule packs escala.

#### Features

- **F4.1** — Rule pack MVC v1.0.0
  - Detectores: `business_logic_in_view`, `fat_controller`, `model_imports_view`
  - Few-shot Django/Rails/Laravel
- **F4.2** — Rule pack Microservicios v1.0.0
  - Detectores: `shared_database_access`, `sync_cross_service_call`, `cross_service_import`
  - Prompts para acoplamiento implícito
- **F4.3** — Refactor del engine
  - Extraer abstracciones comunes a `engine.detector_base`
  - Sin romper interfaces
- **F4.4** — Docs "Cómo crear un rule pack"
  - `CONTRIBUTING.md` + scaffold cookiecutter

#### Done

- Tres packs (Hexagonal, MVC, Microservicios) ≥85% precisión en sus golds.
- Ingeniero externo crea pack experimental en <4h siguiendo la guía.

---

### Hito H5 — Integración CI/CD + Bot de Comentarios (Semanas 9-10)

**Objetivo**: herramienta consumible desde un PR real.

#### Features

- **F5.1** — GitHub Action `arch-guardian-action`
  - Parámetros: `style`, `rule-pack-version`, `severity-threshold`, `mode` (block/comment-only/shadow)
  - Publicada en marketplace privado
- **F5.2** — Cliente GitHub para comentarios
  - GraphQL, agrupado por archivo
  - Evita duplicados entre commits
  - Actualiza comentarios obsoletos
- **F5.3** — Mecanismo de bloqueo
  - Exit code 0/1 según severidad
  - Solo `critical` bloquea por defecto
- **F5.4** — Comando `/ai-ignore` tipado
  - Razones enum: `false-positive`, `intentional-deviation`, `legacy-code-exception`, `urgent-hotfix`
  - Persiste en PostgreSQL
- **F5.5** — Adaptadores GitLab CI y Bitbucket Pipelines
  - Mismo engine, distintos publishers
  - Test integración con repo demo en cada plataforma
- **F5.6** — Endpoints `/health` y `/metrics`
  - Prometheus format

#### Done

- Repo nuevo integra guardián en <30min siguiendo README.
- PR con violaciones intencionales: comentarios en <3min.
- Bloqueo solo en `critical`.
- `/ai-ignore` funciona y se loguea.

---

### Hito H6 — Modo Sombra y Calibración (Semanas 11-12)

**Objetivo**: validar precisión en producción real sin fricción.

#### Features

- **F6.1** — Modo `shadow`
  - Ejecuta análisis sin publicar comentarios
  - Persiste hallazgos en PostgreSQL con metadatos
- **F6.2** — Dashboard Metabase
  - Violaciones/día, por estilo, por pack, FP rate, costo, latencia p95
  - Filtros por equipo/repo
- **F6.3** — Workflow de etiquetado
  - UI Streamlit mínima
  - Tech leads etiquetan TP/FP/needs-discussion
- **F6.4** — Promptfoo regresión
  - Bloquea PRs al catálogo que degradan precisión >2%
- **F6.5** — A/B testing prompts Langfuse
  - Dos versiones en paralelo (10% tráfico)
- **F6.6** — Ajuste fino basado en datos
  - Refinar prompts/umbrales, bump versiones patch

#### Done

- Modo sombra en 3-5 repos piloto ≥2 semanas.
- FP rate global ≤10%.
- Precision en `critical` ≥95%.
- Aprobación formal tech leads para go-live.

---

### Hito H7 — Go-Live Piloto y Capacitación (Semana 13)

**Objetivo**: activación controlada, maximizar adopción.

#### Features

- **F7.1** — Activación gradual
  - Piloto: `shadow` → `comment-only` (1 semana) → bloqueo `critical`
- **F7.2** — Material de capacitación
  - Slide deck 90min, Loom 5min, FAQ Notion/Confluence
  - Decision tree "qué hacer cuando el bot comenta"
- **F7.3** — Canal Slack `#arch-guardian`
  - Bot con comandos: estado, últimas violaciones, abrir ticket
- **F7.4** — Runbook de incidentes
  - Qué hacer: bot caído, alertas en masa, LLM down, rollback pack
- **F7.5** — Métricas ejecutivas
  - Dashboard CTO/VP: deuda detectada, violaciones prevenidas, impacto en tiempo de review, ROI
  - **Nunca métricas individuales por dev**
- **F7.6** — Plan rollout post-piloto
  - Cronograma semanal de expansión, criterios de inclusión

#### Done

- Piloto operando con bloqueo activo.
- Taller ejecutado, grabación publicada.
- NPS interno ≥+30.
- Cero incidentes de severidad alta en semana de go-live.

---

## 8. Hitos Post-MVP

| Hito | Foco |
|---|---|
| H8 | Rule packs adicionales: Modular Monolith, FSD, Vertical Slice, Event-Driven |
| H9 | Soporte Llama 3.3 self-hosted (clientes IP sensible) |
| H10 | Auto-aprendizaje: prompts mejoran con feedback de `/ai-ignore` |
| H11 | Integración SonarQube + SAST (vista unificada) |
| H12 | API pública: otras herramientas consultan estado arquitectónico |

---

## 9. Mitigación de Riesgos

### Falsos positivos
- `/ai-ignore` con razón **enum cerrado** (no texto libre) → análisis cuantitativo y auto-tuning futuro.

### Costos
- **Filtro estático previo** cubre 60-70% sin LLM.
- **Budget guard** corta llamadas si PR supera $1 USD.
- PRs >2000 LOC (merges de branches): analizar de otra forma o pedir revisión humana directa.

### Fricción cultural
- **2-3 arch-bot champions por equipo** durante primeros 3 meses (tiempo asignado oficialmente).
- Comunicación: "asistente, no policía". Bot aprende del equipo.
- Métricas son de **salud del codebase**, nunca de productividad individual.

### Privacidad / IP sensible
- Stack idéntico, solo cambia endpoint del LLM:
  - Azure OpenAI con Private Endpoint, **o**
  - vLLM con Llama 3.3 70B en GPU on-prem (A100/H100, mín 80GB VRAM).

### Estilo declarado ≠ estilo real
- Detector heurístico **siempre corre en paralelo** a la declaración.
- Discordancia >30% archivos no encajan: comentario informativo **no bloqueante** sugiriendo revisar perfil.

---

## 10. Métricas de Éxito a 90 Días Post Go-Live

- **-40%** violaciones arquitectónicas que alcanzan `main`.
- **-25%** tiempo medio de code review para PRs estándar.
- **≥90%** comentarios del bot percibidos como útiles (encuesta cuatrimestral).
- **Costo total operativo ≤ $500 USD/mes** para org de ~50 devs activos.

---

## 11. Convenciones de Trabajo

- **Branching**: trunk-based con feature flags. Branches de feature efímeras (<3 días).
- **Commits**: Conventional Commits (`feat:`, `fix:`, `chore:`, etc.).
- **PRs**: máximo 400 LOC. Plantilla obligatoria con checklist.
- **Definition of Done por feature**: código + tests (cobertura ≥80% del módulo nuevo) + docs actualizadas + observabilidad (logs/métricas si aplica) + revisión por al menos 1 par.
- **Release**: tag SemVer en cada hito, changelog generado.
