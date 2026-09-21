export interface StartIntent {
  fixture_id: string;
  request_id: string;
}

const startKey = "checkout-recovery.pending-start";
type IntentStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;

export class StartIntentStore {
  private pending: StartIntent | null = null;

  constructor(
    private readonly storage?: IntentStorage,
    private readonly createId = () => crypto.randomUUID()
  ) {
    try {
      const value: unknown = JSON.parse(storage?.getItem(startKey) ?? "null");
      if (
        typeof value === "object" && value !== null &&
        "fixture_id" in value && typeof value.fixture_id === "string" &&
        "request_id" in value && typeof value.request_id === "string" &&
        /^[a-z0-9-]+$/.test(value.fixture_id) &&
        /^[a-f0-9-]{36}$/i.test(value.request_id)
      ) {
        this.pending = { fixture_id: value.fixture_id, request_id: value.request_id };
      }
    } catch {
      // A disabled browser store must not prevent explicit workflow commands.
    }
  }

  get current(): StartIntent | null {
    return this.pending;
  }

  begin(fixtureId: string): StartIntent {
    if (this.pending?.fixture_id === fixtureId) return this.pending;
    this.pending = { fixture_id: fixtureId, request_id: this.createId() };
    try {
      this.storage?.setItem(startKey, JSON.stringify(this.pending));
    } catch {
      // The in-memory intent still protects retries in this tab.
    }
    return this.pending;
  }

  complete(): void {
    this.pending = null;
    try {
      this.storage?.removeItem(startKey);
    } catch {
      // Storage can be unavailable in restricted browsing contexts.
    }
  }
}

export function browserIntentStore(): StartIntentStore {
  try {
    return new StartIntentStore(window.sessionStorage);
  } catch {
    return new StartIntentStore();
  }
}

export function selectedCaseId(url: URL): string | null {
  const value = url.searchParams.get("case");
  return value && /^[a-zA-Z0-9-]{1,120}$/.test(value) ? value : null;
}

export function selectCaseUrl(url: URL, caseId: string): URL {
  const selected = new URL(url);
  selected.searchParams.set("case", caseId);
  return selected;
}
