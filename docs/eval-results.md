# Evaluation results

- Date: 2026-11-16
- Environment: Azure for Students, Sweden Central; gpt-5-mini 2025-08-07 (GlobalStandard); text-embedding-3-small; Azure AI Search free tier
- Corpus: 12 sample PDFs, 40 passages
- Command: `uv run workplace-agent eval` (exit code 0, all targets met)

```
[ 1] found=yes cited=yes  4.9s  How many unused vacation days can I roll over into next year?
[ 2] found=yes cited=yes  2.7s  How many paid vacation days do full-time staff get each year?
[ 3] found=yes cited=yes  2.2s  When do I need to bring a doctor's note if I'm off sick?
[ 4] found=yes cited=yes  3.5s  What is the daily food allowance for a domestic business trip?
[ 5] found=yes cited=yes  2.7s  What is the maximum hotel rate per night when travelling to Germany?
[ 6] found=yes cited=yes  2.2s  How long after a trip do I have to submit my expense claim?
[ 7] found=yes cited=yes  3.2s  Where and when is the yearly company retreat?
[ 8] found=yes cited=yes  2.7s  What is the helpdesk PIN reset code?
[ 9] found=no cited=no   3.1s  What is the minimum length for a password?
[10] found=yes cited=yes  3.5s  What is the process for requesting a remote or hybrid work arrangement?
[11] found=yes cited=yes  2.7s  How do I submit a request relating to personal data handling?
[12] found=yes cited=yes  2.3s  Who approves requests about professional behaviour, and how fast must they be logged?
[13] found=yes cited=yes  2.8s  What do I have to do to get a request about company equipment approved?
[14] found=yes cited=yes  3.3s  How should I raise a health and safety request with my manager?
[15] found=yes cited=yes  2.8s  What is the procedure for requests during the onboarding of new employees?
[16] found=yes cited=yes  2.6s  How do I make a request about parental leave?
[17] found=yes cited=yes  3.4s  What are the steps for a request relating to performance reviews?
[18] found=yes cited=n/a  1.8s  How much is the monthly parking allowance for the office car park?
[19] found=yes cited=n/a  2.4s  What is the CEO's favourite food?
[20] found=yes cited=n/a  2.6s  What is the current company stock price?
hit rate: 94.1% (meets target, target ≥ 90%)
citation presence: 94.1% (meets target, target ≥ 90%)
p95 response time: 3.5s (meets target, target ≤ 8.0s)
p50 response time: 2.7s (for information)
Evaluation passed.
```

## Analysis

All targets were met, so the run passed. One answerable question missed, which accounts for the 94.1% (16/17) hit rate and citation presence:

- Q9, "What is the minimum length for a password?" (expected source: IT Security Policy). The CLI answered "I couldn't find this in the company documents." Retrieval is the cause: the top-5 hybrid results were Equipment and Laptop Policy (3. Loss or damage), Data Protection Policy (3. Data subject requests), and three Employee Handbook chapters (11, 3, 6), with scores 0.029 to 0.032. The IT Security Policy was not among them. The sample passages share near-identical boilerplate text, so the keyword and vector signals are weak and the correct passage was outranked. The model correctly refused rather than guess from unrelated passages. No change was made to pass this.
