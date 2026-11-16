# System Architecture Overview: Workplace Agent

> **Spec 1 is built and verified (2026-11-16).** Choices marked **[built]** are implemented in the repository, and the evidence is in `context/spec/001-document-ingestion-and-qa-cli/`. The other markers are **[given]** (from the original `/awos:architecture` prompt), **[confirmed]** (decided with the user) and **[assumption]** (a best-practice default not yet exercised).
>
> **Delivery order:** Spec 1 = document ingestion pipeline + query CLI. Later specs = agent API, Entra ID + Graph tools, QLoRA experiment. Spec 1 must not depend on anything that needs Entra app registration or Graph consent.

---

## 1. Application & Technology Stack

- **Language & runtime:** Python 3.12 **[given]**
- **Project & dependency management:** uv with a single `pyproject.toml` and lockfile **[given]**. Alternative: Poetry.
- **Package layout:** one installable package (`src/workplace_agent/`) with modules per concern: `ingestion/` (load, parse, chunk, embed, index), `retrieval/` (search + answer), `config.py`, `cli.py`. Later specs add `api/`, `agent/`, `graph_tools/`. **[assumption]**
- **CLI:** Typer, with commands `ingest` (run the pipeline over the blob container), `ask "<question>"` (answer with citations) and `eval` (score the 20-question evaluation set). **[built]**
- **Configuration:** pydantic-settings, reading environment variables or a `.env` file. Endpoints only; no keys in config when Entra ID auth is available. **[assumption]**
- **Azure SDKs:** `azure-identity` (DefaultAzureCredential), `azure-storage-blob`, `azure-ai-documentintelligence`, `azure-search-documents`, `openai`. **[built]** Azure OpenAI is called through the GA **v1 API**: `openai.OpenAI(base_url="<endpoint>/openai/v1/")` with an Entra ID bearer-token provider (scope `https://cognitiveservices.azure.com/.default`). `AZURE_OPENAI_API_VERSION=v1` selects it, and a dated api-version falls back to the `AzureOpenAI` client.
- **Chunking:** a custom splitter over Document Intelligence's Markdown output. It splits on headings first, then caps chunks at about 512 tokens with about 64 tokens of overlap (counted with `tiktoken`), and keeps the page range (`page_start`/`page_end`) and section heading for each chunk. Document Intelligence returns tables that cross pages as separate per-page tables, so a continued table only gets a range when it fits in one chunk. **[built]** Alternative: LangChain text splitters (more dependencies, less control).
- **Answer generation:** a retrieve-then-generate flow written in plain Python:
  - Hybrid search returns the top 5 chunks.
  - The prompt numbers the sources, and the model must cite them as `[n]`.
  - The model returns structured JSON (`found`, sentences with cite numbers, `missing_part`).
  - Code then validates and renders the answer deterministically: it drops invalid cites and sentences that only say information is absent, applies the 150-word cap, deduplicates sources by document and page, and produces the exact not-found and partial-answer sentences.
  
  No agent framework is used in Spec 1. **[built]**
- **Agent layer (later spec):** Microsoft Foundry Agent Service (Azure AI Foundry), calling the retrieval function and Graph tools as function tools. **[given]** Alternative: LangGraph or Semantic Kernel. Exactly one orchestrator is used, never both.
- **Backend API (later spec):** FastAPI on Uvicorn, serving the chat endpoint and a minimal chat page. **[given]**
- **Quality tooling:** ruff (lint + format), pytest. **[given]** mypy in non-strict mode. **[assumption]**

---

## 2. Data & Persistence

- **Source document store:** Azure Blob Storage (Standard LRS), one container `documents` holding 10–20 sample company PDFs (HR policy, travel and expenses, IT security, onboarding). **[given]** The sample documents are written or public-domain, with no real company data.
- **Search / vector index:** Azure AI Search, **Free tier** (limit: 50 MB, 3 indexes, one Free service per subscription). **[given]** Index `workplace-docs` has these fields:
  - `id` (key), `doc_id`, `title`, `source_path`, `page_start`, `page_end`, `section`, `chunk_index` (chunk 0 is the document's commit marker)
  - `content` (searchable text)
  - `content_vector` (1536 dimensions, HNSW, cosine)
  - `content_hash`, `ingested_at`

  Queries run as **hybrid search** (keyword + vector, merged with RRF). The semantic ranker is optional; enable it only if the free plan quota allows.
- **Idempotent re-ingestion:**
  - Each document ID is a hash of its blob path, and each chunk ID is `{doc_id}-{chunk_index}`.
  - A document is re-processed only if its content hash changed.
  - Chunks are written with `merge_or_upload`.
  - Leftover chunks from a shorter new version of a document are deleted.
  - The content hash includes a pipeline version (`PIPELINE_VERSION`, chunk settings, embedding deployment).
  - Updated documents are written crash-safe: chunks 1..n-1 first, then stale ids are pruned, then chunk 0 is written last.
  - Deleted and renamed documents are removed by `doc_id`.

  **[built]**
- **Conversation state (later spec):** Foundry Agent Service threads. No database of our own until a feature needs one. **[assumption]**
- **Secrets:** Azure Key Vault (standard tier), used only where key-based auth is unavoidable. **[given]**
- **Evaluation data:** a versioned JSONL file in the repo (`eval/questions.jsonl`, about 20 questions with expected source documents). **[assumption]**

---

## 3. Infrastructure & Deployment

- **Cloud provider:** Microsoft Azure, on an *Azure for Students* subscription ($200 credit, **expires 2026-11-27**). **[given]**
- **Region:** Sweden Central. **[built]** The subscription has an "Allowed resource deployment regions" policy that permits only `belgiumcentral`, `switzerlandnorth`, `francecentral`, `germanywestcentral` and `swedencentral`. East US 2 is therefore **not** a usable fallback; the fallback is France Central or Germany West Central, depending on model availability.
- **Resource layout:** a single resource group `rg-workplace-agent-dev`. The whole environment is torn down with `az group delete`. **[given]**
- **Infrastructure as code:** Bicep in `infra/` (`main.bicep` plus modules), deployed with `az deployment group create` from the developer machine. **[confirmed]** Not Railway or another PaaS: they cannot provision Azure resources, and Bicep is a stated job requirement. Alternative: `azd` wrapping the same Bicep. Spec 1 provisions:
  - Storage account + container
  - Document Intelligence
  - Azure OpenAI / Foundry resource with two model deployments
  - AI Search (Free)
  - Key Vault
  - Log Analytics + Application Insights
  - Role assignments for the developer's user identity
- **Model deployments:**
  - Embeddings: `text-embedding-3-small`. **[given]**
  - Chat: **`gpt-5-mini` version 2025-08-07, GlobalStandard, capacity 30.** **[built]** It replaced `gpt-4o-mini`: version 2024-07-18 was rejected at preflight with `ServiceModelDeprecated` (deprecated since 2026-03-31), and the student subscription had 0 GlobalStandard quota for it. gpt-5-mini is a reasoning model, so it is called with `reasoning_effort="minimal"`, `max_completion_tokens` and structured outputs, with no `temperature`. The model name, version, SKU and capacity are Bicep parameters.
  - Embeddings use GlobalStandard with capacity 50.
- **Document Intelligence tier:** S0 (pay per page). **[confirmed]** The F0 free tier only analyses the first 2 pages of each document, which would quietly break the pipeline. At about 10–20 PDFs the cost is cents.
- **Identity & access:**
  - Local development: DefaultAzureCredential using `az login`.
  - Deployed workloads (later specs): a user-assigned managed identity.
  - Access is granted with role assignments: Storage Blob Data Contributor (the developer uploads samples), Cognitive Services OpenAI User, Cognitive Services User, Search Index Data Contributor, Search Service Contributor (the CLI creates the index) and Key Vault Secrets User.
  
  **[built]** **Verified: the AI Search Free tier accepts Entra ID data-plane auth** (`authOptions: aadOrApiKey`). Every service is reached without keys. The key-in-Key-Vault fallback (`searchUseKeyFallback`) is still implemented but unused.
- **Compute (later spec):** Azure Container Apps (Consumption plan, scale to zero) running the FastAPI image, with Azure Container Registry (Basic). **[given]**
- **CI/CD:** GitHub Actions running ruff, pytest (unit tests only) and `bicep build` validation on every push and pull request. **[given]**
  - **No automated deployment from CI in Spec 1.** OIDC federation needs an Entra app registration in the Georgia Tech tenant, which may be blocked. Deployment runs from the developer's machine.
  - `azure-pipelines.yml` mirrors the same steps as an Azure DevOps port. **[given]**
- **Cost guardrails:**
  - Free or pay-per-use tiers everywhere (AI Search Free, Container Apps scale-to-zero, S0 per-page Document Intelligence, token-billed models).
  - A subscription budget alert at $25, if the student subscription supports budgets. *(Kept as planned on 2026-11-16: not implemented yet.)*
  - Delete the resource group before the credit expires.
  
  **[assumption]**
- **Source control:** public GitHub repository (`shterjovad/workplace-agent`), trunk-based with short feature branches. **[built]** Conventional Commits is kept as the convention for future commits; the first 8 commits use plain imperative messages. **[assumption]**

---

## 4. External Services & APIs

- **Document parsing:** Azure AI Document Intelligence, `prebuilt-layout` model with Markdown output (tables kept, headings detected). **[given]** Alternative: Docling run locally (no cloud cost; the author has used it before).
- **LLM & embeddings:** Azure OpenAI through the Foundry resource. **[given]**
- **Authentication (later spec):** Microsoft Entra ID, using MSAL authorization code flow with PKCE for user sign-in and delegated permissions only. **[given]**
  - Constraint: the Georgia Tech tenant may block app registration and admin consent.
  - Plan: register the app in a tenant the author controls, as a multi-tenant app that also accepts personal Microsoft accounts.
  - The On-Behalf-Of flow is used only if a work tenant with consent rights becomes available.
- **Microsoft Graph (later spec):**
  - Delegated scopes `User.Read`, `Mail.Read`, `Mail.Send`, `Calendars.ReadWrite`.
  - All write operations go through a human-approval step: the API returns a pending action, and nothing executes until the user explicitly confirms it.
  - Graph calls go through one thin client that handles throttling (429 with Retry-After) and paging.

  **[given]**
- **Fine-tuning experiment (separate from the live app):**
  - Google Colab (T4) notebook in `notebooks/`, fine-tuning Qwen2.5-1.5B-Instruct with QLoRA (Hugging Face Transformers + PEFT + TRL + bitsandbytes) as an intent router.
  - Benchmarked against the Azure chat model on accuracy/F1, valid-JSON rate, latency and cost per 1,000 requests.
  - The model is not served in production in this version.

  **[given]**

---

## 5. Observability & Monitoring

- **Logging:** Python `logging` with JSON-structured output. Each ingestion run logs documents seen, skipped (unchanged), parsed, chunks written and deleted, and failures. **[assumption]**
- **Tracing & metrics:** Application Insights (workspace-based, on Log Analytics) via `azure-monitor-opentelemetry`. **[given]**
  - Traces cover each pipeline stage (parse, chunk, embed, index) and each `ask` call (retrieve, generate), with latency and token counts.
  - Tracing is off by default for local runs and turned on when `APPLICATIONINSIGHTS_CONNECTION_STRING` is set.
- **Error handling:**
  - Transient Azure errors (429/5xx) are retried with exponential backoff and jitter, using the SDKs' built-in retry policies.
  - One bad document is logged and skipped; it never stops the batch.
  - The CLI exits non-zero if any document failed.

  **[assumption]**
- **Quality evaluation:** an `eval` command runs `eval/questions.jsonl` through `ask` and reports:
  - retrieval hit rate (expected document among the top 5)
  - citation presence
  - p50/p95 latency

  These numbers feed the product success metrics (≥90% grounded with citations, p95 < 8 s). **[assumption]**
