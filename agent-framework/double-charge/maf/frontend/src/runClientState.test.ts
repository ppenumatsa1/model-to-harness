import { describe, expect, it } from "vitest";
import { freshRunClientState } from "./runClientState";

describe("freshRunClientState", () => {
  it("clears all run-scoped AG-UI state for a second run", () => {
    const first = freshRunClientState();
    first.aguiEvents.push({ type: "CUSTOM" });
    first.events.push({} as never);
    first.aguiCursor = 42;
    first.malformed = 2;
    first.aguiDisconnected = true;

    const second = freshRunClientState();
    expect(second).toEqual({
      run: undefined,
      events: [],
      aguiEvents: [],
      aguiCursor: 0,
      malformed: 0,
      aguiDisconnected: false
    });
  });
});

