import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "../src/api";

afterEach(() => vi.unstubAllGlobals());
describe("case-keyed commands and reads", () => {
  it("sends distinct explicit operator identities and never implicitly resumes approval", async () => {
    const fetcher = vi.fn().mockImplementation(async () => Response.json({}));
    vi.stubGlobal("fetch", fetcher);
    await api.start({ complaint: "duplicate complaint", customer_id: "c", scenario_id: "duplicate-confirmed",
      operator_id: "opener", existing_case_id: "case-a", idempotency_key: "idempotent" });
    await api.approve("case/a", { checkpoint_id: "cp", reviewer_id: "reviewer", reason: "verified evidence", decision: "approve" });
    expect(fetcher).toHaveBeenCalledTimes(2);
    await api.resume("case/a", "cp", "resumer");
    const calls = fetcher.mock.calls;
    expect(calls.map(([url]) => url)).toEqual(["/api/cases", "/api/cases/case%2Fa/approval", "/api/cases/case%2Fa/resume"]);
    expect(JSON.parse(calls[0][1].body).operator_id).toBe("opener");
    expect(JSON.parse(calls[1][1].body)).toEqual({ checkpoint_id: "cp", reviewer_id: "reviewer", reason: "verified evidence", decision: "approve" });
    expect(JSON.parse(calls[2][1].body)).toEqual({ checkpoint_id: "cp", operator_id: "resumer" });
  });
  it("requests ten history records and native workspace, encoding cursor and case IDs", async () => {
    const fetcher = vi.fn().mockImplementation(async () => Response.json({}));
    vi.stubGlobal("fetch", fetcher);
    await api.cases("cursor /&");
    await api.case("case/a");
    expect(fetcher.mock.calls.map(([url]) => url)).toEqual([
      "/api/cases?limit=10&cursor=cursor%20%2F%26", "/api/cases/case%2Fa/workspace"
    ]);
  });
  it("returns a safe status error for structured validation failures without leaking details", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ detail: [{ input: "PRIVATE" }] }, { status: 422 })));
    await expect(api.case("case")).rejects.toEqual(new ApiError("Request failed (422)", 422));
  });
});
