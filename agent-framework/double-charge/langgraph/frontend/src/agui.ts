import type { AguiEvent } from "./types";

const KNOWN_TYPES = new Set([
  "RUN_STARTED",
  "RUN_FINISHED",
  "RUN_ERROR",
  "STEP_STARTED",
  "STEP_FINISHED",
  "TOOL_CALL_START",
  "TOOL_CALL_RESULT",
  "TOOL_CALL_END",
  "CUSTOM"
]);

export function parseAguiEvent(raw: string): AguiEvent {
  const value = JSON.parse(raw) as Partial<AguiEvent>;
  if (
    typeof value.type !== "string" ||
    !KNOWN_TYPES.has(value.type) ||
    typeof value.runId !== "string" ||
    typeof value.sequence !== "number"
  ) {
    throw new Error("Malformed AG-UI event");
  }
  return value as AguiEvent;
}
