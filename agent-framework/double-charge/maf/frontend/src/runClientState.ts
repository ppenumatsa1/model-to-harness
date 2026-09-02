import type { AguiEvent, DurableEvent, RunView } from "./types";

export interface RunClientState {
  run: RunView | undefined;
  events: DurableEvent[];
  aguiEvents: AguiEvent[];
  aguiCursor: number;
  malformed: number;
  aguiDisconnected: boolean;
}

export function freshRunClientState(): RunClientState {
  return {
    run: undefined,
    events: [],
    aguiEvents: [],
    aguiCursor: 0,
    malformed: 0,
    aguiDisconnected: false
  };
}

