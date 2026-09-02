import { useEffect, useState } from "react";
import { useAgent } from "@copilotkit/react-core/v2";
import type { WorkflowState } from "../types";

export function AssistantPanel({ state }: { state: WorkflowState | null }) {
  const { agent, isReady } = useAgent({ agentId: "selected-run" });
  const [question, setQuestion] = useState("Why is this run in its current status?");
  const [answer, setAnswer] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setAnswer("");
    setError("");
    if (isReady) agent.setMessages([]);
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
          if (!state) return;
          setBusy(true);
          setError("");
          try {
            agent.threadId = state.run_id;
            agent.addMessage({
              id: crypto.randomUUID(),
              role: "user",
              content: question.trim()
            });
            const result = await agent.runAgent();
            const response = [...result.newMessages]
              .reverse()
              .find((message) => message.role === "assistant");
            setAnswer(
              response && typeof response.content === "string"
                ? response.content
                : "The read-only runtime returned no explanation."
            );
          } catch (caught) {
            setError(caught instanceof Error ? caught.message : "Explanation failed.");
          } finally {
            setBusy(false);
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
