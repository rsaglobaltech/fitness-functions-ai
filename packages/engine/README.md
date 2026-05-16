# arch-guardian-engine

Core engine for the architectural guardian. Loads architecture profiles, runs deterministic detectors, escalates to LLM for semantic checks, and produces structured findings.

## Layout

```
src/arch_guardian_engine/
├── __init__.py
├── config/         # .architecture.yaml parser + Pydantic schema
├── ast_analyzer/   # Tree-sitter based AST + dep graph
├── detectors/      # Universal rule detectors
├── style_detector/ # Heuristic architecture style detection
├── resolver/       # Style resolution (explicit > heuristic > universal)
├── rule_packs/     # Rule pack loader
├── llm/            # LLM client + LangGraph pipeline
├── rag/            # Qdrant + embeddings
├── publishers/     # GitHub/GitLab/Bitbucket comment publishers
└── cli.py          # Typer entrypoint
```
