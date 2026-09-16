import { useAgent } from "@copilotkit/react-core/v2";
import { useEffect, useRef, useState } from "react";

interface Invocation { completion: Promise<unknown>; detachment?: Promise<void> }
const invocations = new WeakMap<object, Invocation>();

export function SelectedRunAssistant({ caseId }: { caseId?: string }) {
  const { agent, isReady } = useAgent({
    agentId: "selected-run-panel", runtimeAgentId: "selected-run", threadId: caseId ?? "no-selected-run"
  });
  const [answer, setAnswer] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const generation = useRef(0);
  const selection = useRef(caseId);
  selection.current = caseId;

  useEffect(() => {
    let active = true;
    generation.current += 1;
    setAnswer("");
    setError("");
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
      if (isReady) { agent.setMessages([]); agent.setState({}); }
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
  }, [agent, isReady, caseId]);

  async function ask() {
    if (!caseId || busy || invocations.has(agent)) return;
    const started = generation.current;
    const current = () => started === generation.current && selection.current === caseId;
    setBusy(true);
    setError("");
    try {
      agent.threadId = caseId;
      agent.setMessages([]);
      agent.setState({});
      const completion = agent.runAgent({ runId: crypto.randomUUID() });
      const invocation: Invocation = { completion };
      invocations.set(agent, invocation);
      let result;
      try { result = await completion; }
      finally {
        await invocation.detachment;
        if (invocations.get(agent) === invocation) invocations.delete(agent);
      }
      if (!current()) return;
      const message = [...result.newMessages].reverse().find((item) => item.role === "assistant");
      setAnswer(typeof message?.content === "string" ? message.content : "No safe summary was returned.");
    } catch (caught) {
      if (current()) setError(caught instanceof Error ? caught.message : "Selected-run explanation failed.");
    } finally { if (current()) setBusy(false); }
  }
  return <section className="panel assistant-panel">
    <span className="eyebrow">CopilotKit selected-run context</span><h2>Safe run explainer</h2>
    <p>The read-only selected-run runtime explains allowlisted durable facts. It cannot approve, resume, or invoke billing actions.</p>
    <button disabled={!caseId || !isReady || busy} onClick={() => void ask()}>{busy ? "Reading durable events…" : "Explain selected run"}</button>
    {error && <p role="alert">{error}</p>}{answer && <blockquote>{answer}</blockquote>}
    <p className="boundary-note">No chain-of-thought, customer complaint, prompts, secrets, or raw checkpoint payloads are sent as client model context.</p>
  </section>;
}
