import { describe, expect, it } from "vitest";

import { parseAguiEvent } from "../src/agui";

describe("AG-UI projection parser", () => {
  it("accepts an allowlisted event", () => {
    expect(
      parseAguiEvent('{"type":"RUN_STARTED","runId":"run-1","sequence":1}')
    ).toMatchObject({ type: "RUN_STARTED", runId: "run-1", sequence: 1 });
  });

  it("accepts protocol-correct tool result and end events", () => {
    expect(
      parseAguiEvent(
        '{"type":"TOOL_CALL_RESULT","runId":"run-1","sequence":4,"toolCallId":"tool-1"}'
      ).type
    ).toBe("TOOL_CALL_RESULT");
    expect(
      parseAguiEvent(
        '{"type":"TOOL_CALL_END","runId":"run-1","sequence":4,"toolCallId":"tool-1"}'
      ).type
    ).toBe("TOOL_CALL_END");
  });

  it("rejects malformed and unknown events", () => {
    expect(() => parseAguiEvent('{"type":"RAW_PROMPT","runId":"run-1"}')).toThrow(
      "Malformed AG-UI event"
    );
  });
});
