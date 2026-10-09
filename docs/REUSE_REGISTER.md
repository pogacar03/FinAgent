# Dependency and reuse register

All dependencies below were installed and imported in the local Python 3.11 environment. Exact transitive versions are in requirements.lock. No third-party repository source was copied.

| Package | Installed version | Declared license metadata | Source |
|---|---|---|---|
| fastapi | 0.142.4 | MIT | [upstream](https://github.com/fastapi/fastapi) |
| pydantic | 2.13.5 | MIT | [upstream](https://github.com/pydantic/pydantic) |
| SQLAlchemy | 2.1.4 | MIT | [upstream](https://github.com/sqlalchemy/sqlalchemy) |
| langgraph | 1.2.14 | MIT | [upstream](https://github.com/langchain-ai/langgraph) |
| langgraph-checkpoint-sqlite | 3.1.1 | MIT | [upstream](https://github.com/langchain-ai/langgraph) |
| langgraph-checkpoint-postgres | 3.1.2 | MIT | [upstream](https://github.com/langchain-ai/langgraph) |
| psycopg | 3.3.6 | LGPL-3.0-only | [upstream](https://github.com/psycopg/psycopg) |
| pytest | 9.1.1 | MIT | [upstream](https://github.com/pytest-dev/pytest) |
| opentelemetry-sdk | 1.45.1 | Apache-2.0 | [upstream](https://github.com/open-telemetry/opentelemetry-python) |
| opentelemetry-exporter-otlp-proto-http | 1.45.1 | Apache-2.0 | [upstream](https://github.com/open-telemetry/opentelemetry-python) |
| httpx | 0.28.1 | BSD-3-Clause | [upstream](https://github.com/encode/httpx) |

## Reference decisions

TradingAgents and AI Hedge Fund inform only the supplied design reference; this application uses original small adapters and official LangGraph APIs. No trading runtime was vendored. FinRobot operators were not copied; transparent original forward P/E and guarded DCF equations are independently tested. vectorbt is not used, avoiding its Commons Clause redistribution concerns. Langfuse is optional and integrated through the official OTel OTLP HTTP exporter; no Langfuse SDK or server is bundled. Local SDK traces and database audits work without credentials. Live Langfuse ingestion remains UNVERIFIED.

Official persistence API references: [LangGraph checkpointers](https://reference.langchain.com/python/langgraph.checkpoint.sqlite/SqliteSaver), [SQLAlchemy select/locking](https://docs.sqlalchemy.org/en/20/core/selectable.html).
