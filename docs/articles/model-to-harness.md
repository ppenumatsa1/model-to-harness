# From Models to Harnesses: How AI Agents Learn to Finish the Job

## The next breakthrough may not be a smarter model

We now call almost everything an *agent*: chatbots, copilots, coding assistants, research tools, workflows, and managed agent platforms. The word is useful, but it hides the more important change underneath.

AI is moving from **answering questions**, to **taking actions**, to **finishing real work**: carrying a task to a checked result that people can trust.

The problem is that a model alone is not a working system. It can reason and generate, but it cannot reliably gather current information, operate tools, preserve progress, wait for approval, recover from failure, or prove that the task was completed correctly.

Those missing capabilities accumulated around the model:

```text
Model
  ↓
Agent loop
  ↓
Agent SDKs / frameworks and workflow patterns
  ↓
Harness for completing real work
  ↓
Runtime / managed hosted agent
```

This is not a strict history or a rigid product taxonomy. The layers overlap, and many products span several of them. It is a **capability progression**: each layer addresses limits exposed by the layer before it.

The central idea is:

> **Models generate. Agents act. Frameworks organize. Harnesses finish the job. Runtimes sustain the work.**

> **A case to follow — the double charge.**  
> A customer says they were billed twice. Resolving the case means reading the complaint and account history, checking billing records, validating the refund policy, obtaining approval, issuing the refund exactly once, notifying the customer, and retaining evidence of what happened. We will follow this same case through every layer.

## The full map at a glance

| Layer | Core responsibility | Important primitives | Double-charge example | Remaining limitation |
|---|---|---|---|---|
| Model | Reason and generate | Prompt, context window, response | Reads the supplied complaint and drafts a helpful reply | Cannot retrieve billing records or issue a refund |
| Agent loop | Reason and act repeatedly | Observe, reason, act, reflect, continue or stop | Reads the account and investigates the charges | A custom loop becomes difficult to control and recover |
| Agent SDKs / frameworks | Package and organize agent behavior | Model adapters, messages, tools, nodes, edges, workflows, state transitions, subagents, retries, interrupts, checkpoints | Defines investigate → approve → refund → notify | The work still needs a useful task environment |
| Harness | Assemble a complete environment for finishing work | Context builder, skills, permissions, tool executor, workspace, filesystem, shell, code tools, verification | Carries the case to a verified refund and closed ticket | It must be run, persisted, isolated, and operated reliably |
| Runtime / managed hosted agent | Run, persist, isolate, scale, pause, and recover the harness | Sessions, workers, events, queues, sandboxes, checkpoints, scheduling, identity integration | Preserves the approval wait and resumes the case later | Must be governed, observed, and evaluated |

The boundaries are intentionally practical rather than absolute. An SDK may contain workflow features. A framework may ship with a runtime. A managed platform may host a simple agent, a framework workflow, or a complete harness. This sequence is a reader's story, not a claim that the runtime is technically added last: every framework and harness executes somewhere. The useful question is not “Which single box contains this product?” It is “Which capabilities does it provide, and which ones must we still design?”

## 1. Model: smart, but empty-handed

Foundation models made language and reasoning programmable. They can summarize, draft, classify, explain, plan, and generate code. That alone was a major leap.

But a model is stuck behind glass. It only sees the context supplied for the current request. It does not automatically know today’s account balance, open a billing system, run a validation, preserve meaningful progress, or act on a business system.

```text
Instructions + supplied context
             │
             ▼
           Model
             │
             ▼
       Generated response
```

> **Double charge at the model layer:** when the complaint is supplied in its context, the model can read it and draft a polite response saying that the company will investigate. It cannot retrieve billing records, confirm that two charges occurred, or return any money. It produces words, not outcomes.

Chat and copilot experiences made models easier to reach, but a chat window does not automatically create an agent. The next step is to connect the model to information and actions, then let it decide what to do next.

## 2. Agent: now it can act

An agent wraps a decision loop around a model:

```text
Observe → Reason → Act → Reflect → Continue or stop
```

The loop supplies the model with instructions and current context. The model may respond directly, select a tool, request clarification, delegate work, or stop. Tool results return to the loop and become input to the next decision. Here, **reflect** means assessing the result, verifying what changed, updating task state, and deciding whether to continue—it does not imply autonomous self-improvement.

A minimal agent can be custom-built:

```text
User request
     │
     ▼
Build model input
     │
     ▼
Model reasons: response or tool
     │
     ├── Response ──► Return to user
     │
     └── Tool call ─► Execute ─► Return result to loop
```

This is the first important transition: the model is no longer only generating an answer. It can inspect the world and attempt to change it.

### From custom loops to agent SDKs

A small custom loop is easy to understand. Production work quickly introduces repeated engineering needs: model adapters, typed messages, tool schemas, validation, handoffs, guardrails, streaming, tracing, and error handling.

Agent SDKs package these recurring parts. OpenAI Agents SDK, Claude Agent SDK, Microsoft Agent Framework, Google ADK, and similar libraries provide different combinations of these capabilities. In practical terms, **SDKs package reusable building blocks; frameworks add explicit control flow and stateful orchestration.** Product boundaries overlap, so these labels should be understood by the primitives being used rather than only by the product name.

> **Double charge at the agent layer:** the agent can retrieve the account, compare the transactions, and determine that the customer was charged twice. It can draft a refund request. But a simple loop still lacks a dependable structure for parallel checks, approval waits, safe recovery, and exactly-once business actions.

## 3. Agent SDKs and frameworks: organizing the work

An agent can decide its next action. A real business process also needs explicit control over how work moves, what state changes, when humans intervene, and how execution recovers.

### Agent frameworks organize work

Agent frameworks provide primitives for:

- **Nodes:** agents, tools, deterministic code, human steps, or sub-workflows that perform work.
- **Edges:** transitions that connect nodes based on results, conditions, events, or failures.
- **Graphs and workflows:** the overall control flow, including branches and loops.
- **State transitions:** explicit changes to the task’s execution truth.
- **Multi-agent orchestration:** delegation, handoffs, supervisors, subagents, and fan-out/fan-in.
- **Interrupts:** durable pauses for approval, clarification, external events, or unavailable dependencies.
- **Failure controls:** retries, timeouts, cancellation, fallback, and error routing.
- **Durability primitives:** checkpoints, resume, replay, and recovery from a known state.

The double-charge flow is a simple example:

```text
Investigate
  → duplicate confirmed?
  → parallel billing and policy checks
  → approval interrupt
  → retry-safe refund
  → verify and notify
```

The framework tracks shared workflow state: case data, plan, completed steps, results, errors, approval status, and final outcome. Checkpoints and event records make it possible to resume or reconstruct work after interruption; idempotency keys and business-system checks prevent a refund, payment, or message from being issued twice.

> **Double charge at the framework layer:** the framework glues the process together. It carries shared case state from investigation to the parallel billing and policy checks, pauses at the approval gate, routes a failure to a retry-safe refund step, and only then moves to verification and notification. It makes the order, branches, waits, and recovery behavior explicit rather than leaving them to an improvised agent loop.

Framework patterns such as sequential steps, parallel work, routing, handoffs, supervisors, and fan-out/fan-in are simply different arrangements of nodes, edges, and state. The detailed mechanics belong in the framework deep dive. For now, the key point is that dependable systems usually combine deterministic workflow boundaries with model-directed judgment inside selected steps.

## 4. Harness: the execution shell for finishing the job

A harness is the execution shell around a model that turns generation into repeated, stateful, tool-using work. It integrates the agent loop, framework and runtime capabilities with the context, skills, permissions, tools, workspace, environment, collaboration, and verification needed to complete a real task.

A harness uses framework and runtime capabilities. This article introduces the runtime afterward because it explains how the harness is sustained: where its work runs, how it is isolated, and how it survives interruption.

```text
Harness
  = agent loop and model adapter
  + context builder and context management
  + instructions, skills, planning, and memory access
  + tool registry, permissions, and tool executor
  + workspace, filesystem, shell, browser, and code tools
  + sandbox, container, microVM, or external systems
  + verification, human collaboration, and finished artifacts
```

### Context, state, and memory are different

The harness is where the information model becomes useful. Three concepts should stay separate:

- **State** is the current execution truth: the plan, completed steps, intermediate results, errors, and approval status. The framework defines its transitions; the runtime persists it.
- **Memory** is selected knowledge retained for later use: facts, preferences, prior outcomes, or reusable procedures.
- **Context** is the temporary projection shown to the model for one decision.

A context builder assembles that temporary view:

```text
Instructions + skills + recent history
State + memory + workspace + tool results
                     │
                     ▼
               Context builder
                     │
                     ▼
          Model context for this decision
```

Context is not the source of truth. It is a view assembled from state, memory, history, instructions, skills, workspace, and tool results.

The core harness loop looks like this:

```text
                         AGENT HARNESS

User / Event / Schedule
          │
          ▼
┌─────────────────────────┐
│ Session and task state  │
└────────────┬────────────┘
             ▼
┌─────────────────────────────────────┐
│ Context builder                     │
│                                     │
│ Instructions + recent history       │
│ task state + memory + workspace     │
│ relevant skills + tool results      │
└──────────────────┬──────────────────┘
                   ▼
┌─────────────────────────┐
│ Model decision          │
│ Plan / answer / tool    │
│ selection / delegation  │
└────────────┬────────────┘
             ▼
┌─────────────────────────┐
│ Permission and policy   │
│ Identity │ authorization│
│ approval │ budget       │
└────────────┬────────────┘
             ▼
┌─────────────────────────┐
│ Tool executor / worker  │
│ Validate │ retry        │
│ timeout │ idempotency   │
└────────────┬────────────┘
             ▼
┌─────────────────────────────────────┐
│ Execution environment               │
│                                     │
│ Workspace │ filesystem │ shell      │
│ code interpreter │ browser │ search │
│ sandbox │ container │ microVM       │
│ APIs and business systems           │
└──────────────────┬──────────────────┘
                   ▼
┌─────────────────────────────────────┐
│ Capture result                      │
│                                     │
│ Tool output │ files │ errors        │
│ events │ traces │ audit records     │
└──────────────────┬──────────────────┘
                   ▼
┌─────────────────────────────────────┐
│ Update durable sources              │
│                                     │
│ State │ transcript │ checkpoint     │
│ workspace │ selected memory         │
└──────────────────┬──────────────────┘
                   ▼
             ┌───────────────┐
             │ Goal verified?│
             └──────┬───┬────┘
                    │   │
                  No│   │Yes
                    │   ▼
                    │ Finished, checked
                    │ artifact or outcome
                    │
                    └────► Build next context


CONTROLS FOR DURABLE, LONG-RUNNING HARNESS TASKS:

Pause / resume │ recovery │ replay │ cancellation
human approval │ subagents │ compaction │ verification
observability │ evaluations │ security │ governance
```

### Skills, tools, workspace, and environment

**Skills** are reusable procedures: how to perform a recurring task well. They supply instructions and supporting resources but do not execute actions themselves.

**Tools** are the capabilities that act: APIs, search, browser automation, code execution, business systems, and agent-to-agent communication. MCP and other connectors can standardize how tools and resources are exposed.

The **workspace** is what the agent works on: a repository, task folder, documents, case files, or generated artifacts. The **environment** is where and under what controls the work runs: a local machine, browser session, sandbox, container, VM, or microVM. It determines filesystem access, network reachability, available packages, secrets, and isolation.

The model does not directly edit a file or issue a refund. It proposes an action. The harness checks the schema, identity, policy, permission, approval requirements, and execution boundary before a worker performs it. Put simply:

> **Models propose; harnesses authorize, execute, record, and verify.**

Coding harnesses such as Claude Code, GitHub Copilot, Codex, and Cursor make this visible through repositories, terminals, files, tests, diffs, and review. General-purpose harnesses such as Claude Cowork, Microsoft 365 Copilot Cowork, and GPT work experiences apply the same ideas to research, documents, browser tasks, communication, and business workflows.

> **Double charge at the harness layer:** the context builder assembles the complaint, account data, case state, refund policy, and relevant skill. The model decides what to inspect. The permission layer protects sensitive actions. The tool executor runs billing operations in a controlled environment. The harness records events and checkpoints, updates selected memory, waits for approval, verifies that exactly one refund occurred, notifies the customer, and produces a reviewable closed case.

A harness becomes **long-horizon** when it can preserve progress, recover from interruption, coordinate multiple steps or agents, work with people, manage context over time, and verify a task that cannot be completed in one model turn.

## 5. Runtimes and hosted agents: sustaining the harness

The harness is the useful work environment. A runtime is the execution substrate beneath it. The runtime runs the framework and harness locally or remotely, and makes their durable behavior real.

- Sessions and threads identify continuing work.
- Workers and queues schedule execution.
- Sandboxes, containers, or microVMs isolate code and tools.
- Persistent stores retain state, events, and checkpoints.
- Schedulers and event handlers start or resume work later.
- Identity and network controls determine what execution can reach.
- Scaling and recovery keep execution available.

The distinction is simple:

```text
Framework defines: node, edge, transition, interrupt, retry, checkpoint
Harness assembles: context, skills, tools, workspace, environment, verification
Runtime provides:  worker, session, persistence, queue, isolation,
                   scheduling, restoration, scaling, recovery
```

Managed hosted-agent platforms operate some or all of this runtime for the developer. Examples include Azure AI Foundry Hosted Agents, Claude Managed Agents, and LangChain managed agent offerings. A managed platform may run a simple agent, a framework workflow, or a complete harness.

> **Double charge at the runtime layer:** the harness reaches the approval step and the hosted runtime saves the paused session. When approval arrives two hours later, it restores the work from its checkpoint. If the billing API fails, the refund step retries with an idempotency key so the customer is refunded once.

## 6. Cross-cutting concerns: what makes agency trustworthy

The capability progression explains how increasingly complete work becomes possible. Cross-cutting concerns apply across agents, frameworks, hosted runtimes, and harnesses rather than appearing only at the end.

| Plane | Questions it must answer |
|---|---|
| Experience and collaboration | Where do people meet the agent? How do they review, approve, correct, or receive its work? |
| Interoperability standards | How do agents, tools, data sources, and user interfaces exchange capabilities and events without one-off integration? |
| Identity, security, and governance | Who or what is acting, what can it access, which policies apply, and can its work be reconstructed and controlled? |
| Memory and knowledge | What should persist, for how long, under what scope, and with what provenance? |
| Observability and evaluation | What happened, did it reach the right outcome safely, and how reliably and efficiently did it do so? |

### Experience and collaboration

People and systems may meet an agent through chat, Teams, Slack, email, an IDE, a browser, a custom UI, or an API. ChatGPT, Microsoft 365 Copilot, Teams, Slack, Outlook, and IDE-based experiences are examples of these channels. These are not merely skins. The experience determines how the agent is discovered, supervised, corrected, and asked to deliver work.

The desired output is usually a real artifact or changed business state: a resolved ticket, code change, document, dashboard, message, or updated record. In the double-charge case, the outcome is a verified refund and closed case, not a long transcript.

### Interoperability standards

Interoperability is not another step in the maturity story. It is a set of common contracts that can apply across frameworks, harnesses, runtimes, and user experiences.

| Standard | Boundary it addresses | Role |
|---|---|---|
| MCP | Agent or harness ↔ tools and context | Standardizes how tools, resources, and related capabilities are exposed. It does not execute the tool itself. |
| A2A | Agent ↔ agent | Supports discovery, delegation, and communication between agents. It does not replace workflow orchestration. |
| AG-UI | Agent ↔ user interface | Connects agent activity and events to a user interface. It does not replace Teams, Slack, or a custom application. |

The practical point is simple: MCP reduces one-off tool and context integrations; A2A reduces one-off agent-to-agent integrations; AG-UI reduces one-off agent-to-UI integrations. Teams, Slack, email, browser applications, and IDEs remain the channels through which people use the resulting experience.

### Identity, security, and governance

The moment an agent can see sensitive data or take real action, identity, security, and governance become one architectural concern. Teams need to know who acted, on whose behalf, with which permissions, against which systems, and whether a human approved a consequential step.

Controls include authentication, scoped authorization, secret handling, tool permissions, sandbox and network restrictions, data protection, audit trails, ownership, approval boundaries, and cancellation. In a Microsoft environment, Agent 365, Microsoft Entra, Microsoft Purview, and Microsoft Defender illustrate complementary parts of this control plane: agent identity and lifecycle, access control, data governance, and security monitoring and response. Governance is not the last box in the design. It surrounds every consequential decision and action.

### Memory and knowledge

Memory spans several layers but serves different purposes. A framework may carry thread state. A runtime may persist it. A memory system may retain selected facts, experiences, or procedures across sessions. A harness context builder retrieves only the information needed for the current model decision. Common building blocks include enterprise search and retrieval systems such as Azure AI Search, Microsoft Graph data, vector stores such as pgvector, Pinecone, or Weaviate, and knowledge graphs or application databases.

Memory should therefore have scope, provenance, retention, access control, and update rules. Not every transcript or tool result should become long-term memory.

### Observability and evaluation

Agents leave a trail, not just an answer. Traces, events, logs, tool calls, state transitions, retries, approvals, cost, latency, and produced artifacts reveal what happened. Examples of the operating tools include OpenAI tracing, LangSmith, Langfuse, Arize Phoenix, Azure Monitor, and Application Insights; evaluation suites may be built into those platforms or run alongside them.

Evaluation asks more than whether the final text looks plausible:

- Did the system reach the correct business outcome?
- Did it use authoritative sources and the correct tools?
- Did it follow the expected workflow and approval policy?
- Did retries remain safe and side effects happen once?
- Is the final artifact complete and reviewable?

Improvement should be evidence-driven:

```text
Observe → Evaluate → Diagnose → Improve prompt, skill, tool, or workflow
   ▲                                                   │
   └──────────── Test → controlled rollout ────────────┘
```

This does not require an agent that freely rewrites itself. It requires measurable changes, evaluation before release, monitoring afterward, and a safe rollback path.

## The real contest

The industry often compares models head-to-head, as though the best model automatically creates the best agentic system. Model quality matters enormously, but it is only one part of dependable work.

```text
Model intelligence
  + agent loop and framework control
  + harness context, tools, environment, and verification
  + runtime durability
  + interoperability standards
  + identity, security, governance, observability, and evaluation
  = finished, trustworthy work
```

The real prize is not merely cleverness. It is consistency: carrying work to a verified outcome across tool calls, state transitions, failures, approvals, and time.

That is why harnesses matter. They are the execution shell that brings the model, agent behavior, workflow control, runtime, context, tools, environment, state, and human collaboration together until the job is finished.

## Where this series goes next

This article establishes the shared mental model. The next two pieces will dive into the framework and harness layers with focused examples and implementation projects:

1. **Agent frameworks and managed hosting, with code**  
   I will create equivalent workflows in Microsoft Agent Framework (MAF) and LangGraph. We will first explain each primitive—nodes, edges, state transitions, retries, checkpoints, pause/resume, replay, idempotency, memory, and multi-agent patterns—then build projects that show how those primitives run on a managed hosted-agent platform.

2. **Inside the harness**  
   I will build harness projects, then explain the context builder, skills, planning, tool permissions, tool execution, filesystem and shell, controlled environments, workspace artifacts, helper agents, memory updates, and verification loop.

The question for any new “agent” is therefore not only “Which model does it use?” It is:

> **What work can it carry to a finished, trustworthy result; over what time horizon; with whose authority; and with what evidence that it was done correctly?**

## Sources and verification

The diagrams and category map in this article are original conceptual models. Product behavior changes quickly, so validate vendor-specific statements, preview status, and limits immediately before publication.

- [Microsoft Agent Framework documentation](https://learn.microsoft.com/en-ca/agent-framework/?view=agent-framework-python-latest)
- [Microsoft Foundry Hosted Agents](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/hosted-agents)
- [Claude Managed Agents overview](https://platform.claude.com/docs/en/managed-agents/overview)
- [Microsoft Agent 365 identity](https://learn.microsoft.com/en-us/microsoft-agent-365/developer/identity)
- [Model Context Protocol specification](https://modelcontextprotocol.io/specification/2024-11-05/index)
- [A2A Protocol documentation](https://a2a-protocol.org/latest/)
- [AG-UI documentation](https://docs.ag-ui.com/)
