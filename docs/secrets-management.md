# Secrets Management

> Status: H0 design. Implementation lands in H5 (CI/CD integration) when secrets are first injected into runners.

## Principles

1. **Never store secrets in source control.** `.env` is in `.gitignore`; only `.env.example` is committed.
2. **Never store secrets in CI/CD variables long-term.** Use them only as the *bootstrap* path to fetch from the secret manager.
3. **Rotate quarterly minimum** — Anthropic, Voyage, OpenAI, Langfuse, Qdrant API keys.
4. **Least privilege** — each environment (dev / staging / prod) gets a distinct credential scoped to its workload.

## Architecture

```
┌──────────────────┐      ┌──────────────────┐
│  HashiCorp Vault │◄─────│  CI/CD Runner    │  Short-lived OIDC token
│  (or AWS/Azure)  │      │  GitHub Actions  │
└────────┬─────────┘      └────────┬─────────┘
         │ TTL=10min secret         │
         ▼                          ▼
┌────────────────────────────────────────────┐
│        arch-guardian-engine container       │
│   (reads GUARDIAN_* env vars at boot)       │
└────────────────────────────────────────────┘
```

## Secret inventory

| Variable | Source | Rotation | Used by |
|---|---|---|---|
| `GUARDIAN_LLM_ANTHROPIC_API_KEY` | Anthropic console | 90 days | engine LLM client |
| `GUARDIAN_RAG_VOYAGE_API_KEY` | Voyage AI | 90 days | embeddings |
| `GUARDIAN_RAG_OPENAI_API_KEY` | OpenAI (optional fallback) | 90 days | embeddings |
| `GUARDIAN_RAG_QDRANT_API_KEY` | Qdrant cluster | 90 days | vector store |
| `GUARDIAN_OBS_LANGFUSE_PUBLIC_KEY` | Langfuse instance | 180 days | tracing |
| `GUARDIAN_OBS_LANGFUSE_SECRET_KEY` | Langfuse instance | 180 days | tracing |
| `POSTGRES_PASSWORD` (shadow mode) | Managed Postgres | 90 days | findings persistence |

## Vault paths (proposed)

```
secret/data/arch-guardian/{env}/llm/anthropic_api_key
secret/data/arch-guardian/{env}/rag/voyage_api_key
secret/data/arch-guardian/{env}/rag/qdrant_api_key
secret/data/arch-guardian/{env}/obs/langfuse_public_key
secret/data/arch-guardian/{env}/obs/langfuse_secret_key
```

Where `{env}` is `dev`, `staging`, or `prod`.

## CI/CD injection flow (GitHub Actions example, lands in H5)

1. Workflow authenticates to Vault via OIDC (no static token).
2. `hashicorp/vault-action` fetches the required secrets into `GITHUB_ENV`.
3. The runner starts the engine container with those env vars.
4. After the job, the env vars are discarded (no persistence).

## Local development

1. Copy `.env.example` to `.env`.
2. Fill only the keys you need (the engine falls back to NullTracer / errors only when actually used).
3. `direnv` or `python-dotenv` loads `.env` automatically — engine uses `pydantic-settings` so it picks up `.env` natively.

## Cloud-specific equivalents

- **AWS**: Secrets Manager + IRSA (for EKS) or IAM role (for EC2/Fargate).
- **Azure**: Key Vault + Managed Identity. For air-gapped clients, use Azure OpenAI Private Endpoint to keep traffic off the public internet.
- **GCP**: Secret Manager + Workload Identity.

## Audit

Every secret read is logged by Vault (or equivalent). The engine logs the
*name* of the secret it loaded, never the value. Pydantic `SecretStr` ensures
the value cannot be accidentally serialized.
