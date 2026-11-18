---
title: DBS Recording Inventory and Derivatives
description: A staging toolchain for a multi-case intraoperative deep brain stimulation dataset, designed by Garrett W. Thrash and built by AI coding agents.
nav: research
---

::: entry
Status

In use
:::

::: entry
Role

Designed and directed by me; code written by AI agents
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

[Research](/research/#tools)
