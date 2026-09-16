import { useEffect, useRef, useState } from "react";
import { useAgent } from "@copilotkit/react-core/v2";
import type { WorkflowState } from "../types";

interface Invocation {
  completion: Promise<unknown>;
  detachment?: Promise<void>;
}

// The runtime agent owns a mutable message collection, including across panel mounts.
const invocations = new WeakMap<object, Invocation>();

export function AssistantPanel({ state }: { state: WorkflowState | null }) {
  const { agent, isReady } = useAgent({ agentId: "selected-run" });
  const [question, setQuestion] = useState("Why is this run in its current status?");
  const [answer, setAnswer] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const generation = useRef(0);
  const selectedRun = useRef(state?.run_id);
  selectedRun.current = state?.run_id;

  useEffect(() => {
    let active = true;
    setAnswer("");
    setError("");
    generation.current += 1;
    const detach = (invocation: Invocation) => {
      invocation.detachment ??= (async () => {
        await Promise.allSettled([agent.detachActiveRun(), invocation.completion]);
      })();
      return invocation.detachment;
    };
    const previous = invocations.get(agent);
    setBusy(Boolean(previous));
    const prepare = () => {
      if (!active) return;
      if (isReady) agent.setMessages([]);
      setBusy(false);
    };
    if (previous) void detach(previous).then(prepare);
    else prepare();
    return () => {
      active = false;
      generation.current += 1;
      const invocation = invocations.get(agent);
      if (invocation) void detach(invocation);
    };
  }, [agent, isReady, state?.run_id]);

  return (
    <section className="panel assistant-panel" aria-labelledby="assistant-title">
      <p className="eyebrow">CopilotKit selected-run context</p>
      <h2 id="assistant-title">Safe run explainer</h2>
      <p>
        This panel runs inside the CopilotKit v2 provider. Answers use allowlisted durable facts
        only; the assistant cannot approve, resume, or call billing actions.
      </p>
      <label htmlFor="selected-run-question">Question about the selected run</label>
      <textarea
        id="selected-run-question"
        value={question}
        onChange={(event) => setQuestion(event.target.value)}
      />
      <button
        disabled={!state || !isReady || busy || question.trim().length < 2}
        onClick={async () => {
          if (!state || busy || invocations.has(agent)) return;
          const requestGeneration = generation.current;
          const runId = state.run_id;
          const isCurrent = () => generation.current === requestGeneration && selectedRun.current === runId;
          setBusy(true);
          setError("");
          try {
            agent.threadId = state.run_id;
            agent.addMessage({
              id: crypto.randomUUID(),
              role: "user",
              content: question.trim()
            });
            const completion = agent.runAgent();
            const invocation: Invocation = { completion };
            invocations.set(agent, invocation);
            let result;
            try {
              result = await completion;
            } finally {
              await invocation.detachment;
              if (invocations.get(agent) === invocation) invocations.delete(agent);
            }
            if (!isCurrent()) return;
            const response = [...result.newMessages]
              .reverse()
              .find((message) => message.role === "assistant");
            setAnswer(
              response && typeof response.content === "string"
                ? response.content
                : "The read-only runtime returned no explanation."
            );
          } catch (caught) {
            if (!isCurrent()) return;
            setError(caught instanceof Error ? caught.message : "Explanation failed.");
          } finally {
            if (isCurrent()) setBusy(false);
          }
        }}
      >
        {busy ? "Explaining…" : "Explain selected run"}
      </button>
      {answer && <blockquote>{answer}</blockquote>}
      {error && <p role="alert">{error}</p>}
      <small>No chain-of-thought, raw prompts, secrets, or raw checkpoint payloads.</small>
    </section>
  );
}
