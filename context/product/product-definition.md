# Product Definition: Workplace Agent

- **Version:** 1.0
- **Status:** Proposed

---

## 1. The Big Picture (The "Why")

### 1.1. Project Vision & Purpose

To give knowledge workers one trustworthy assistant that answers questions from company documents and takes routine email and calendar work off their plate — acting only on the user's own data, with their consent, and never taking an action without their explicit approval.

### 1.2. Target Audience

Employees at organisations that run on Microsoft 365 who lose time hunting through policies and internal documents and triaging a busy inbox and calendar. Typical roles: operations, HR, office management, project coordination.

### 1.3. User Personas

- **Persona 1: "Ana the Operations Coordinator"**
  - **Role:** Operations coordinator at a mid-sized company; receives ~80 emails a day and is the go-to person for policy questions.
  - **Goal:** Answer colleagues' policy questions quickly and accurately, and get through her inbox and scheduling without losing an hour every morning.
  - **Frustration:** Searching scattered documents for the right policy paragraph, re-reading long email threads, and the back-and-forth of finding a meeting slot.

- **Persona 2: "Marco the Hiring Reviewer"**
  - **Role:** Engineering lead evaluating the project as a demonstration of an enterprise-ready AI assistant.
  - **Goal:** See, in a few minutes, that the assistant is grounded, secure, measured, and cost-aware.
  - **Frustration:** Demos that are impressive but unverifiable — no citations, no evaluation numbers, no safeguards.

### 1.4. Success Metrics

- At least 90% of answers on the evaluation question set are grounded in company documents and include a source citation.
- Zero emails sent or meetings created without the user's explicit approval.
- 95% of responses arrive within 8 seconds.
- The small fine-tuned intent model classifies user requests more accurately (higher F1) than the same model before fine-tuning, and costs less per 1,000 requests than the commercial model it is compared with.
- A first-time user can sign in and get a useful answer within 2 minutes, without instructions.

---

## 2. The Product Experience (The "What")

### 2.1. Core Features

- **Grounded document Q&A:** Ask questions about company documents and get concise answers with citations to the source document.
- **Inbox & calendar briefing:** Summarise the user's unread mail and today's calendar on request.
- **Approve-before-act assistance:** Draft an email reply or propose a meeting slot; nothing is sent or booked until the user explicitly approves (and can edit or reject).
- **Secure personal sign-in:** Users sign in with their Microsoft account and grant consent; the assistant only sees the data that user is allowed to see.
- **Smart request routing (experiment):** A small, specially trained open-source model recognises what the user is asking for (document question, mail, reply, meeting, other), benchmarked against a commercial model on accuracy, speed, and cost.

### 2.2. User Journey

Ana opens the Workplace Agent and signs in with her Microsoft work account, approving the permissions it asks for. She asks, "What's our policy on carrying over unused vacation days?" and receives a short answer citing the HR policy document. Next she asks, "What did I miss in my inbox this morning?" and gets a summary of her unread emails and today's meetings. She says, "Reply to Marko that I can join Thursday's review, and find 30 minutes with him next week." The agent shows her a draft reply and a proposed meeting slot; Ana tweaks one sentence, approves both, and the email is sent and the invitation created. If she had rejected them, nothing would have happened.

---

## 3. Project Boundaries

### 3.1. What's In-Scope for this Version

- Sign-in with a Microsoft account and user consent to access their own mail and calendar.
- Question answering with citations over a fixed set of sample company documents.
- Summary of unread mail and today's calendar.
- Drafting an email reply and proposing a meeting slot, executed only after explicit approval.
- A simple chat-style web interface.
- An evaluation of answer quality and response time.
- A trained intent-classification model with a comparison report (accuracy, speed, cost) against a commercial model.
- A public write-up with a short demo video, architecture overview, and roadmap, since this is a portfolio project.

### 3.2. What's Out-of-Scope (Non-Goals)

- A Microsoft Teams app (roadmap).
- Pulling documents from SharePoint with per-user permission filtering (roadmap).
- Multiple cooperating agents (roadmap).
- Running the trained intent model in the live product (roadmap — benchmark only in this version).
- Acting on behalf of other users, shared mailboxes, or admin-level access.
- Fully automatic actions without approval.
- Mobile app, multi-language support, and long-term conversation memory.
- Delivery constraint: built in one day as a portfolio project, so the first version stays deliberately minimal.
