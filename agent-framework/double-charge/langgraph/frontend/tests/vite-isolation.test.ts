// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { serverConfig } from "../server-config";
import config from "../vite.config";

vi.mock("../server-config", () => ({ serverConfig: vi.fn(() => ({})) }));
afterEach(() => vi.clearAllMocks());
describe("actual Vite dotenv boundary", () => {
  it("disables lane dotenv reads in test mode even with a private dotenv present", () => {
    if (typeof config !== "function") throw new Error("Expected mode-dependent Vite config");
    const result = config({ mode: "test", command: "serve" });
    expect(serverConfig).toHaveBeenCalledWith({});
    expect(result).toMatchObject({ envDir: false, envPrefix: [] });
  });
  it("retains ordinary server settings and process overrides outside test mode", () => {
    if (typeof config !== "function") throw new Error("Expected mode-dependent Vite config");
    config({ mode: "development", command: "serve" });
    expect(serverConfig).toHaveBeenCalledWith();
  });
});
