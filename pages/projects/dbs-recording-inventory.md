---
title: DBS Recording Inventory and Derivatives
description: A staging toolchain for a multi-case intraoperative deep brain stimulation dataset, agentically engineered by Garrett W. Thrash.
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

Python
:::

::: entry
Code

Private, because the data are patient recordings; available on request
:::

A staging toolchain for a multi-case intraoperative dataset: verifies every raw file is readable, builds an inventory of leads, contacts, and streams per case, derives condition labels and task states, computes audio coherence and video motion traces for behavioral alignment, and writes de-identified derivatives to a separate store. Raw data and the identity crosswalk never leave the acquisition machine.

[Agentic engineering](/research/#agentic)
