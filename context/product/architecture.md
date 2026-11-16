# System Architecture Overview: Workplace Agent

> Greenfield repository: the only files present are AWOS scaffolding and `context/product/product-definition.md`, so no choice below is inherited from existing code. Choices come from the `/awos:architecture` prompt (marked **[given]**) or are best-practice defaults (marked **[assumption]**).
>
> **Delivery order:** Spec 1 = document ingestion pipeline + query CLI. Later specs = agent API, Entra ID + Graph tools, QLoRA experiment. Spec 1 must not depend on anything that needs Entra app registration or Graph consent.

---

## 1. Application & Technology Stack

- **Language & runtime:** Python 3.12 **[given]**
- **Project & dependency management:** uv with a single `pyproject.toml` and lockfile **[given]**. Alternative: Poetry.
- **Package layout:** one installable package (`src/workplace_agent/`) with modules per concern: `ingestion/` (load, parse, chunk, embed, index), `retrieval/` (search + answer), `config.py`, `cli.py`. Later specs add `api/`, `agent/`, `graph_tools/`. **[assumption]**
- **CLI:** Typer, with commands `ingest` (run the pipeline over the blob container) and `ask "<question>"` (answer with citations). **[assumption]** Alternative: argparse.
- **Configuration:** pydantic-settings, reading environment variables or a `.env` file. Endpoints only; no keys in config when Entra ID auth is available. **[assumption]**
- **Azure SDKs:** `azure-identity` (DefaultAzureCredential), `azure-storage-blob`, `azure-ai-documentintelligence`, `azure-search-documents`, `openai` (Azure OpenAI client). **[assumption]**
- **Chunking:** a custom splitter over Document Intelligence's Markdown output. It splits on headings first, then caps chunks at about 512 tokens with about 64 tokens of overlap (counted with `tiktoken`), and keeps the page number and section heading for each chunk. **[assumption]** Alternative: LangChain text splitters (more dependencies, less control).
- **Answer generation:** a retrieve-then-generate flow written in plain Python:
  - Hybrid search returns the top 5 chunks.
  - The prompt numbers the sources, and the model must cite them as `[n]`.
  - If nothing relevant is retrieved, the answer says "not found in the documents" and does not guess.
  
  No agent framework is used in Spec 1. **[assumption]**
- **Agent layer (later spec):** Microsoft Foundry Agent Service (Azure AI Foundry), calling the retrieval function and Graph tools as function tools. **[given]** Alternative: LangGraph or Semantic Kernel. Exactly one orchestrator is used, never both.
- **Backend API (later spec):** FastAPI on Uvicorn, serving the chat endpoint and a minimal chat page. **[given]**
- **Quality tooling:** ruff (lint + format), pytest. **[given]** mypy in non-strict mode. **[assumption]**

---

## 2. Data & Persistence

- **Source document store:** Azure Blob Storage (Standard LRS), one container `documents` holding 10–20 sample company PDFs (HR policy, travel and expenses, IT security, onboarding). **[given]** The sample documents are written or public-domain, with no real company data.
- **Search / vector index:** Azure AI Search, **Free tier** (limit: 50 MB, 3 indexes, one Free service per subscription). **[given]** Index `workplace-docs` has these fields:
  - `id` (key), `doc_id`, `title`, `source_path`, `page_number`, `section`, `chunk_index`
  - `content` (searchable text)
  - `content_vector` (1536 dimensions, HNSW, cosine)
  - `content_hash`, `ingested_at`

  Queries run as **hybrid search** (keyword + vector, merged with RRF). The semantic ranker is optional; enable it only if the free plan quota allows.
- **Idempotent re-ingestion:**
  - Each document ID is a hash of its blob path, and each chunk ID is `{doc_id}-{chunk_index}`.
  - A document is re-processed only if its content hash changed.
  - Chunks are written with `merge_or_upload`.
  - Leftover chunks from a shorter new version of a document are deleted.

  **[assumption]**
- **Conversation state (later spec):** Foundry Agent Service threads. No database of our own until a feature needs one. **[assumption]**
- **Secrets:** Azure Key Vault (standard tier), used only where key-based auth is unavoidable. **[given]**
- **Evaluation data:** a versioned JSONL file in the repo (`eval/questions.jsonl`, about 20 questions with expected source documents). **[assumption]**

---

## 3. Infrastructure & Deployment

- **Cloud provider:** Microsoft Azure, on an *Azure for Students* subscription ($200 credit, **expires 2026-11-27**). **[given]**
- **Region:** Sweden Central (good model availability); East US 2 as fallback. **[confirmed]** Student subscriptions may restrict regions through policy; confirm before the first deployment.
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
  - Chat: `gpt-4o-mini` **[given]**. If it is retired or has no quota in the chosen region, use the current smallest GPT mini model available there.
  - Both use Standard / GlobalStandard deployments with low TPM quotas.
- **Document Intelligence tier:** S0 (pay per page). **[confirmed]** The F0 free tier only analyses the first 2 pages of each document, which would quietly break the pipeline. At about 10–20 PDFs the cost is cents.
- **Identity & access:**
  - Local development: DefaultAzureCredential using `az login`.
  - Deployed workloads (later specs): a user-assigned managed identity.
  - Access is granted with role assignments: Storage Blob Data Reader, Cognitive Services OpenAI User, Cognitive Services User, Search Index Data Contributor.
  
  **[given]** If the AI Search Free tier does not accept Entra-based data access, fall back to its admin key stored in Key Vault. Verify this during Spec 1.
- **Compute (later spec):** Azure Container Apps (Consumption plan, scale to zero) running the FastAPI image, with Azure Container Registry (Basic). **[given]**
- **CI/CD:** GitHub Actions running ruff, pytest (unit tests only) and `bicep build` validation on every push and pull request. **[given]**
  - **No automated deployment from CI in Spec 1.** OIDC federation needs an Entra app registration in the Georgia Tech tenant, which may be blocked. Deployment runs from the developer's machine.
  - `azure-pipelines.yml` mirrors the same steps as an Azure DevOps port. **[given]**
- **Cost guardrails:**
  - Free or pay-per-use tiers everywhere (AI Search Free, Container Apps scale-to-zero, S0 per-page Document Intelligence, token-billed models).
  - A subscription budget alert at $25, if the student subscription supports budgets.
  - Delete the resource group before the credit expires.
  
  **[assumption]**
- **Source control:** public GitHub repository, trunk-based with short feature branches, Conventional Commits. **[assumption]**

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
