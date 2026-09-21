# Agent Harnesses: Giving Agents a Place to Work

_This is Part 3 of the model-to-harness series, continuing from
[Part 1: From Models to Harnesses](https://www.linkedin.com/pulse/from-models-harnesses-how-ai-agents-learn-finish-job-penumatsa-g2mjc)
and [Part 2: Agent Frameworks](https://www.linkedin.com/pulse/agent-frameworks-model-can-answer-workflow-finish-penumatsa-sdz6c).
We now turn to the harness: the controlled working environment that helps an
agent investigate, adapt, and finish the job safely._

## 1. When the goal is clearer than the path

> **Checkout failed for order 8472. Investigate the issue, safely resolve it,
> and show the evidence.**

The goal is clear, but the path is not.

In Part 1, we started with a **model** that could reason. Add an **agent loop**,
and it could call tools, observe results, and decide what to do next.

In Part 2, we added **frameworks** to coordinate workflows: steps, state
transitions, checkpoints, approvals, and multi-agent patterns.

So what are we still missing?

**A place for the agent to work.**

Somewhere it can keep findings, update a plan, inspect another clue, create
intermediate artifacts, and continue from what it has already learned.

That is where the harness becomes important. It surrounds the agent loop with
a controlled working environment: context, tools, workspace, permissions,
state, and verification.

The progression is:

**Model → reason**

**Agent loop → reason and act**

**Framework → coordinate workflows**

**Harness → give the agent an environment to keep working toward an outcome**

|                | Framework emphasis          | Harness emphasis                         |
| -------------- | --------------------------- | ---------------------------------------- |
| Starting point | Steps and state transitions | A goal and a working environment         |
| Main question  | What step comes next?       | What can the agent use to make progress? |
| Contribution   | Coordinates work            | Equips and controls the agent's work     |

These are complementary. A harness may use a framework, and a framework may
coordinate adaptive agents. The new capability here is the working environment
around the loop.

## 2. The working environment around the loop

Think of an investigator with a desk. The desk holds notes, evidence, a plan,
and unfinished work. The investigator can return to them without keeping
everything in mind at once.

An agent's environment plays that role. It may include a workspace, filesystem,
shell or REPL, and code execution. Tools let it inspect information and create
artifacts. Skills provide reusable instructions. Not every task needs every
capability.

The harness connects this environment to the model. It builds context, checks
permissions and limits, dispatches allowed actions, and captures what happened.
The model reasons over the selected context and proposes the next action.

**Figure 1. How a harness works**

![The harness builds context, calls the model for a proposed action, checks permissions, executes an authorized tool, captures the result and updates state, then continues or completes based on task-specific evidence. External systems are accessed through authorized tools.](assets/03-agent-harness-loop-screenshot.png)

The loop continues until the outcome is verified or the system stops safely.
Completion requires task-specific evidence, not just the model saying it is done.
**The agent loop controls the next model call; the environment retains the
work.** Retained working state helps the agent continue across more steps
without depending only on conversation history.

## 3. Checkout example: an agent at work

Suppose checkout fails. The agent does not yet know whether the problem is
payment, inventory, order creation, or something else.

It starts with a small set of diagnostic tools and investigates. It might
discover:

```text
Payment:   authorized
Inventory: reservation expired
Order:     not confirmed
```

That changes what it should inspect next. The agent records findings in its
workspace, updates `plan.md`, and checks the next useful source, perhaps more
detail in the order record or the checkout logs.

The cycle is simple:

**Inspect → record findings → update understanding → choose the next check**

Relevant observations go back to the model through the harness. The rest of the
working material stays in the environment. The investigation can build on
previous work instead of starting over on every model call.

Eventually, the evidence may point to a recovery path. **That is where the
agent's freedom stops.**

The application applies business rules, requests approval when required,
performs the authorized repair, and verifies the result against the
authoritative business records.

**Figure 2. Investigation is not authority to repair**

![Checkout recovery moves from adaptive investigation inside the harness—inspecting evidence, analyzing, recording findings, and updating understanding—to application-controlled business action: applying rules and approvals, executing repair, and verifying the outcome.](assets/03-checkout-recovery-flow-screenshot.png)

The agent has freedom to investigate, not freedom to bypass business authority.
If evidence is incomplete, approval is denied, or verification fails, the
application reports that outcome instead of declaring success.

Our independent [**MAF implementation**](https://github.com/ppenumatsa1/model-to-harness/tree/main/harness/checkout-recovery/maf)
and [**Copilot SDK implementation**](https://github.com/ppenumatsa1/model-to-harness/tree/main/harness/checkout-recovery/copilot-sdk)
follow this same boundary. MAF assembles framework primitives; Copilot SDK configures a supplied
agent runtime. Both use scoped diagnostic tools and a private plan, without
shell access or business-write tools.

These are simulated checkout systems, not live payment integrations. Required
approval is saved through an explicit command, followed by a separate Resume.
**`plan.md` helps the agent work. It does not authorize a refund.** Neither does
chat text.

## 4. What the agent's workspace might contain

A more general investigation workspace could look like this:

```text
workspace/
├── plan.md       # Current plan and next steps
├── findings/     # Notes, excerpts, and analysis
├── queries/      # Saved queries or scripts
├── evidence/     # Logs, responses, and outputs
└── summary.md    # Key findings for the next step
```

This is an illustration, not the directory layout of our checkout examples,
which deliberately use a smaller workspace centered on `plan.md`.

Working state helps the agent build on previous work. **It is a notebook, not
the business ledger.** Business systems remain the source of truth.
Workspace files are not automatically model context, and persistence alone does
not restore execution.

## 5. Harness types

Some SDKs help you assemble a harness; others embed a prebuilt harness.
Managed services additionally operate more of the environment around it.

### Harness SDKs and frameworks

**MAF primitives / Deep Agents** help you assemble or configure harness
capabilities; **MAF Harness / Copilot SDK** offer more preassembled or embedded
harness behavior.

They provide or expose capabilities such as agent loops, tools, skills,
workspaces, context management, and controls. Your application chooses how to
use them, integrates business systems, and arranges where the agent runs.
Using an SDK does not mean writing the model/tool loop yourself.

### Managed harnesses

A provider operates more of the harness and its execution environment.
Examples include **Claude Managed Agents**, **Managed Deep Agents**, and
**OpenAI Agents API**.

You provide task-specific tools, instructions, integrations, and policies.
The provider takes on more of the environment, persistence, and operations;
the exact division depends on the service.

### Ready-to-use harnesses

The harness is already assembled around a class of work. Examples include
**Claude Code**, **Codex**, **Copilot CLI/coding agent**, and **Goose**.

You mostly provide the task and context rather than assembling the harness
yourself, while configuring the access and controls the product supports.

A simple way to remember the distinction:

| Form                     | Main emphasis                        |
| ------------------------ | ------------------------------------ |
| **SDK / framework**      | You assemble or embed a harness.     |
| **Managed harness**      | You configure more than you operate. |
| **Ready-to-use harness** | You mostly provide the task.         |

The boundaries overlap. A packaged agent runtime is not automatically a hosted
service, and a ready-to-use product may also expose an SDK. The useful question is:

> **Who owns the loop, environment, controls, persistence, and operations?**

## 6. Cross-cutting concerns

These concerns apply throughout the work, not just at the end.

| Concern                                | Purpose                                                                                      |
| -------------------------------------- | -------------------------------------------------------------------------------------------- |
| **Identity, security, and governance** | Control who can access what. Harness permissions do not replace business-system permissions. |
| **Observability**                      | Explain what happened and where work failed.                                                 |
| **Evaluations**                        | Test behavior and outcomes across cases.                                                     |
| **Memory and knowledge**               | Inform the agent without replacing current business truth.                                   |
| **Business systems**                   | Enforce authority and provide the records used to verify outcomes.                           |

## 7. What keeps the work alive

Suppose the case pauses for approval and the reviewer returns tomorrow. The
agent's work may need to continue hours later, possibly on a different process
or machine.

The application still needs the case, pending request, recorded decision,
operation ID, and business evidence. If the agent resumes investigating, the
harness may also need its session, workspace, files, and enough working state
to continue from where it left off.

That raises the next question:

**What infrastructure keeps this environment running, isolated, and recoverable
over time?**

That is the role of **runtime infrastructure**.

> **The harness defines how the agent works.**  
> **The runtime determines where that work runs, what it can reach, how it is
> isolated, and how it continues after interruption.**

Next, we move underneath the harness: hosting, persistence, recovery, networking,
credentials, and where tools actually execute.

---

**Explore the code:**
[MAF checkout recovery](https://github.com/ppenumatsa1/model-to-harness/tree/main/harness/checkout-recovery/maf)
· [Copilot SDK checkout recovery](https://github.com/ppenumatsa1/model-to-harness/tree/main/harness/checkout-recovery/copilot-sdk)
· [Business rules](https://github.com/ppenumatsa1/model-to-harness/blob/main/harness/checkout-recovery/docs/business-rules.md)

**References by harness type:**

- **SDKs and frameworks:** [Microsoft Agent Framework](https://learn.microsoft.com/en-us/agent-framework/overview/) · [MAF Harness](https://learn.microsoft.com/en-us/agent-framework/concepts/harness) · [Deep Agents](https://docs.langchain.com/oss/python/deepagents/overview) · [GitHub Copilot SDK](https://docs.github.com/en/copilot/how-tos/copilot-sdk/features)
- **Managed harnesses:** [Claude Managed Agents](https://platform.claude.com/docs/en/managed-agents/overview) · [Managed Deep Agents](https://docs.langchain.com/langsmith/python/managed-deep-agents-overview) · [OpenAI Agents API](https://developers.openai.com/api/docs/guides/agents-api/quickstart)
- **Ready-to-use harnesses:** [Claude Code](https://code.claude.com/docs/en/overview) · [Codex](https://github.com/openai/codex) · [Copilot CLI](https://docs.github.com/en/copilot/concepts/agents/copilot-cli/about-copilot-cli) · [Goose](https://goose-docs.ai/)
