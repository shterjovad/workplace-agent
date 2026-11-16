# Functional Specification: Document ingestion pipeline and grounded Q&A CLI

- **Topic:** Making a set of company policy PDFs searchable, and answering questions about them from the command line with answers that cite the document and page.
- **Status:** Draft
- **Author:** Dona Shterjova

---

## 1. Overview and Rationale (The "Why")

People in operations, HR and office roles spend too long hunting through scattered policy documents for the one paragraph that answers a colleague's question. AI assistants could answer instantly, but an answer is only useful if the person can trust it, meaning they can see exactly where each fact came from. Both problems matter equally here: getting to the answer fast, and being able to check it.

This is the first feature of the Workplace Agent. It is used from a terminal by one developer, over a set of sample company policy PDFs written in English for the demo (HR leave, travel and expenses, IT security, onboarding).

**Terms used in this spec:**

- **Document folder:** one folder in the project's online cloud storage. The developer adds, replaces, renames or deletes PDF files there using the cloud provider's web portal. All three commands always work with this single folder.
- **Document title:** the PDF's file name without ".pdf". For example, "HR Leave Policy.pdf" has the title "HR Leave Policy".
- **Page:** the page's position in the file, counted from 1 for the first page. This is not the page number printed on the page.
- **Passage:** a short piece of a document, a few paragraphs long. Answers are built from passages.
- **Searchable library:** everything the assistant can answer from, made up of passages from the documents in the folder.
- **Changed document:** a file whose contents differ from the last time it was read. A renamed file counts as the old name removed and the new name added.
- **Success or failure result:** every command finishes either successfully or with a failure. An automated check that runs the command, such as a script or a test pipeline, marks the run as passed or failed accordingly. In the terminal, the developer also sees the final message described for each command.

**What the developer can do:**

1. Place the PDFs in the document folder.
2. Run **`ingest`** to bring the searchable library up to date with the folder.
3. Run **`ask "<question>"`** to get a short answer built only from the documents, with numbered citations to the document title and page. When the documents don't contain the answer, the reply says so instead of guessing.
4. Run **`eval`** to check answer quality against a stored set of 20 test questions.

Later features (sign-in, mail and calendar, a chat interface) will answer questions from this same library.

**Success is measured by `eval`:**

- for at least 90% of answerable test questions, the expected document is among the documents the answer was built from
- at least 90% of answers to answerable test questions carry a citation
- 95% of answers arrive within 8 seconds

These match the product's success metrics.

---

## 2. Functional Requirements (The "What")

### 2.1 Make the documents searchable (`ingest`)

- **As a** developer, **I want to** run one command that reads every PDF in the document folder and adds it to the searchable library, **so that** questions can be answered from any page of any document.
  - Every page of every PDF is read, including the text of tables and text that appears inside images.
  - Files in the folder that are not PDFs (for example Word documents or spreadsheets) are not read. They are listed in the summary as "skipped (not a PDF)" and do not make the run fail.
  - When the run finishes, the summary shows:
    - how many documents were **new**, **updated**, **unchanged**, **removed** and **failed**
    - the list of skipped non-PDF files
    - the total number of passages now in the library
   
  - **Acceptance Criteria:**
    - [ ] Given the document folder contains 15 readable PDFs and the library is empty, when the developer runs `ingest`, then the summary shows 15 new, 0 updated, 0 unchanged, 0 removed and 0 failed documents, and a passage total greater than 0.
    - [ ] Given a 12-page document whose 12th page contains a sentence found nowhere else, when the developer runs `ingest` and then asks a question that only that sentence answers, then the answer cites that document at "p. 12".
    - [ ] Given a document has a table that is the only place a specific figure appears (for example a daily meal allowance amount), when the developer runs `ingest` and then asks for that figure, then the answer contains the figure and cites the page the table is on.
    - [ ] Given a document has a figure from an image, such as a screenshot or a scanned notice, whose text appears nowhere else, when the developer runs `ingest` and then asks about that text, then the answer contains it and cites the page the image is on.
    - [ ] Given the folder contains 15 PDFs and one Word document, when the developer runs `ingest`, then the summary lists the Word document as "skipped (not a PDF)" and the run finishes with "Ingest finished successfully."
    - [ ] Given both the document folder and the library are empty, when the developer runs `ingest`, then they see "No documents found in the document folder." and the run finishes successfully.

### 2.2 Keep the library in step with the folder on every run

- **As a** developer, **I want** re-running `ingest` to process only what changed in the folder, **so that** runs are quick and the library never answers from outdated or deleted documents.
  - A document whose contents haven't changed since the last run is not read again and is counted as unchanged.
  - A document replaced with new contents is read again. Information that existed only in the old version can no longer appear in answers.
  - A document that became shorter keeps nothing from the pages that no longer exist.
  - A document removed from the folder is removed from the library completely on the next run. If the folder is emptied, every document is removed.
  - **Acceptance Criteria:**
    - [ ] Given `ingest` has already completed for 15 documents and nothing in the folder has changed, when the developer runs `ingest` again, then the summary shows 15 unchanged and 0 new, updated, removed and failed.
    - [ ] Given the HR leave policy is replaced with a version that changes the carry-over limit from 5 days to 10 days, when the developer runs `ingest` and asks "How many vacation days can I carry over?", then the summary shows 1 updated document and the answer gives 10 days as the limit, without giving 5 days as the current limit.
    - [ ] Given a document is deleted from the folder, when the developer runs `ingest` and then asks a question that only that document could answer, then the summary shows 1 removed document and the reply is the not-found answer.
    - [ ] Given a 12-page document is replaced with a version that keeps only pages 1–8, when the developer runs `ingest` and asks a question only the old 12th page answered, then the summary shows 1 updated document and the reply is the not-found answer.
    - [ ] Given a document is renamed in the folder without changing its contents, when the developer runs `ingest`, then the summary shows 1 removed and 1 new document, and answers cite the new title.
    - [ ] Given the library holds 15 documents and the folder is then emptied, when the developer runs `ingest`, then the summary shows 15 removed and the message "No documents found in the document folder."

### 2.3 Handle unreadable documents without stopping

- **As a** developer, **I want** one bad file to be reported and skipped, **so that** a single problem doesn't block the rest of the collection, and I can still tell that the run was not fully successful.
  - Every other document is still processed.
  - Each failed PDF is listed in the summary by name, with one of these plain reasons:
    - "password-protected"
    - "not a readable PDF", when the file is damaged or isn't really a PDF despite its name
    - "temporary problem — try again later", when reading still fails after 3 attempts because of a temporary connection or service problem
  - A run with any failed document ends with the message "Ingest finished with N failed document(s)." and finishes with a failure result.
  - A run with no failed documents ends with the message "Ingest finished successfully." and finishes successfully.
  - **Acceptance Criteria:**
    - [ ] Given the folder holds 14 readable PDFs and 1 password-protected PDF, and the library is empty, when the developer runs `ingest`, then the summary shows 14 new and 1 failed, lists the protected file with the reason "password-protected", ends with "Ingest finished with 1 failed document(s).", and the run finishes with a failure result.
    - [ ] Given the folder holds a damaged file named like a PDF (for example a text file renamed to "Policy.pdf"), when the developer runs `ingest`, then that file is listed as failed with the reason "not a readable PDF" and all other documents are still processed.
    - [ ] Given the developer's internet connection is switched off part-way through a run, when the run ends, then each document that could not be read is listed with the reason "temporary problem — try again later".
    - [ ] Given every PDF is readable, when the developer runs `ingest`, then the run ends with "Ingest finished successfully." and finishes successfully.
    - [ ] Given a PDF failed in an earlier run and the developer then replaces it with a readable version, when the developer runs `ingest` again, then that document is counted as new and no longer appears in the failed list.

### 2.4 Ask a question and get a cited answer (`ask`)

- **As a** developer, **I want to** ask a question in plain language and get a short answer with citations, **so that** I get the answer quickly and can check every fact at its source.
  - Each answer is built from up to 5 passages, the ones most relevant to the question.
  - The answer text is no longer than 150 words. The count excludes the citation markers and the Sources list. The answer uses only information found in those passages.
  - Citations:
    - Every sentence that states a fact from the documents carries at least one numbered marker, such as [1].
    - Below the answer, a "Sources" list shows one line per number, in the form "[1] Document title, p. N", or "[1] Document title, pp. N–M" when the information spans consecutive pages.
    - The same document and page (or page range) never appear twice in the list.
    - Every number used in the answer appears in the list, and every line in the list is used in the answer.
  - When the documents don't contain the answer, the reply is exactly "I couldn't find this in the company documents.", with no Sources list and no guessed answer.
  - When the documents answer only part of the question, the reply answers that part with citations, then names the part it couldn't find in one final sentence: "I couldn't find information about <the missing part> in the company documents."
  - The 8-second response-time target is measured by `eval` across all test questions, not judged on individual `ask` runs.
  - **Acceptance Criteria:**
    - [ ] Given the HR leave policy has been ingested, when the developer runs `ask "How many vacation days can I carry over?"`, then they see an answer of 150 words or fewer (excluding markers and Sources), in which every sentence carries at least one marker like [1], followed by a Sources list whose lines read "[n] Document title, p. N" or "[n] Document title, pp. N–M".
    - [ ] Given the developer has run `ask "How many vacation days can I carry over?"`, when they open each cited document at each cited page, then every fact the answer attributes to that citation is on that page.
    - [ ] Given the travel policy states two different facts on the same page, when the developer asks a question whose answer uses both facts, then the Sources list shows that document and page only once.
    - [ ] When the developer asks a question that none of the documents answer (for example "What is the CEO's favourite food?"), then they see exactly "I couldn't find this in the company documents." with no Sources list.
    - [ ] Given the documents state the meal allowance but say nothing about a parking allowance, when the developer asks "What are the meal and parking allowances?", then the answer gives the meal allowance with a citation and ends with "I couldn't find information about the parking allowance in the company documents."
    - [ ] When the developer runs `ask` with no question, with `ask ""`, or with a question made only of spaces, then they see "Please type a question." and no answer is attempted.
    - [ ] Given the library holds no documents (because `ingest` was never run, the folder was emptied, or every document failed), when the developer runs `ask` with any question, then they see "The library has no documents yet. Run ingest first."

### 2.5 Measure answer quality (`eval`)

- **As a** developer, **I want to** run a stored set of test questions and see clear quality scores, **so that** I can show the assistant is reliable and notice when a change makes it worse.
  - The evaluation set is a list of exactly 20 test questions, kept in a plain-text file in the project that the developer edits in any text editor. Each entry has a question and the expected document title. For the 3 deliberately unanswerable questions, the expected title is "none".
  - The report shows one line per question with:
    - the question
    - **found:** for answerable questions, whether the expected document was among the documents the answer was built from; for unanswerable questions, whether the not-found reply was given
    - **cited:** whether the answer carried at least one citation, shown as "n/a" for unanswerable questions
    - **time:** how long the answer took, from when `ask` starts until the full answer is shown, in seconds with one decimal place
  - The report ends with four totals. Every question's time counts toward both time totals.
    - **hit rate:** the share of answerable questions marked found (target: 90% or more)
    - **citation presence:** the share of answerable questions marked cited (target: 90% or more)
    - **slow-end response time (p95):** 95% of answers were this fast or faster (target: 8.0 seconds or less)
    - **typical response time (p50):** half of the answers were this fast or faster (shown "for information", with no target)
    
    The first three totals are labelled "meets target" or "below target".
  - If any target is missed, the evaluation run finishes with a failure result. Otherwise it finishes successfully.
  - **Acceptance Criteria:**
    - [ ] Given the documents are ingested and the evaluation set has 20 questions, when the developer runs `eval`, then they see 20 result lines and four totals: hit rate, citation presence and p95 each labelled "meets target" or "below target", and p50 labelled "for information".
    - [ ] Given an unanswerable test question gets the not-found reply, when the developer runs `eval`, then that question's line shows found as yes and cited as "n/a".
    - [ ] Given a score falls below its target, when `eval` finishes, then that score is labelled "below target" and the run finishes with a failure result.
    - [ ] Given all three targeted scores meet their targets, when `eval` finishes, then the run finishes successfully.
    - [ ] Given the evaluation file is missing or contains no questions, when the developer runs `eval`, then they see "No evaluation questions found.", no scores are shown, and the run finishes with a failure result.
    - [ ] Given the library holds no documents, when the developer runs `eval`, then they see "The library has no documents yet. Run ingest first." and the run finishes with a failure result.

---

## 3. Scope and Boundaries

### In-Scope

- Reading the sample company policy PDFs in the document folder, including tables and text inside images.
- The `ingest`, `ask` and `eval` commands, used from a terminal by one developer.
- Keeping the library in step with the folder: new, updated, shortened, renamed and deleted documents.
- Clear reporting of unreadable documents and skipped non-PDF files.
- Cited answers, partial answers, and the not-found reply.
- The 20-question evaluation set and its quality report.

### Out-of-Scope

- A web page or chat interface for asking questions (a later feature).
- Signing in, and any per-person access to documents (a later feature).
- Reading the user's email or calendar, drafting replies or proposing meetings (a later feature).
- An assistant that takes multi-step actions or chooses between tools (a later feature).
- Automatic publishing of the system from the code repository; setup is done by hand from the developer's machine.
- Pulling documents from company file-sharing sites, and showing different documents to different people.
- Reading file types other than PDF (they are skipped, see 2.1).
- Documents and questions in languages other than English.
- Several users working at the same time.
- Response-time guarantees for an individual question; the 8-second target applies to the evaluation set as a whole.

---

## Change Log

_Dated amendments made after the spec was first written, typically by `/awos:spec` in Update Mode when a bug fix changed documented behavior. Each entry records the date, the source reference (bug id or fix description), and what behavior changed and why. Leave empty until the first amendment._
