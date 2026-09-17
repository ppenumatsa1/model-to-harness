import type { StartPayload } from "./api";

export const START_INTENT_KEY = "maf-double-charge.pending-start.v1";
export type StartIntent = StartPayload & { request_id: string };
const fields = [
  "request_id", "complaint", "customer_id", "scenario_id",
  "operator_id", "existing_case_id", "idempotency_key"
] as const;

function isStartIntent(value: unknown): value is StartIntent {
  return typeof value === "object" && value !== null
    && Object.keys(value).length === fields.length
    && fields.every((field) => field in value && typeof Reflect.get(value, field) === "string"
      && Reflect.get(value, field).trim().length > 0)
    && /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(Reflect.get(value, "request_id"));
}

export function readStartIntent(storage: Storage): StartIntent | undefined {
  const raw = storage.getItem(START_INTENT_KEY);
  if (raw === null) return undefined;
  const value: unknown = JSON.parse(raw);
  if (!isStartIntent(value)) throw new Error("Invalid pending Start identity; inspect session storage before starting another case.");
  return value;
}

export function saveStartIntent(storage: Storage, payload: StartIntent): void {
  if (!isStartIntent(payload)) throw new Error("Cannot retain an invalid Start request.");
  storage.setItem(START_INTENT_KEY, JSON.stringify(payload));
}

export function clearStartIntent(storage: Storage): void {
  storage.removeItem(START_INTENT_KEY);
}
