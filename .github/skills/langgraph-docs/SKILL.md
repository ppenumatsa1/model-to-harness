---
name: langgraph-docs
description: Fetch and reference LangGraph Python documentation to build stateful agents, multi-agent workflows, checkpointers, streaming, and human-in-the-loop patterns. Use when the user asks about LangGraph, graph agents, agent orchestration, interrupts, or LangGraph implementation guidance.
license: MIT
metadata:
  author: LangChain
  package: langgraph
---

# langgraph-docs

## Workflow

### 1. Fetch the documentation index

Use `web_fetch` or `curl` to read: https://docs.langchain.com/llms.txt

This returns a structured list of available documentation pages and descriptions.

### 2. Select relevant documentation

Identify 2-4 relevant URLs from the index. Prioritize:

- **Implementation questions** — concrete how-to guides
- **Conceptual questions** — core concept pages
- **End-to-end examples** — tutorials and walkthroughs
- **API details** — reference material

### 3. Fetch and apply

Fetch the selected pages, then answer using the documentation content.

If the initial fetch fails or returns empty content, retry once. If it fails again, direct the reader to https://docs.langchain.com/oss/python/langgraph/.
