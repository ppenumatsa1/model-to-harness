import { afterEach, describe, expect, it, vi } from "vitest";
import { api, parseAguiSse } from "./api";

afterEach(() => vi.unstubAllGlobals());

it("sends independent operator identities on Start and Resume command bodies", async () => {
  const fetch = vi.fn().mockImplementation(async () => new Response(JSON.stringify({}), { status: 200 }));
  vi.stubGlobal("fetch", fetch);
  await api.start({
    complaint: "Charged twice", customer_id: "customer-test", scenario_id: "duplicate-confirmed",
    existing_case_id: "case-test", idempotency_key: "refund-test", operator_id: "case-opener"
  });
  await api.resume("run-test", "checkpoint-test", "different-resumer");
  expect(JSON.parse(fetch.mock.calls[0][1].body)).toMatchObject({ operator_id: "case-opener" });
  expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({ checkpoint_id: "checkpoint-test", operator_id: "different-resumer" });
});

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
