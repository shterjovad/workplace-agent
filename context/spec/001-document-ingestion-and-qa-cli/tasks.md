# Tasks: Document ingestion pipeline and grounded Q&A CLI

Source: `functional-spec.md` and `technical-considerations.md` in this directory.

**Ground rules for every slice:**
- Any command that creates, changes or deletes billable Azure resources (`az deployment group create`, `scripts/deploy.sh`, `scripts/teardown.sh`, `az group delete`) runs **only after the user explicitly approves it in that task**.
- Read-only commands (`az bicep build`, `what-if`, `list`/`show`) need no approval.
- Live checks need `az login` and a populated `.env`.

---

- [x] **Slice 1: A runnable CLI skeleton with input validation and CI**

  > After this slice, `uv run workplace-agent --help` lists `ingest`, `ask` and `eval`, and the input-only behaviors already work without Azure.
  - [x] Create the uv project:
    - `pyproject.toml`: Python 3.12; console script `workplace-agent`; runtime deps (typer, pydantic-settings, azure-identity, azure-storage-blob, azure-ai-documentintelligence, azure-search-documents, azure-keyvault-secrets, openai, tiktoken, azure-monitor-opentelemetry); dev deps (pytest, pytest-mock, ruff, mypy, reportlab, pypdf); ruff/pytest/mypy config with an `integration` marker.
    - A `.venv` via `uv sync`.
    - `.gitignore` covering `.env`, `.venv` and caches.
    
    **[Agent: python-backend]**
  - [x] Implement `config.py` (`Settings` with the env vars from tech spec 2.3), `errors.py` (`FailureReason`, `ParseError`, `AppError`), `ports.py` (the five Protocols), and the `ingestion/models.py` dataclasses. Add `tests/fakes.py` with in-memory fakes for every Protocol, and `test_config.py`. **[Agent: python-backend]**
  - [x] Implement `cli.py` with the Typer commands `ingest`, `ask` and `eval`:
    - `ask` with an empty, missing or whitespace-only question prints "Please type a question." and exits 2.
    - `eval` with a missing or empty `eval/questions.jsonl` prints "No evaluation questions found." and exits 1.
    - Missing required settings give a clear message and exit 3.
    - The live paths are stubbed behind the ports.
    
    Add `test_cli.py` for these cases, proven with RED validation. **[Agent: python-backend]**
  - [x] Add `.github/workflows/ci.yml` and `azure-pipelines.yml`: Python 3.12 + uv, `ruff check`, `ruff format --check`, `pytest -m "not integration"`, and an `az bicep build --file infra/main.bicep` step that is skipped while `infra/` doesn't exist yet. No Azure login, no deployment. **[Agent: azure-infra]**
  - [x] Verify:
    1. Run `uv run workplace-agent --help`, `uv run workplace-agent ask ""`, `uv run workplace-agent ask "   "` and `uv run workplace-agent eval` (with no eval file), and confirm the exact messages and exit codes (`echo $?`).
    2. Run `uv run ruff check .` and `uv run pytest -m "not integration"` and confirm both pass.
    3. Delete any temporary files created during the check.
    
    **[Agent: python-backend]**

- [x] **Slice 2: Azure environment and a document folder holding the sample PDFs**

  > After this slice, the resource group exists in Sweden Central, `.env` is populated, and the developer can see the sample PDFs in the `documents` container.
  - [x] Write `infra/main.bicep`, `infra/main.bicepparam` and the modules (`monitoring`, `storage`, `ai`, `search`, `keyvault`, `rbac`) exactly as in tech spec 2.7:
    - Document Intelligence S0.
    - AIServices with the two deployments: serial, with chat model name, version and capacity as parameters and a `deployChatModel` flag.
    - AI Search Free with `aadOrApiKey`.
    - Role assignments for `principalId`.
    - The optional `searchUseKeyFallback` secret.
    - Outputs named as the env vars.
    
    Confirm current API versions, SKUs and model availability with context7 or the official docs. Validate with `az bicep build`. **[Agent: azure-infra]**
  - [x] Write `scripts/deploy.sh` (what-if, then an interactive "yes", then create, then `env.sh`), `scripts/env.sh` (outputs to `.env`, `chmod 600`, refuses if `.env` isn't git-ignored), `scripts/upload-samples.sh` (`upload-batch --auth-mode login`) and `scripts/teardown.sh` (typed resource group name confirmation, delete, purge soft-deleted Cognitive Services and Key Vault). Add a `docs/setup.md` with `brew install azure-cli`, `az login --tenant`, provider registration and the read-only pre-checks. **[Agent: azure-infra]**
  - [x] Write `scripts/make_samples.py`, which generates the sample set and fixtures with reportlab and pypdf. It writes to `samples/documents/` (12 policy PDFs) and `samples/fixtures/`, as described below. Commit the generated PDFs. **[Agent: python-backend]**
    - The 12 policy PDFs are HR Leave Policy, Travel and Expenses Policy, IT Security Policy, Onboarding Guide and so on. They include:
      - a 12-page document with a unique sentence on page 12
      - a meal-allowance table, with no parking allowance mentioned anywhere
      - a table that spans two pages
      - a page with a screenshot image containing text found nowhere else
      - a carry-over limit of 5 days in the HR Leave Policy
    - The fixtures are:
      - an HR Leave Policy variant with a 10-day limit
      - a version of the 12-page document cut to 8 pages
      - a password-protected PDF
      - a text file renamed to `Policy.pdf`
      - a small `.docx`
  - [x] Run the read-only pre-checks (model list and quota in swedencentral, policy assignments, existing Free search services, role-assignment permission) and report the results. **Then ask the user for approval** before running `scripts/deploy.sh`. After approval, deploy, run `env.sh`, and run `upload-samples.sh` for `samples/documents/`. **[Agent: azure-infra]**
  - [x] Verify:
    1. Run `az bicep build --file infra/main.bicep` (passes).
    2. Run `az resource list -g rg-workplace-agent-dev -o table` and confirm Storage, Document Intelligence, AIServices with both deployments, Search (free), Key Vault, Log Analytics and App Insights.
    3. Run `az storage blob list --auth-mode login` on `documents` and confirm the 12 PDFs.
    4. Confirm `.env` has every variable from tech spec 2.3 and no keys.
    5. Delete any temporary output files.
    
    **[Agent: azure-infra]**

- [x] **Slice 3: `ingest` makes the documents searchable on a first run**

  > After this slice, running `ingest` on the uploaded folder prints a summary (12 new, 0 failed, passage total > 0) and the passages are in the search index with page ranges.
  - [x] Implement `ingestion/parser.py`: a Document Intelligence `prebuilt-layout` adapter with Markdown output, returning a `ParsedDocument` with the Markdown, the offset-to-page interval map, table regions, and the uncovered-`lines` fallback for figure text. Check the current SDK signature with context7. **[Agent: python-backend]**
  - [x] Implement `ingestion/chunker.py`: heading-aware blocks, heading-path `section`, 512/64-token windows (cl100k_base), tables never split mid-row (header repeated), `page_start`/`page_end` from offsets, PageBreak markers stripped. Add `test_chunker.py` covering multi-page text, a two-page table, the token cap and last-page content. **[Agent: python-backend]**
  - [x] Implement `ingestion/embedder.py` (batched embeddings with an Entra token provider) and `ingestion/index.py` (create or update the `workplace-docs` schema from tech spec 2.4; the `ChunkStore` adapter with `merge_or_upload`, delete-by-ids, state query on `chunk_index eq 0`, and document count). In `azure_clients.py`, build every client with `DefaultAzureCredential`, plus the Key Vault key fallback for Search. **[Agent: python-backend]**
  - [x] Implement `ingestion/pipeline.py` `run_ingest()` for **new documents and the empty folder**:
    - list blobs and skip non-PDFs
    - hash, parse, chunk, embed
    - write with the chunk-0-last protocol
    - build the summary
    
    Wire it into `ingest` in `cli.py` with the final messages and exit codes. Add `test_pipeline.py` cases for first-run counts, skipped non-PDFs and the empty folder. **[Agent: python-backend]**
  - [x] Verify:
    1. Run `uv run pytest -m "not integration"` (passes).
    2. Run `uv run workplace-agent ingest` against the deployed environment and confirm the summary shows 12 new, 0 updated, 0 unchanged, 0 removed and 0 failed, a passage total above 0, and "Ingest finished successfully." with exit 0.
    3. Query the index with a small script and confirm that chunks from the 12-page document include `page_start = 12`, and that the Travel and Expenses Policy has chunks on pages 1, 2 and 3. (Changed 2026-11-16: Document Intelligence returns cross-page tables as separate per-page tables, and in the sample the continuation doesn't fit in the same 512-token chunk. Page ranges such as "pp. 2–3" are covered by unit tests.)
    4. Delete the query script and any output files.
    
    **[Agent: python-backend]**

- [x] **Slice 4: `ask` returns cited answers, the not-found reply and partial answers**

  > After this slice, `ask` answers policy questions with page-level citations, and says so when the documents don't contain the answer.
  - [x] Implement `retrieval/search.py` (library-empty check via the document count; hybrid query with `search_text` plus `VectorizedQuery` k=50 and top=5) and `retrieval/prompt.py` (system rules and the JSON schema `{found, sentences[{text, cites}], missing_part}`). Add `test_search_query.py`. **[Agent: python-backend]**
  - [x] Implement `retrieval/answer.py` `ask()`:
    - one structured-output chat call (temperature 0, max_tokens ≈ 400)
    - validation: drop invalid cites and sentences left with no cite
    - the 150-word cap
    - source deduplication by (title, page_start, page_end), renumbered by first use
    - `p.`/`pp.` rendering with an en dash
    - the exact not-found sentence, and the partial-answer sentence
    
    Wire it into `ask` in `cli.py` (empty library prints "The library has no documents yet. Run ingest first." and exits 1). Add `test_answer.py` covering every rendering rule, with RED validation. **[Agent: python-backend]**
  - [x] Verify against the deployed environment:
    1. `ask "How many vacation days can I carry over?"` gives at most 150 words, every sentence with a marker, and Sources lines in the `[n] Title, p. N` format, and the cited page in the PDF contains the fact.
    2. `ask "What is the daily meal allowance?"` cites the table page.
    3. Asking about the page-12 sentence cites p. 12.
    4. Asking about the screenshot text returns it and cites its page.
    5. `ask "What is the CEO's favourite food?"` prints exactly "I couldn't find this in the company documents." with no Sources.
    6. `ask "What are the meal and parking allowances?"` ends with "I couldn't find information about the parking allowance in the company documents."
    7. Two facts from the same page give a single Sources line.
    8. Run the unit tests (they pass).
    9. Delete any captured output files.
    
    **[Agent: python-backend]**

- [x] **Slice 5: Re-running `ingest` keeps the library in step with the folder**

  > After this slice, re-runs report unchanged, updated, removed and renamed documents correctly, and answers never use outdated or deleted content.
  - [x] Extend `run_ingest()`:
    - read the index state and diff it against the blobs (new / updated / unchanged / removed)
    - updated and shortened documents use upsert, then prune stale ids, then write chunk 0 last
    - removed and renamed documents are deleted by `doc_id`
    - an emptied folder removes everything
    - the hash includes the pipeline version
    
    Add `test_pipeline.py` cases for unchanged, updated, shortened, renamed, removed, emptied folder, and a crash between write steps that gets redone on the next run. **[Agent: python-backend]**
  - [x] Verify against the deployed environment, re-running `uv run workplace-agent ingest` after each change:
    1. With nothing changed, confirm 12 unchanged.
    2. Upload the 10-day HR Leave Policy over the original. Confirm 1 updated, and that `ask "How many vacation days can I carry over?"` gives 10 days and doesn't present 5 days as the current limit.
    3. Upload the 8-page cut over the 12-page document. Confirm 1 updated, and that the page-12 question returns the not-found reply.
    4. Rename a document in the container. Confirm 1 removed and 1 new, and that citations use the new title.
    5. Delete a document. Confirm 1 removed, and that a question only it answered returns not-found.
    6. Restore the original 12 documents with `upload-samples.sh` (plus blob deletes for any extras) and re-ingest.
    7. Delete any temporary files.
    
    **[Agent: python-backend]**

- [x] **Slice 6: Unreadable files are reported and skipped without stopping the run**

  > After this slice, password-protected, damaged and temporarily failing documents are listed with plain reasons, and the run ends with the failure message and exit 1.
  - [x] Implement the error classification in `ingestion/parser.py` and the pipeline:
    - 3 attempts in total with exponential backoff
    - the mapping from tech spec 2.6 to PASSWORD_PROTECTED / NOT_READABLE_PDF / TEMPORARY
    - unknown exceptions logged and mapped to NOT_READABLE_PDF
    - failed documents write nothing, so a fixed file later counts as new
    - "Ingest finished with N failed document(s)." with exit 1
    - one structured JSON log line per document
    
    Add `test_parser_errors.py`, plus `test_pipeline.py` cases for a mixed batch and for a failed file that's later fixed. **[Agent: python-backend]**
  - [x] Verify against the deployed environment:
    1. Upload the password-protected PDF, the renamed text file `Policy.pdf` and the `.docx`, then run `ingest`.
    2. Confirm 12 unchanged, 2 failed with reasons "password-protected" and "not a readable PDF" (if Document Intelligence gives no distinct password error, record the actual reason shown), the `.docx` listed as "skipped (not a PDF)", the final line "Ingest finished with 2 failed document(s).", and exit 1.
    3. Replace `Policy.pdf` with a readable PDF and re-run. Confirm it's counted as new.
    4. Delete the fixture blobs, re-run `ingest`, and confirm a clean run with exit 0.
    5. Run the unit tests (the TEMPORARY path is covered by unit tests with fakes).
    6. Delete temporary files.
    
    **[Agent: python-backend]**

- [x] **Slice 7: `eval` reports quality against the targets**

  > After this slice, `eval` runs the 20 stored questions and shows per-question results and the four totals, with pass or fail.
  - [x] Write `eval/questions.jsonl`: 20 entries `{"question", "expected_title"}` matching the sample documents, 17 answerable and 3 with `"none"`. **[Agent: python-backend]**
  - [x] Implement `retrieval/evaluation.py`:
    - loader, with "No evaluation questions found." and a warning when the count isn't 20
    - a runner timing the whole `ask()` with `perf_counter`
    - found and cited rules ("n/a" for unanswerable questions)
    - hit rate, citation presence, nearest-rank p95 ≤ 8.0 s, and p50 for information
    - labels "meets target", "below target" and "for information"
    - the empty-library check first
    - exit codes
    
    Wire it into `eval` in `cli.py`. Add `test_eval.py`. **[Agent: python-backend]**
  - [x] Verify:
    1. Run `uv run workplace-agent eval` against the deployed environment and confirm 20 result lines and four labelled totals, with exit 0 when all targets are met (if a target is missed, record which one and why).
    2. Temporarily point `EVAL_PATH` at an empty file and confirm "No evaluation questions found." with exit 1, then restore it.
    3. Save the real report to `docs/eval-results.md` for the README.
    4. Delete any other temporary files.
    
    **[Agent: python-backend]**

- [x] **Slice 8: Tracing in Application Insights and portfolio README**

  > After this slice, runs with `APPLICATIONINSIGHTS_CONNECTION_STRING` set appear as traces in Application Insights, and the README explains the project.
  - [x] Add opt-in OpenTelemetry tracing (`azure-monitor-opentelemetry`), active only when the connection string is set:
    - spans `ingest.document` (parse, chunk, embed, index) and `ask` (embed, search, chat, render)
    - attributes for latency and token counts
    - no document text in the traces
    
    Add a unit test that tracing stays off when the variable is unset. **[Agent: python-backend]**
  - [x] Write `README.md`:
    - what it is and why
    - an architecture diagram (Mermaid)
    - setup: link to `docs/setup.md`, deploy, upload, ingest, ask, eval
    - example `ask` output
    - the eval table from `docs/eval-results.md`
    - cost and teardown notes, including the credit expiring on 2026-11-27
    - design decisions (Entra auth, crash-safe re-ingest, citation validation, page ranges)
    - a roadmap: API on Container Apps, Foundry agent, Entra + Graph mail and calendar with approval, SharePoint with permission filtering, QLoRA intent router, Teams
    
    **[Agent: python-backend]**
  - [x] Verify:
    1. With the connection string set, run one `ingest` (all unchanged) and one `ask`.
    2. After about 2–3 minutes, run `az monitor app-insights query` for the last 15 minutes and confirm spans named `ingest.document` and `ask` exist.
    3. Confirm the README renders: run a Markdown lint, or check the Mermaid block syntax.
    4. Delete any query output files.
    
    **[Agent: azure-infra]**

- [x] **Slice 9: Feature Testing & Regression**

  > Verifies the whole feature end-to-end against functional-spec.md, run after all implementation slices are complete.
  - [x] Read functional-spec.md acceptance criteria in full. Generate acceptance-level tests that verify the entire feature as a whole — not individual slices. Cover applicable layers (unit for pure logic, integration for service interactions, e2e for user flows) based on the project's testing stack. Write tests with RED validation (must fail before implementation is confirmed done). Annotate each test with `@spec: 001-document-ingestion-and-qa-cli` and `@regression` if suitable for long-term regression. **[Agent: testing-expert]**
  - [x] Run all generated tests. All must pass. Fix any failures before proceeding. **[Agent: testing-expert]**
