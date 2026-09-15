# Agent Frameworks: The Model Can Answer. Can the Workflow Finish?

*Part 2 of From Models to Harnesses. LinkedIn draft, adapted from the repository's
technical chapter.*

## Beyond smarter models: systems that finish the job

"I was charged twice."

A language model can apologize, explain possible causes, and draft a reassuring
reply. But the customer is not asking for better wording. They want the charges
investigated and, if a refund is justified, their money returned. Once.

Between the complaint and that outcome sit billing records, policy, human
approval, a payment operation that might time out, and evidence that the refund
actually happened.

**A smarter answer does not settle an unfinished case.**

In [Part 1](https://www.linkedin.com/pulse/from-models-harnesses-how-ai-agents-learn-finish-job-penumatsa-g2mjc),
we separated three responsibilities:

> Framework = how work is coordinated. Harness = what surrounds the agent so it
> can finish and verify the work. Runtime = where that work executes and survives.

Let's follow one case through two independent implementations, with real code.

## Why the loop needs a structure

An agent can inspect its context, choose a tool, read the result, and decide what
to do next. For a small task, that loop may be enough.

Our case introduces harder questions. Which checks can run together? What happens
if only one passes? Where does the system stop for approval? What survives a
process restart? Is retrying a timed-out refund safe?

A framework gives the application structures for expressing those answers:
steps, routes, state, joins, pauses, and recovery boundaries. It coordinates code,
tools, and model calls rather than leaving every transition implicit.

**Predictable orchestration does not make a model deterministic. It makes the
permitted actions and transitions explicit.**

Not every automation needs an agent framework. A conventional service or workflow
engine may already fit. The value appears when model calls, tool execution,
stateful coordination, and human input would otherwise require substantial
custom plumbing.

## Before we continue: the building blocks of this case

Our investigation needs a small vocabulary. Each **primitive** solves a practical
coordination problem:

| Primitive | Its job in our case |
|---|---|
| **Workflow / graph** | Describe the allowed journey from complaint to outcome. |
| **Node / executor** | Perform one task: interpret, check, submit, or verify. |
| **Edge / route** | Choose the next permitted step from the evidence. |
| **State** | Carry the case's evidence, status, and decisions. |
| **Fan-out / fan-in** | Run independent checks together, then join their results. |
| **Checkpoint** | Save the execution state needed for continuation. |
| **Pause / resume** | Stop for external input and continue later. |
| **Failure handling** | Bound attempts and define failure or review routes. |

State carries the case's progress and evidence. **Context** is the selected
information the model sees for a particular call—for example, complaint text or
verified refund facts. **Memory** is knowledge retained for later use; it does
not automatically become model context.

A node need not be an agent: ordinary code, a tool call, or a model-backed
operation can fill that role. The framework coordinates them; business rules
decide what is allowed.

## Give the case a route, not just a prompt

Here is the business flow implemented independently with Microsoft Agent
Framework (MAF) and LangGraph:

![Double-charge workflow: model interpretation, deterministic duplicate detection, parallel billing and policy checks, then an approval pause. This application records the decision and resumes through separate commands. An approved refund uses a stable idempotency identity and is verified before notification. Policy ineligibility closes without a refund; unresolved payment outcomes require manual review rather than a failed-payment assumption.](assets/02-agent-frameworks-flow.png)

*One case, several possible outcomes. Payments and notifications are simulated in
this teaching repository; the authority and verification boundaries are deliberate.*

## Follow the case: from complaint to verified outcome

### 1. Investigate and bring the evidence together

An explicit start command opens the case. A model interprets the complaint;
code investigates the billing records.

Deterministic code checks for two distinct captured charges matching the account,
purchase reference, amount, and currency. If no qualifying duplicate exists,
the case closes without a refund.

If a duplicate appears, two questions can be answered independently:

- Is the billing evidence valid?
- Does the policy permit a refund?

The checks run in parallel, then join before the workflow decides whether to
continue. This is **fan-out and fan-in**.

The [MAF workflow](https://github.com/ppenumatsa1/model-to-harness/blob/8a2ac71dc8afb4b82e2e49bd37d35cf9d3647225/agent-framework/double-charge/maf/backend/src/maf_double_charge/maf/workflows/double_charge.py)
connects typed executors:

    .add_fan_out_edges(prepare_validation, [billing_validation, policy_validation])
    .add_fan_in_edges([billing_validation, policy_validation], join_validations)

The [LangGraph workflow](https://github.com/ppenumatsa1/model-to-harness/blob/8a2ac71dc8afb4b82e2e49bd37d35cf9d3647225/agent-framework/double-charge/langgraph/backend/src/model_to_harness_langgraph/graph/workflows/double_charge.py)
uses named nodes:

    builder.add_edge("dispatch_validations", "billing_validation")
    builder.add_edge("dispatch_validations", "policy_validation")
    builder.add_edge("billing_validation", "join_validations")
    builder.add_edge("policy_validation", "join_validations")

These are excerpts, not standalone programs; setup and surrounding routes are
omitted. In LangGraph, `builder` is a `StateGraph(DoubleChargeState)` with registered
nodes. Both checks run in the same parallel round; **reducers** combine their
results and evidence in state.

The join applies the business rules. Valid billing but ineligible policy closes
the case **without a refund**. Missing or invalid required evidence fails the
investigation; it is not a policy rejection.

Different framework mechanics, one rule: **both checks must pass before
requesting approval.**

### 2. Eligibility is not permission

The checks pass. The refund is eligible—but nobody has authorized it yet.

The workflow pauses for a reviewer. Neither the customer's request nor the
model's recommendation counts as approval.

This MAF implementation uses `ctx.request_info(...)` for typed input; LangGraph
uses `interrupt(...)`. These mechanisms manage the pause, not permission.
The application must check the reviewer's identity and authority.

The reviewer can return later. A **checkpoint** saves resumable execution state.
The application can end the request and resume the workflow later. In our design,
one command records the decision; a separate command resumes the workflow.
Approval allows the refund path to continue. Denial closes it without a refund.

LangGraph restarts the interrupted node on resume, so code before the pause
must be safe to repeat.

PostgreSQL records the business evidence and decisions; framework checkpoints
save execution progress. **A checkpoint is not proof that money moved.**

### 3. Refund once. Verify before closing.

After approval and resume, the workflow submits the refund with a stable
**idempotency key**—an identifier reused for the same refund request across attempts.

But what if the response is lost? The application checks for an existing refund
and retries only within its defined limits, using the same key. If the outcome
remains uncertain, the case goes to **manual review** for reconciliation.
A missing response does not prove the payment failed.

Next, the workflow verifies that the evidence shows one matching refund.
A mismatch goes to manual review, not a success message.

Only after verification does the model draft the customer update and the
application record the outcome.

Payments and notifications are simulated here. A real payment system must enforce
the idempotency contract and supply authoritative refund evidence.

**Framework retries are not an exactly-once guarantee. The application still
needs idempotency and verification.**

## The orchestration patterns we just used

Our case used several orchestration patterns—without needing a team of
autonomous agents.

| Pattern | Where we used it |
|---|---|
| **Sequential** | Submit, verify, then notify. |
| **Parallel** | Check billing and policy independently. |
| **Fan-out/fan-in** | Start both checks and join their results. |
| **Conditional routing** | Continue, close without refund, fail, or seek review. |
| **Human-in-the-loop** | Pause for approval and resume from the recorded decision. |

Other workloads may add specialist handoffs, supervisor-led delegation, or
bounded review loops—but multiple steps do not automatically require multiple agents.

## Agent SDKs and orchestration: choosing the fit

[MAF](https://learn.microsoft.com/en-us/agent-framework/overview/) and
[LangGraph](https://docs.langchain.com/oss/python/langgraph/overview) make our
coordination choices visible. Other options include the
[OpenAI Agents SDK](https://openai.github.io/openai-agents-python/) for agents,
handoffs, and guardrails; [CrewAI](https://docs.crewai.com/) for crews and flows;
and [Google ADK](https://adk.dev/) for agent composition and workflows.

These are overlapping approaches, not rankings. Ask how the chosen version
handles persistence, human input, failure, integrations, and deployment.
Pick contracts your team can understand when the happy path ends.

## The usual suspects around the workflow

The workflow needs a runtime and durable storage, alongside the same cross-cutting
concerns introduced in Part 1. Framework and runtime are responsibilities, not
necessarily separate products.

- **Experience:** where people review progress and issue approval commands.
- **Standards:** MCP for tools and data, A2A for agents, and AG-UI for user interfaces.
- **Memory and knowledge:** what information is retained and made available to the model.
- **Identity, security, and governance:** who can act, what they can access, and
  which controls apply.
- **Observability and evals:** what happened and whether the workflow reached
  the correct outcome.

In this repository, each framework lane owns its application and deployment.
They share framework-neutral fixtures, simulators, and evaluation contracts, not
a hidden orchestration layer.

We started with "I was charged twice." The framework's contribution was not a
better apology. It was a coordinated path through evidence, approval, uncertainty,
and verification—with explicit outcomes when the refund could not proceed.

## Explore the code

The [public repository](https://github.com/ppenumatsa1/model-to-harness) contains
both independent implementations. Start with the
[MAF walkthrough](https://github.com/ppenumatsa1/model-to-harness/blob/8a2ac71dc8afb4b82e2e49bd37d35cf9d3647225/agent-framework/double-charge/maf/README.md)
or the
[LangGraph walkthrough](https://github.com/ppenumatsa1/model-to-harness/blob/8a2ac71dc8afb4b82e2e49bd37d35cf9d3647225/agent-framework/double-charge/langgraph/README.md),
then trace a case through approval, refund, and verification.

The [technical companion](https://github.com/ppenumatsa1/model-to-harness/blob/8a2ac71dc8afb4b82e2e49bd37d35cf9d3647225/docs/articles/02-agent-frameworks.md)
and [business rules](https://github.com/ppenumatsa1/model-to-harness/blob/8a2ac71dc8afb4b82e2e49bd37d35cf9d3647225/docs/design/business-rules.md)
provide deeper detail. Source links are pinned to a public snapshot so the
excerpts remain inspectable as the repository evolves.

The demonstrated package versions are `agent-framework-core 1.16.0`,
`langgraph 1.2.11`, and `langgraph-checkpoint-postgres 3.1.2`.

## Where this series goes next

A framework helps coordinate work. What gives an agent the environment to pursue
a goal when the path is not already laid out?

That is **the harness**—the focus of the next article. Context, skills, tools,
permissions, a workspace, and artifacts give the agent an environment to
investigate, act, and verify progress.

**The framework coordinates the work. The harness equips the agent to carry it out.**

## References and further reading

- [Microsoft Agent Framework documentation](https://learn.microsoft.com/en-us/agent-framework/overview/)
- [MAF workflow concepts and primitives](https://learn.microsoft.com/en-us/agent-framework/concepts/workflows/)
- [MAF human-in-the-loop workflows](https://learn.microsoft.com/en-us/agent-framework/workflows/human-in-the-loop)
- [MAF workflow checkpoints](https://learn.microsoft.com/en-us/agent-framework/workflows/checkpoints)
- [LangGraph workflows and agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents)
- [LangGraph interrupts and resume](https://docs.langchain.com/oss/python/langgraph/interrupts)
- [OpenAI Agents SDK documentation](https://openai.github.io/openai-agents-python/)
- [CrewAI documentation](https://docs.crewai.com/)
- [Google Agent Development Kit documentation](https://adk.dev/)
- [Model Context Protocol specification](https://modelcontextprotocol.io/specification/latest)
- [A2A Protocol documentation](https://a2a-protocol.org/latest/)
- [AG-UI documentation](https://docs.ag-ui.com/)
