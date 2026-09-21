import { beforeEach, describe, expect, it } from "vitest";
import { clearStartIntent, readStartIntent, saveStartIntent, START_INTENT_KEY } from "./startIntent";

describe("pending Start command storage", () => {
  beforeEach(() => sessionStorage.clear());

  it("retains the exact intent and clears it only explicitly", () => {
    const payload = {
      request_id: crypto.randomUUID(), complaint: "Charged twice.",
      customer_id: "customer", scenario_id: "no-duplicate", operator_id: "operator",
      existing_case_id: "case", idempotency_key: "refund",
    };
    saveStartIntent(sessionStorage, payload);
    expect(readStartIntent(sessionStorage)).toEqual(payload);
    clearStartIntent(sessionStorage);
    expect(readStartIntent(sessionStorage)).toBeUndefined();
  });

  it.each(["{}", "null", "not-json", '{"request_id":"invalid"}'])("rejects invalid persisted data: %s", (raw) => {
    sessionStorage.setItem(START_INTENT_KEY, raw);
    expect(() => readStartIntent(sessionStorage)).toThrow();
    expect(sessionStorage.getItem(START_INTENT_KEY)).toBe(raw);
  });
});
