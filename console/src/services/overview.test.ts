import { afterEach, describe, expect, it, vi } from "vitest";
import { overviewService } from "./index";

const reply = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }));

afterEach(() => vi.restoreAllMocks());

describe("overview service", () => {
  it("counts readiness from the real scorecard", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => reply({ source: "x.csv", counts: { green: 0, amber: 2, red: 9 }, models: [] }));
    expect(await overviewService.readiness()).toEqual({ green: 0, amber: 2, red: 9 });
  });

  it("keeps the rest of the summary off the network", async () => {
    const spy = vi.spyOn(globalThis, "fetch");
    expect((await overviewService.summary()).release).toBeTruthy();
    expect(spy).not.toHaveBeenCalled();
  });
});
