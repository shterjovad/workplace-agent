# Technical Specification: Document ingestion pipeline and grounded Q&A CLI

- **Functional Specification:** [functional-spec.md](./functional-spec.md)
- **Status:** Completed
- **Author(s):** Dona Shterjova, with the `python-backend` and `azure-infra` specialists

---

## 1. High-Level Technical Approach

This is a greenfield Python 3.12 package (`workplace_agent`, managed with uv) with a Typer CLI exposing three commands. Everything runs from the developer's machine against one Azure resource group, which is provisioned with Bicep.

- **`ingest`:**
  1. List the PDFs in the Blob container `documents`.
  2. Diff them against the state stored in the search index itself.
  3. Parse new or changed PDFs with Document Intelligence `prebuilt-layout` (Markdown output).
  4. Chunk them heading-aware, with physical page ranges.
  5. Embed with `text-embedding-3-small` and upsert into Azure AI Search (Free tier, hybrid search).
  6. Delete the chunks of removed documents.
- **`ask`:**
  1. Run a hybrid search for the top 5 chunks.
  2. Make one chat call with structured JSON output: sentences, each with cite numbers.
  3. Validate and render deterministically in code: citation checks, deduplicated sources, the 150-word cap, and the exact not-found and partial-answer sentences.
- **`eval`:** run 20 JSONL questions through `ask` and report hit rate, citation presence and p50/p95 latency against thresholds.

Azure services are reached only through small Protocol interfaces, so every unit test runs with in-memory fakes. Authentication uses Entra ID (`DefaultAzureCredential` after `az login`) everywhere it's supported. No secrets go in code or `.env`. There's no CI deployment: CI runs lint, unit tests and `az bicep build`.

---

## 2. Proposed Solution & Implementation Plan (The "How")

### 2.1 Repository layout

| Path | Responsibility |
|---|---|
| `pyproject.toml`, `uv.lock` | Package metadata, dependencies; ruff, pytest and mypy config (pytest marker `integration`) |
| `src/workplace_agent/config.py` | pydantic-settings `Settings` (env vars, see 2.3) |
| `src/workplace_agent/cli.py` | Typer app: `ingest`, `ask`, `eval`. Wires the real clients, prints output, sets exit codes |
| `src/workplace_agent/errors.py` | `AppError`; `ParseError(reason)` with StrEnum `FailureReason` {PASSWORD_PROTECTED, NOT_READABLE_PDF, TEMPORARY} |
| `src/workplace_agent/ports.py` | Protocols: `BlobSource`, `DocumentParser`, `Embedder`, `ChunkStore`, `ChatModel` |
| `src/workplace_agent/azure_clients.py` | The only module that constructs SDK clients: credential, Blob, Document Intelligence, Search, Azure OpenAI. Also handles the Search key fallback |
| `src/workplace_agent/ingestion/models.py` | `ParsedDocument`, `Chunk`, `IngestSummary` (dataclasses) |
| `src/workplace_agent/ingestion/parser.py` | Document Intelligence adapter; maps SDK errors to `FailureReason` |
| `src/workplace_agent/ingestion/chunker.py` | Pure heading-aware chunker with offset-to-page mapping |
| `src/workplace_agent/ingestion/embedder.py` | Batched embeddings |
| `src/workplace_agent/ingestion/index.py` | Index schema definition (create or update) and the `ChunkStore` adapter |
| `src/workplace_agent/ingestion/pipeline.py` | `run_ingest()`: diff, parse, chunk, embed, upsert, prune, summary |
| `src/workplace_agent/retrieval/search.py` | Hybrid retrieve (top 5); library-empty check |
| `src/workplace_agent/retrieval/prompt.py` | System prompt and the JSON schema of the structured answer |
| `src/workplace_agent/retrieval/answer.py` | `ask()`: validation and rendering of the final text, as pure logic |
| `src/workplace_agent/retrieval/evaluation.py` | Eval loader, runner, metrics, report |
| `eval/questions.jsonl` | 20 test questions (17 answerable, 3 with `expected_title: "none"`) |
| `samples/` | 10–20 sample policy PDFs written for the demo, plus test fixtures (a 12-page doc, a table, a screenshot, a password-protected PDF, a corrupt "PDF", a .docx) |
| `infra/main.bicep`, `infra/main.bicepparam`, `infra/modules/{monitoring,storage,ai,search,keyvault,rbac}.bicep` | Infrastructure as code (see 2.7) |
| `scripts/{deploy,env,upload-samples,teardown}.sh` | Developer workflow scripts (see 2.7) |
| `.github/workflows/ci.yml`, `azure-pipelines.yml` | CI: ruff, unit tests, `az bicep build` |
| `tests/unit/*`, `tests/fakes.py`, `tests/integration/*`, `tests/conftest.py` | See section 4 |
| `README.md` | Setup, architecture diagram, eval results, roadmap |

### 2.2 CLI contracts

| Command | Output | Exit code |
|---|---|---|
| `ingest` | Summary: new / updated / unchanged / removed / failed counts, a `name: reason` line per failure, a "skipped (not a PDF)" list, and the total passages. The final line is "Ingest finished successfully." or "Ingest finished with N failed document(s)." If the folder is empty, it also prints "No documents found in the document folder." | 0 success (including empty folder and skipped files); 1 if any document failed; 3 on a fatal config or auth error |
| `ask "<q>"` | The answer, then `Sources:` lines `[n] Title, p. N` or `[n] Title, pp. N–M`. Other outputs: the not-found sentence, "Please type a question.", or "The library has no documents yet. Run ingest first." | 0 for any answer (including not-found); 2 for an empty question; 1 for an empty library |
| `eval` | One line per question (question, found, cited, time), then four totals | 0 if all three targets are met; 1 if a target is missed, there are no questions, or the library is empty |

### 2.3 Configuration (env vars, written to `.env` by `scripts/env.sh`)

| Variable | Purpose |
|---|---|
| `STORAGE_ACCOUNT_URL`, `BLOB_CONTAINER` (default `documents`) | Document folder |
| `DOCINTEL_ENDPOINT` | Document Intelligence S0 endpoint |
| `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_VERSION` | Foundry (AIServices) endpoint; an API version that supports structured outputs |
| `AZURE_OPENAI_EMBEDDING_DEPLOYMENT`, `AZURE_OPENAI_CHAT_DEPLOYMENT` | Model deployment names |
| `SEARCH_ENDPOINT`, `SEARCH_INDEX_NAME` (default `workplace-docs`) | AI Search |
| `KEY_VAULT_URI`, `SEARCH_KEY_SECRET_NAME` (optional) | Fallback only: the Search admin key is read from Key Vault if Entra data-plane access to the Free tier is refused |
| `EVAL_PATH` (default `eval/questions.jsonl`) | Evaluation set |
| `CHUNK_MAX_TOKENS` (512), `CHUNK_OVERLAP_TOKENS` (64), `TOP_K` (5) | Tuning |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` (optional) | Turns on OpenTelemetry tracing when set |

`.env` is git-ignored and written with `chmod 600`. It holds no keys.

### 2.4 Search index `workplace-docs`

| Field | Type | Attributes | Purpose |
|---|---|---|---|
| `id` | String | key | `{doc_id}-{chunk_index}` |
| `doc_id` | String | filterable | First 16 hex characters of sha1(blob name) |
| `title` | String | searchable, filterable | Blob name without `.pdf` (the functional spec's "document title") |
| `source_path` | String | filterable | Blob name |
| `page_start`, `page_end` | Int32 | filterable | Physical page range. **Changes the architecture's single `page_number` to a range** |
| `section` | String | searchable | Heading path |
| `chunk_index` | Int32 | filterable, sortable | Order. Chunk 0 is the document's **commit marker** |
| `content` | String | searchable | Chunk text |
| `content_vector` | Collection(Single) | searchable | 1536 dimensions, HNSW, cosine |
| `content_hash` | String | filterable | sha256(PDF bytes plus pipeline version: chunk params and embedding model) |
| `ingested_at` | DateTimeOffset | retrievable | Audit |

**State and change detection** (no separate state store):
- Ingest reads the current state from the index with a filter `chunk_index eq 0`, selecting `doc_id, source_path, content_hash`.
- It then diffs that against the blob listing:
  - **new:** the blob isn't in the index
  - **updated:** the hash differs
  - **unchanged:** the hash is equal
  - **removed:** the doc_id is in the index but the blob is gone. A rename counts as one removed plus one new, and an emptied folder removes everything.
- The hash comes from the downloaded bytes, which is cheap for about 20 PDFs. This is more reliable than ETag or Content-MD5 for portal uploads.

**Write protocol** for an updated or shortened document. It's crash-safe because the old content stays searchable until the new content is complete:
1. `merge_or_upload` chunks 1…n-1.
2. Delete that document's chunk ids that aren't in the new id set.
3. `merge_or_upload` chunk 0, which carries the new hash.

A crash before step 3 leaves the old hash in place, so the next run redoes the document. Removed documents are cleaned up by filtering on `doc_id`, selecting ids, then calling `delete_documents` in pages. Batches stay within 1,000 documents and 16 MB.

### 2.5 Parsing and chunking

- **Parsing:** `begin_analyze_document("prebuilt-layout", …, output_content_format=markdown)`, using:
  - `content` (the Markdown)
  - `pages[].page_number` and `pages[].spans`, to build an offset-to-page interval map
  - paragraph spans and bounding regions
  - `tables[]` spans and bounding regions (one region per page for a spanning table)

  `<!-- PageBreak -->` markers are used to cross-check the page map, and are stripped before embedding.
- **Chunking:**
  1. Split the Markdown into blocks (heading, paragraph, table, figure), keeping character offsets.
  2. Group blocks into sections by heading path.
  3. Pack sections into windows of at most 512 tokens with 64 overlap (tiktoken `cl100k_base`).
  4. Never split a table mid-row; an oversized table is split by rows with the header repeated.
  5. Set `page_start` and `page_end` from the chunk's first and last characters.
  6. The embedded text is `"{title} > {section}\n{content}"`.
- **Text inside images:** scanned pages are OCR'd as normal text. Whether text inside embedded figures lands in the Markdown isn't verified. As a safeguard, any `pages[].lines` not covered by a Markdown block is appended as an extra chunk on its page. The screenshot fixture checks this in an integration test.

### 2.6 Ingest, ask and eval logic

**Ingest error handling:**
- Non-`.pdf` names (case-insensitive) are listed as skipped and never downloaded.
- Documents are processed one at a time inside a try block.
- SDK retry policy: 3 attempts in total, with exponential backoff.
- Failure reasons:

  | Error | Reason |
  |---|---|
  | 400 or 415, or `InvalidContent` / `InvalidRequest` / `UnsupportedMediaType`, with a message mentioning password or encryption | `PASSWORD_PROTECTED` |
  | The same errors without that message | `NOT_READABLE_PDF` |
  | 408, 429, 5xx, connection or timeout errors (including embedding and search 5xx) | `TEMPORARY` |
  | Any unknown exception (logged with a stack trace) | `NOT_READABLE_PDF` |

- A failed document writes nothing, so once fixed it counts as new.
- One structured JSON log line is written per document.

**Ask:**
1. `strip()` the question. If it's empty, print "Please type a question." and exit 2.
2. If the index document count is 0, print the library-empty message and exit 1.
3. Embed the query.
4. Run hybrid search: `search_text` plus a `VectorizedQuery` (k=50) with `top=5` (RRF fusion).
5. Make one chat call to `gpt-5-mini` (a reasoning model: no `temperature`; `reasoning_effort` "minimal"; `max_completion_tokens` about 800) with the numbered passages [1]–[5], using `response_format` json_schema:
   `{found: bool, sentences: [{text: str, cites: [int]}], missing_part: str | null}`.
6. Render deterministically:
   1. Drop cites outside 1–5, and drop any sentence left with no valid cite. This guards against made-up citations.
   2. If `found` is false or no sentences remain, output exactly the not-found sentence.
   3. Apply the 150-word cap to the sentence text only, dropping trailing sentences that overflow.
   4. Deduplicate sources by (title, page_start, page_end) and renumber [1..k] by first use.
   5. Print Sources lines with "p." or "pp." and an en dash.
   6. If `missing_part` is set and at least one sentence remains, append "I couldn't find information about {missing_part} in the company documents."

**Eval:**
- `questions.jsonl` lines look like `{"question": str, "expected_title": str}`. A missing file or no valid lines prints "No evaluation questions found." and exits 1. A count other than 20 is a warning.
- Each question times the whole `ask()` with `perf_counter`.
- Metrics:
  - **found:** for answerable questions, `expected_title` is among the top-5 retrieved titles (the functional spec's "documents the answer was built from"); for unanswerable questions, the output equals the not-found sentence.
  - **cited:** at least one validated marker, or "n/a" for unanswerable questions.
  - **Targets:** hit rate ≥ 0.90 and citation presence ≥ 0.90 (both over answerable questions), and nearest-rank p95 ≤ 8.0 s over all questions. p50 is for information only.
- The empty-library check runs first.

### 2.7 Infrastructure (Bicep, resource group `rg-workplace-agent-dev`, Sweden Central)

| Module | Resource | SKU / key settings | Est. cost |
|---|---|---|---|
| `storage` | StorageV2 + container `documents` | Standard_LRS, Hot, no public blob access, TLS 1.2 | < $0.10 |
| `ai` | Document Intelligence (kind FormRecognizer) | **S0** (F0 parses only 2 pages), custom subdomain | ≈ $0.50 for the sample set |
| `ai` | Foundry resource (kind AIServices) | S0, custom subdomain | per token |
| `ai` | Deployment `text-embedding-3-small` | GlobalStandard, capacity 50 | cents |
| `ai` | Chat deployment: `gpt-5-mini` (2025-08-07) by default, set by the `chatModelName`/`chatModelVersion` parameters | GlobalStandard, capacity 30; deployed after the embedding deployment (one at a time); `deployChatModel` flag as an escape hatch | cents to ~$1 |
| `search` | AI Search | **Free**, `authOptions: aadOrApiKey` so Entra and keys both work | $0 |
| `keyvault` | Key Vault | Standard, RBAC mode; optional secret `search-admin-key` (only when `searchUseKeyFallback=true`) | ≈ $0 |
| `monitoring` | Log Analytics + workspace-based App Insights | PerGB2018, 30-day retention, 0.1 GB daily cap | ≈ $0–1 |
| `rbac` | Role assignments for the parameter `principalId` (the developer) | Storage Blob Data Contributor; Cognitive Services OpenAI User (Foundry); Cognitive Services User (Document Intelligence); Search Index Data Contributor + Search Service Contributor (the CLI creates the index); Key Vault Secrets User | — |

- **Parameters:** `location`, `namePrefix`, `uniqueSuffix`, `principalId`, `principalType`, embedding and chat model name, version, capacity and SKU, `deployChatModel`, `searchUseKeyFallback`, `tags`.
- **Outputs:** the env var names in 2.3, plus `RESOURCE_GROUP` and `SUBSCRIPTION_ID`.

**Scripts:**

| Script | What it does |
|---|---|
| `deploy.sh` | Checks `az account show`, creates the resource group if missing, runs `what-if`, asks for an interactive "yes", runs `create`, then `env.sh` |
| `env.sh` | Writes deployment outputs to `.env`; refuses to run if `.env` isn't git-ignored |
| `upload-samples.sh` | `az storage blob upload-batch --auth-mode login` |
| `teardown.sh` | Lists the resources, asks for the resource group name to be typed, deletes the group, then purges soft-deleted Cognitive Services and Key Vault |

**First-time setup:**
1. `brew install azure-cli`
2. `az login --tenant <tenant>`
3. `az account set -s <subscription>`
4. Register the providers: CognitiveServices, Search, Storage, KeyVault, OperationalInsights and Insights.

**Read-only pre-checks before the first deploy:**
- Model availability and quota: `az cognitiveservices model list` and `usage list -l swedencentral`
- Region and SKU policies: `az policy assignment list`
- That no other Free search service exists: `az search service list`
- That the developer can create role assignments

**CI** (`ci.yml` and the equivalent `azure-pipelines.yml`), with no Azure login and no deployment:
1. Check out the repo.
2. Set up Python 3.12 and uv.
3. `ruff check` and `ruff format --check`.
4. `pytest -m "not integration"`.
5. `az bicep build --file infra/main.bicep`.

### 2.8 Observability

- `azure-monitor-opentelemetry` is configured only when `APPLICATIONINSIGHTS_CONNECTION_STRING` is set.
- Spans cover `ingest.document` (parse, chunk, embed, index), `ask` (embed, search, chat, render) and token counts.
- Diagnostic settings on the AI resources are left off in Spec 1, to avoid ingestion cost.

---

## 3. Impact and Risk Analysis

**System dependencies:**
- **Builds on:** Azure subscription access, the developer's Entra identity and the role assignments.
- **Used later:** the index and the `retrieval` package are the base for the later API, agent and Graph specs. The index schema and `ask()` contract should stay stable.
- **Architecture change:** `page_number` becomes `page_start`/`page_end`. The architecture doc should be updated when the spec is verified.

**Potential risks and mitigations:**

| Risk | Mitigation |
|---|---|
| Credit expires 2026-11-27 | Finish integration runs, eval and screenshots before then. `teardown.sh` afterwards; Bicep makes rebuilding a single command |
| Chat model retired or without quota (happened on 2026-11-16: `gpt-4o-mini` 2024-07-18 was rejected as `ServiceModelDeprecated`, and its GlobalStandard quota was 0) | Switched to `gpt-5-mini` GlobalStandard (quota 500). The model is still a parameter. East US 2 as fallback region |
| Tenant or policy blocks role assignments or the region | `what-if` and the role-assignment check before deploying. Fallback: a personal subscription |
| Free Search rejects Entra tokens | `searchUseKeyFallback`: the admin key goes to Key Vault and the app reads it with the developer's identity |
| Free Search deleted after inactivity | Ingest is idempotent; re-run `ingest` to rebuild |
| Offset-to-page mapping doesn't match the Markdown | PageBreak cross-check, plus an integration test on the 12-page fixture |
| Figure text missing from the Markdown | Append uncovered `lines` as an extra chunk; integration test on the screenshot fixture |
| No distinct error code for password-protected PDFs | Message match, with a default of "not a readable PDF"; fixture test |
| Model cites wrongly or ignores the word cap | Structured output plus code-side validation and rendering |
| p95 over 8 s (higher risk with a reasoning model) | One chat call, small prompt, `reasoning_effort` "minimal", `max_completion_tokens` cap; measured by eval |
| Any change to the chunk parameters re-ingests everything (the hash includes the pipeline version) | Intended; documented in the README |
| SDK details not verified (`begin_analyze_document` body parameter name, structured-output `api_version`, Entra data-plane auth on Search Free) | The specialists check these with context7 or the docs at implementation time, and the integration tests confirm them |

---

## 4. Testing Strategy

**Unit tests:** pytest with pytest-mock, never calling Azure. Fakes in `tests/fakes.py` implement the Protocols: `FakeBlobSource`, `FakeParser`, `FakeEmbedder`, `InMemoryChunkStore`, `FakeChatModel`.

| Test file | Covers | Functional spec |
|---|---|---|
| `test_chunker.py` | page ranges for text and spanning tables, table header repeat, token caps, last-page content | 2.1 |
| `test_parser_errors.py` | SDK error → `FailureReason` mapping | 2.3 |
| `test_pipeline.py` | new / unchanged / updated / shortened / renamed / removed / emptied folder; non-PDF skipped; failed then fixed → new; crash between write steps is redone; summary counts and exit codes | 2.1–2.3 |
| `test_answer.py` | marker validation, dropping sentences with no cite, dedupe of the same page, renumbering, 150-word cap, exact not-found and partial sentences | 2.4 |
| `test_search_query.py` | the hybrid query is built with top=5 and the vector field | 2.4 |
| `test_eval.py` | found/cited rules, nearest-rank p95, thresholds, "n/a", missing or empty file, exit codes | 2.5 |
| `test_cli.py` | Typer `CliRunner`: empty or whitespace question, empty library, exit codes per command | 2.4, 2.5 |
| `test_config.py` | env parsing and defaults | — |

**Integration tests:** `tests/integration/`, marked `@pytest.mark.integration` and skipped unless the env vars are set. They cover:
- real Document Intelligence on the fixtures: 12-page, table, screenshot, password-protected, corrupt
- a live ingest → ask round trip
- Entra access to Search Free

**Acceptance:**
- `testing-expert` maps every functional-spec criterion to a test after implementation.
- `eval` on the deployed environment is the end-to-end quality check. Its report is saved to the README.
- **Quality gates:** the `checks-before-stop` hook runs ruff and pytest locally, and CI runs ruff, unit tests and `bicep build`.

---

## Change Log

- 2026-11-16: The chat model changed from `gpt-4o-mini` to `gpt-5-mini` (2025-08-07, GlobalStandard, capacity 30). Azure rejected `gpt-4o-mini` 2024-07-18 at preflight as `ServiceModelDeprecated`, and the student subscription had no GlobalStandard quota for it. As a result, the chat call uses `reasoning_effort` "minimal" and `max_completion_tokens`, with no `temperature`. Approved by the user.
