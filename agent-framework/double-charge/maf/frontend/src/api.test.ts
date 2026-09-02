import { describe, expect, it } from "vitest";
import { parseAguiSse } from "./api";

describe("parseAguiSse", () => {
  it("orders valid projection events and counts malformed frames", () => {
    const result = parseAguiSse(
      'id: 4\ndata: {"type":"STEP_STARTED","stepName":"billing_validation"}\n\n' +
        'id: 5\ndata: {"missing":"type"}\n\n' +
        'id: 6\ndata: {"type":"CUSTOM","name":"approval_requested"}\n\n'
    );
    expect(result.events.map((event) => event.type)).toEqual(["STEP_STARTED", "CUSTOM"]);
    expect(result.malformed).toBe(1);
    expect(result.lastSequence).toBe(6);
  });
});

