# Runtime Infrastructure: Give Your Agent a Computer and a Badge

_This is Part 4 of the model-to-harness series, continuing from
[Part 1: From Models to Harnesses](https://www.linkedin.com/pulse/from-models-harnesses-how-ai-agents-learn-finish-job-penumatsa-g2mjc),
[Part 2: Agent Frameworks](https://www.linkedin.com/pulse/agent-frameworks-model-can-answer-workflow-finish-penumatsa-sdz6c),
and
[Part 3: Agent Harnesses](https://www.linkedin.com/pulse/agent-harnesses-giving-agents-place-work-praveen-varma-penumatsa-1tmwf).
You don't need the earlier parts to follow this story._

## 1. A model can write the script. It can't run it.

Checkout failed for order 8472. The customer's payment was authorized, but the
order was never confirmed.

An AI agent has been asked to find out why. It has already checked the order
record and the payment status. Something happened in between. So the agent asks
for something new:

> _"Let me run a small Python script over the last hour of checkout logs."_

That one sentence changes the problem.

Somewhere, a machine has to start a process, load the logs, and keep the output.
The script needs a network path and credentials, and someone has to decide
whose. If the investigation takes all evening, that machine has to be there all
evening too.

**This is where agent design stops being abstract and becomes physical.**

So far in this series, a **model** reasons, an **agent loop** lets it act and
check the result, a **framework** coordinates approvals and pauses, and a
**harness** gives the agent a place to work: context, tools, a workspace, and
permissions.

But saying an agent "has a shell" doesn't tell you where that shell runs, what
it can reach, or who the agent is when it knocks on a door. That's the layer
underneath: **runtime infrastructure**. (Frameworks also use "runtime" for the
engine that steps through their workflow. Here, it means the machine, sandbox,
identity, and lifecycle beneath it all.)

> **Harness = what the agent may do. Runtime infrastructure = where it runs,
> what it reaches, who it is, and how long it lives.**

## 2. Why agents need a laptop and a badge

Picture a new investigator on the incident team. With only a desk, they must ask
someone else to run every query. They can't try an idea, watch it fail, and try
again.

Now give them **a laptop** and **a badge**. The laptop is a place to work: run a
query, fix the script, run it again, and find the files still there after lunch.
The badge says who they are. It opens the log room but not the payments vault,
records every door under their name, and can be revoked on its own.

Agents need the same two things:

**Own computer → explores:** runs, inspects, and retries in its own sandbox,
where mistakes stay contained.

**Own computer → keeps going:** files and working state survive between steps.

**Own identity → least access:** scoped, short-lived credentials, not a borrowed
login.

**Own identity → accountable:** every action traces back to the agent, and can
be revoked.

**A computer lets the agent explore. An identity lets it act as itself.
Together, they turn one-shot answers into work that can run for hours.**

## 3. Seven building blocks of runtime infrastructure

So what is runtime infrastructure? The simplest answer: **it turns an approved
action into something that runs somewhere.** To run the log script, it needs
seven building blocks you'll find under almost every agent platform.

The script needs a process with CPU, memory, and Python: **compute**. It needs
files that survive a restart, usually a mounted folder for logs and output: the
**workspace**. It needs a wall between this investigation, other tasks, and the
host: **isolation**.

It needs a road to the log store, and only there: **networking**. It shows the
agent's own badge, scoped to reading logs and set to expire: **identity and
credentials**. A timeout and memory cap stop a runaway loop: **resource
limits**.

Finally, someone decides what happens when the work stops: pause, restore,
recycle, or destroy. That's **lifecycle**, and it matters more than it looks.

Three of these make the sandbox: compute and the workspace, inside an isolation
wall. The other four surround it and decide what it reaches, as whom, how much
it uses, and how long it lives.

**Figure 1. The agent's computer**

![Runtime infrastructure puts compute (with Bash, Python, and a browser) and the workspace, mounted files that survive restarts, inside an isolation wall: the sandbox. Networking, identity, resource limits, and lifecycle sit around it. The harness sends approved actions in; results come back. Business systems are reached only through allowed routes with the agent's scoped identity.](assets/04-agent-computer-primitives.png)

The wall itself can be a container, a virtual machine, or a lightweight microVM.

## 4. One script, one long night

Follow the script from start to finish.

1. The harness approves the action: run _analyze_checkout.py_ on the last hour
   of logs.
2. Runtime infrastructure finds or creates an environment and restores the
   agent's workspace: its _plan.md_, notes, and earlier output.
3. It applies network rules and issues a short-lived, read-only log credential
   under the agent's own identity.
4. The script runs within its time and memory limits.
5. The output goes back to the harness, which passes the useful part to the
   model.

The answer arrives at 5:10 p.m.: the inventory reservation expired eleven
seconds before the payment was confirmed. The agent notes it, runs two more
checks, and proposes a fix: re-reserve the stock and confirm the order.

That fix affects a customer, so it needs a person's approval. The on-call
manager has gone home.

Now lifecycle matters. Nobody keeps a machine running all night just to wait, so
the workspace is saved and the machine is recycled. At 9:00 a.m., the manager
approves, and the investigation resumes on a **different machine** with its
workspace restored and a fresh credential.

Two things never lived in the runtime infrastructure. The approval was recorded
in the application as an explicit decision. The business system applied the fix
and checked the real order state. **Restarting a machine doesn't approve a
fix.**

_(Our published checkout example deliberately gives the agent read-only
diagnostic tools and no shell. The script here is illustrative.)_

## 5. Your laptop, your cloud, or theirs?

**Local.** The script runs on a developer's laptop, with their files, network,
and often their credentials, as with Claude Code or Copilot CLI. It's the
fastest way to learn, but the trust boundary is the whole laptop, and the agent
borrows the developer's badge.

**Self-hosted.** The environment moves into containers or VMs your team runs,
for example on Azure Container Apps or AKS. You own the image, the network
rules, the identity, the limits, and the overnight cleanup. Or keep your harness
and rent the sandbox: Azure Container Apps dynamic sessions or E2B create one on
demand and clean it up, while you still decide what it reaches and as whom.

**Managed.** The provider runs the runtime infrastructure for you. Microsoft
Foundry Hosted Agents, Amazon Bedrock AgentCore Runtime, and Google's Agent
Platform Runtime host the agent code you bring. Claude Managed Agents and
LangChain's Managed Deep Agents go further and supply the harness too.

**Figure 2. Where runtime infrastructure lives**

![Three homes for the same agent compared by compute, identity, isolation, lifecycle, and what runs around it. Local runs on your laptop and borrows your credentials. Self-hosted runs in containers or VMs you operate, or in a rented sandbox, with an identity you issue. Managed, shown as Foundry Hosted Agents, gives each session its own VM-isolated sandbox and the agent its own Entra identity, releases idle compute while keeping files, and runs the endpoint, versions, tools, and tracing. Moving right, the provider runs more.](assets/04-where-runtime-lives.png)

Whichever home you choose, ask the same questions: Where do the loop and tools
run? What can they reach, and as whom? What survives a pause? Who cleans up?

## 6. The laptop and the badge, on Foundry

Here's how one managed option, Microsoft Foundry Hosted Agents, fills in the
building blocks from Figure 1. You package the agent as a container (MAF,
LangGraph, or your own code) and deploy it.

**Figure 3. Inside managed runtime infrastructure: Foundry Hosted Agents**

![Foundry Hosted Agents: a client calls the agent's dedicated endpoint. Foundry Agent Service runs the endpoint, the agent's own Entra identity, versions, conversations, a state store, and tracing. Your code runs in a per-session, VM-isolated sandbox where $HOME and /files persist and you choose CPU and memory. Compute is active, released after an idle timeout with files kept, then resumed with files restored. The agent calls Foundry models, Toolbox tools, and your services as its own identity.](assets/04-foundry-hosted-agents.png)

- **Compute, isolation, limits:** a sandbox per session, VM-isolated from every
  other session, with the CPU and memory you choose.
- **Workspace:** _$HOME_ and _/files_, kept across turns and idle periods.
- **Networking:** outbound traffic can go through your own Azure virtual
  network.
- **Identity:** the agent gets **its own Microsoft Entra identity**. Models are
  reachable by default; anything else, like the log store, needs a role you
  grant.
- **Lifecycle:** idle compute is released (after 15 minutes by default), and the
  files wait for the next request.

Around the sandbox, Foundry also runs the endpoint, versions, a Toolbox of tools
over MCP, and tracing. Your code runs inside; the approval and the order record
still live in your application. Our checkout example's
[hosted-agent adapter](https://github.com/ppenumatsa1/model-to-harness/tree/main/harness/checkout-recovery/maf/infra/foundry-hosted/agent)
keeps start, approve, and resume as explicit commands.

## 7. The machine forgets. Should the agent?

The stack is now complete: the model reasons, the loop acts, the framework
coordinates, the harness decides, and **runtime infrastructure runs it**.

Look back at the night. Three kinds of state carried order 8472 through it, and
each lives somewhere different.

- **Runtime state** is the place to work: the sandbox, its processes, and the
  workspace files. It lasts as long as the session, then it's gone.
- **Business state** is the truth: the order, the payment, the approval. It
  lives in the system of record, never in the sandbox.
- **Agent memory** is what the agent chooses to carry forward: not every log
  line, just the few things worth knowing next time.

The first two worked. The third didn't exist.

A month later, order 9315 gets stuck the same way. A fresh sandbox starts. The
8472 workspace is long gone, and the order database knows orders, not lessons.
The agent starts from scratch. What should it have brought along?

- **Conversation history:** what was said so far in this case.
- **Episodic memory:** what happened last time. _"8472 was an inventory
  reservation that expired seconds before payment."_
- **Semantic memory:** facts about the world. _"Reservations expire if payment
  is slow."_
- **Procedural memory:** how to do the job. _"Check reservation timing before
  reading payment logs."_
- **Preferences:** how people like to work. _"The on-call manager wants a
  one-line summary with every approval request."_

Deciding what to keep, what to forget, and who may read it is a design problem
of its own.

> **Runtime state ≠ agent memory ≠ business state.**

Runtime infrastructure gives the agent a place to work. Memory decides what it
learns from the work. That's where we go next, in Part 5: **memory**.

---

**Explore the code:**

- **Framework lanes** from
  [Part 2](https://www.linkedin.com/pulse/agent-frameworks-model-can-answer-workflow-finish-penumatsa-sdz6c):
  the
  [MAF walkthrough](https://github.com/ppenumatsa1/model-to-harness/blob/8a2ac71dc8afb4b82e2e49bd37d35cf9d3647225/agent-framework/double-charge/maf/README.md)
  and the
  [LangGraph walkthrough](https://github.com/ppenumatsa1/model-to-harness/blob/8a2ac71dc8afb4b82e2e49bd37d35cf9d3647225/agent-framework/double-charge/langgraph/README.md),
  each with a Foundry hosted-agent adapter
  ([MAF](https://github.com/ppenumatsa1/model-to-harness/tree/8a2ac71dc8afb4b82e2e49bd37d35cf9d3647225/agent-framework/double-charge/maf/infra/foundry-hosted/agent),
  [LangGraph](https://github.com/ppenumatsa1/model-to-harness/tree/8a2ac71dc8afb4b82e2e49bd37d35cf9d3647225/agent-framework/double-charge/langgraph/infra/foundry-hosted/agent)).
- **Checkout recovery** from
  [Part 3](https://www.linkedin.com/pulse/agent-harnesses-giving-agents-place-work-praveen-varma-penumatsa-1tmwf):
  [MAF](https://github.com/ppenumatsa1/model-to-harness/tree/main/harness/checkout-recovery/maf)
  and
  [Copilot SDK](https://github.com/ppenumatsa1/model-to-harness/tree/main/harness/checkout-recovery/copilot-sdk),
  with their
  [MAF](https://github.com/ppenumatsa1/model-to-harness/tree/main/harness/checkout-recovery/maf/infra/foundry-hosted/agent)
  and
  [Copilot SDK](https://github.com/ppenumatsa1/model-to-harness/tree/main/harness/checkout-recovery/copilot-sdk/infra/foundry-hosted/agent)
  hosted adapters.

Each adapter sends start, approve, and resume as explicit commands to the
workflow service. They are integration points, not a verified production
deployment, and the business systems are simulated.

**References:**

- **Local:** [Claude Code](https://code.claude.com/docs/en/overview) ·
  [Copilot CLI](https://docs.github.com/en/copilot/concepts/agents/copilot-cli/about-copilot-cli)
- **Self-hosted:**
  [Azure Container Apps](https://learn.microsoft.com/en-us/azure/container-apps/overview)
  · [AKS](https://learn.microsoft.com/en-us/azure/aks/what-is-aks)
- **Rented sandbox:**
  [Azure Container Apps dynamic sessions](https://learn.microsoft.com/en-us/azure/container-apps/sessions)
  · [E2B](https://e2b.dev/docs)
- **Managed:**
  [Microsoft Foundry Hosted Agents](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/hosted-agents)
  ·
  [Amazon Bedrock AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agents-tools-runtime.html)
  ·
  [Google Agent Platform Runtime](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale)
  ·
  [Claude Managed Agents](https://platform.claude.com/docs/en/managed-agents/overview)
  ·
  [Managed Deep Agents](https://docs.langchain.com/langsmith/python/managed-deep-agents-overview)
- **Agent identity:**
  [Microsoft Entra Agent ID](https://learn.microsoft.com/en-us/entra/agent-id/what-are-agent-identities)
