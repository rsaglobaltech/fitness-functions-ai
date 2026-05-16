# ADR-0001: Technical choices for the H2 universal engine

- **Status**: accepted
- **Date**: 2026-05-16
- **Hito**: H2 — Motor core + reglas universales

## Context

H2 builds the language-agnostic analysis core: parse source code, extract a
dependency graph, run universal rules (cycles, God Objects, complexity), and
emit structured findings. These decisions are load-bearing for the rest of the
project — H3 onwards plugs *into* this core.

## Decisions

### D1 — AST parsing: **Tree-sitter** (with per-language grammars)

**Why:**
- Single API across Python, TypeScript, Java, Go, Ruby, Kotlin, C#, JavaScript.
  Adding a new language is "install grammar + map node names", not a rewrite.
- Error-tolerant: parses incomplete / syntactically-broken files instead of
  crashing — important because we run on PR diffs which can be partial.
- Incremental parsing baked in. Cheap to re-parse on file changes.
- Pure Python bindings (`tree-sitter` package) — no JVM, no native daemon.

**Alternatives rejected:**
- Python `ast` only: fine for Python but we need polyglot.
- LibCST: too Python-specific.
- ANTLR: heavy runtime, slower to bootstrap new languages.
- LLM-only parsing: too expensive and non-deterministic for structural facts.

**Cost:** ~30 MB of grammar wheels per language; one-time at install.

### D2 — Dependency graph + cycles: **`networkx` + Tarjan SCC**

**Why:**
- `networkx.strongly_connected_components` is the canonical, well-tested
  implementation of Tarjan's algorithm. Reimplementing it would only add bugs.
- Graphs are tiny by computer-science standards (typical repos: 500–5000
  modules). NetworkX is overkill on perf but unbeatable on ergonomics.
- A SCC of size >1 *is* a circular dependency. Definition is mechanical;
  no LLM needed.

**Alternatives rejected:**
- `graph-tool`: faster but C++ build dep, painful in CI runners.
- Hand-rolled Tarjan: same complexity, more surface for bugs.

### D3 — Cyclomatic complexity: **McCabe walk over Tree-sitter AST**

**Why:**
- McCabe's metric is defined as `E - N + 2` where E/N are edges/nodes in the
  control-flow graph. In practice everyone computes the equivalent simpler
  form: 1 + (count of decision points). That's what we do.
- Decision points per language are a short, stable list: `if`, `elif`, `for`,
  `while`, `case`, `&&`, `||`, ternary, `except`/`catch`. Walking the AST and
  counting matching node kinds is ~50 LOC per language.
- Reusing an existing library (`radon`, `lizard`) would either be
  Python-only (`radon`) or shell out to a separate binary (`lizard`). Both
  break our polyglot story.

**Trade-off:** we recompute results that `radon` would give us for Python.
Acceptable — uniformity beats marginal speed.

### D4 — God Object: **threshold-on-metrics, no LCOM4 (yet)**

**Why:**
- Three metrics catch the bulk of God Objects in field studies:
  class LOC, public-method count, and fan-out (number of distinct external
  modules referenced).
- LCOM (Lack of Cohesion of Methods) variants — especially LCOM4 — give a
  more principled signal but require building a per-class method/attribute
  bipartite graph. Adds ~150 LOC and another set of edge cases (inheritance,
  decorators, static methods, language-specific attribute access).
- We can ship without LCOM4 and revisit once we have FP/FN data from shadow
  mode (H6). YAGNI applied with eyes open.

**Configurable via `.architecture.yaml`:** thresholds live in
`universal_rules.god_object_threshold`. Tuned per-repo with one line.

### D5 — Diff extraction: **`httpx` + provider abstractions, local-first**

**Why:**
- We need both *remote* (GitHub/GitLab API for CI mode) and *local* (`git`
  for dev mode / offline runs). A thin `DiffSource` protocol with two
  implementations keeps the engine testable without network.
- `httpx` over `requests` for async support (needed for LangGraph pipeline
  in H3) and HTTP/2 reuse.
- We cap the diff size in tokens up-front. Big merges (>2000 LOC) get the
  "review human" treatment as the plan mandates.

### D6 — Finding model: **Pydantic, frozen, single schema**

**Why:**
- All detectors emit the same shape. Pydantic gives us validation,
  serialization (JSON for CI / publisher), and `model_dump` for free.
- `frozen=True` prevents accidental in-place mutation while the report is
  being aggregated — a class of bug we don't want.
- `Severity` enum is shared with `engine.config` so rule packs and universal
  rules speak the same language.

### D7 — Orchestration: **simple sequential `UniversalAnalyzer`, no LangGraph yet**

**Why:**
- H2 has no LLM step. LangGraph buys nothing — it's just sequential function
  calls today. Pulling it in would be a premature abstraction.
- When H3 adds the LLM step we *do* introduce LangGraph for retries and
  branching. At that point the orchestrator boundary is already in place.

## Consequences

- Tests are fast (Tree-sitter parses small fixtures in < 50 ms; the whole
  detector suite runs in < 2 s on CI).
- We pay for polyglot uniformity with ~30 MB of grammar wheels. Acceptable.
- LCOM4 is a known omission tracked for post-H6 work.
- Diff size guardrail is conservative (50k tokens) — easy to relax once we
  have real PR data.
