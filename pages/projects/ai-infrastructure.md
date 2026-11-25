---
title: Personal AI Infrastructure
description: Scheduled agents, review gates and verification tools for research, medical education and administration, agentically engineered by Garrett W. Thrash.
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

Python, SQLite, Git, systemd, Obsidian, Codex, Claude Code, MATLAB
:::

::: entry
Code

Private, because it runs on my own accounts
:::

Agent workflows in three tracks: neuroengineering research, medical education, and administration. One agent builds, a different agent reviews, and regression tests check the result. The production code for my PhD stays mine to write.

- **Scheduled agents.** Seven unattended Claude Code jobs on systemd timers: a daily neuroscience literature digest, mail alerts, deadline reminders, a morning agenda, and recurring CV and toolbox checks. A permission guard limits each agent to an allow-list of tools, with no shell access, and lets it send email only to me.
- **Literature and funding pipeline.** Retrieves and deduplicates public records from PubMed, bioRxiv, medRxiv, arXiv and Grants.gov, tracks incomplete searches, and turns the daily collection into a weekly Obsidian digest.
- **Medical-education grading pilot.** Checks AI scores against versioned rubrics and the quotations that support them. Blinded grading sessions matched both synthetic reference scores, and test controls caught both overcredit and missed credit.
- **MATLAB-to-Python verification harness.** Runs Python in isolation and compares its output with MATLAB on synthetic inputs. It reproduced all 21 reference values and caught a channel-axis error that kept the array shape intact.

The project has 91 passing tests.

[Agentic engineering](/research/#agentic)
