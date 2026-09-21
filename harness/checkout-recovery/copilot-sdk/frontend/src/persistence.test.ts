import { describe, expect, it, vi } from "vitest";
import { selectCaseUrl, selectedCaseId, StartIntentStore } from "./persistence";

function storage() {
  const values = new Map<string, string>();
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => { values.set(key, value); },
    removeItem: (key: string) => { values.delete(key); }
  };
}

describe("durable command pointers", () => {
  it("reuses an unresolved start key, including after reload", () => {
    const saved = storage();
    const intents = new StartIntentStore(saved);
    const first = intents.begin("recoverable-inventory-reservation");
    expect(first.request_id).toMatch(/^[0-9a-f-]{36}$/);
    expect(intents.begin(first.fixture_id)).toEqual(first);
    expect(new StartIntentStore(saved).begin(first.fixture_id)).toEqual(first);
  });

  it("generates a fresh ID for a completed command or another fixture", () => {
    const saved = storage();
    const intents = new StartIntentStore(saved);
    const first = intents.begin("first-fixture");
    const second = intents.begin("second-fixture");
    expect(second.request_id).not.toBe(first.request_id);
    intents.complete();
    expect(new StartIntentStore(saved).current).toBeNull();
    expect(intents.begin("second-fixture").request_id).not.toBe(second.request_id);
  });

  it("ignores malformed persisted data and tolerates unavailable storage", () => {
    const broken = {
      getItem: vi.fn(() => "{invalid"),
      setItem: vi.fn(() => { throw new Error("blocked"); }),
      removeItem: vi.fn(() => { throw new Error("blocked"); })
    };
    const intents = new StartIntentStore(broken);
    expect(intents.current).toBeNull();
    const first = intents.begin("fixture");
    expect(intents.begin("fixture")).toEqual(first);
    expect(() => intents.complete()).not.toThrow();
  });

  it("persists only the selected case pointer in the URL", () => {
    const original = new URL("https://example.test/?view=safe#workspace");
    const selected = selectCaseUrl(original, "case-123");
    expect(selectedCaseId(selected)).toBe("case-123");
    expect(selected.searchParams.get("view")).toBe("safe");
    expect(original.searchParams.has("case")).toBe(false);
    expect(selectedCaseId(new URL("https://example.test/?case=../../private"))).toBeNull();
  });
});
