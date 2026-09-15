import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, checkoutApi, loadCaseWorkspace } from "./api";

const casePayload = {
  case_id: "case 1",
  run_id: "run-1",
  fixture_id: "recoverable-inventory-reservation",
  phase: "closed",
  diagnostic_disposition: "recover_inventory",
  approval_decision: "not_required",
  approval_request_id: null,
  remediation_action: "recreate_inventory_reservation",
  remediation_status: "applied",
  verification_result: true,
  terminal_status: "recovered",
  failure_code: "none",
  workspace_artifact: {
    artifact_id: "artifact-1",
    kind: "checkout_recovery_plan_evidence_summary",
    revision: 3,
    updated_at: "2026-01-01T00:00:00Z"
  }
} as const;

afterEach(() => vi.unstubAllGlobals());

describe("checkout API", () => {
  it("sends only the fixture identifier for a start command", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(casePayload), { status: 201 })
    );
    vi.stubGlobal("fetch", fetchMock);

    await checkoutApi.start(casePayload.fixture_id);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/cases",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ fixture_id: casePayload.fixture_id })
      })
    );
  });

  it("loads only the three safe workspace projections", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(casePayload)))
      .mockResolvedValueOnce(new Response(JSON.stringify([])))
      .mockResolvedValueOnce(new Response(JSON.stringify(casePayload.workspace_artifact)));
    vi.stubGlobal("fetch", fetchMock);

    const workspace = await loadCaseWorkspace("case 1");

    expect(workspace.case.case_id).toBe("case 1");
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/api/cases/case%201",
      "/api/cases/case%201/events",
      "/api/cases/case%201/workspace-artifact"
    ]);
  });

  it("carries the deliberate start request ID without browser credentials", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(casePayload), { status: 201 })
    );
    vi.stubGlobal("fetch", fetchMock);
    await checkoutApi.start(casePayload.fixture_id, "request-1");
    expect(fetchMock).toHaveBeenCalledWith("/api/cases", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ fixture_id: casePayload.fixture_id, request_id: "request-1" })
    });
  });

  it("records a bound approval without implicitly resuming", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(casePayload)));
    vi.stubGlobal("fetch", fetchMock);
    const command = {
      approval_request_id: "approval-1",
      decision: "approved" as const,
      reviewer_id: "reviewer-1",
      reason: "Reviewed checkout remediation"
    };
    await checkoutApi.approval("case-1", command);
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith("/api/cases/case-1/approval", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(command)
    });
  });

  it("surfaces the API's safe error detail", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "approval rejected" }), { status: 409 }))
    );

    await expect(checkoutApi.resume("case-1")).rejects.toEqual(
      new ApiError(409, "approval rejected")
    );
  });

  it.each([
    JSON.stringify({ detail: "password=private-provider-error" }),
    JSON.stringify({ detail: [{ input: "private-tool-input" }] }),
    "<html>upstream private error</html>"
  ])("does not render unrestricted error bodies: %s", async (body) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body, { status: 500 })));
    await expect(checkoutApi.resume("case-1")).rejects.toEqual(
      new ApiError(500, "Request failed (500)")
    );
  });
});
