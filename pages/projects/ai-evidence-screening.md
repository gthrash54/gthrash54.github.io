---
title: AI-Assisted Evidence Screening
description: A hybrid human and AI title-and-abstract screening pipeline for large systematic and scoping reviews, agentically engineered by Garrett W. Thrash.
nav: research
---

::: entry
Status

In use
:::

::: entry
Role

Agentically engineered by me
:::

::: entry
Stack

Python, Claude Code agents, Covidence
:::

Hybrid human–AI screening for a scoping review of roughly 10,000 records.

- A language model votes on every record with a confidence and an exclusion code.
- High-confidence exclusions are removed only after both human reviewers validate a blinded random sample against a pre-declared error threshold.
- The model then serves as second reviewer on the retained set, with human adjudication of every disagreement.
- Designed to meet the 2025 Cochrane/Campbell/JBI/CEE position statement and the RAISE recommendations on AI in evidence synthesis.

[Agentic engineering](/research/#agentic)
