import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  createResearch,
  getResearch,
  getResearchSources,
  getResearchTasks,
  parseReport,
} from "@/lib/api/research";
import { ApiError } from "@/lib/api/errors";
import type { ResearchJob } from "@/lib/types/research";

const BASE = "http://localhost:8000/api";

function jsonResponse(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("lib/api/research", () => {
  const origFetch = global.fetch;

  beforeEach(() => {
    global.fetch = vi.fn();
  });
  afterEach(() => {
    global.fetch = origFetch;
  });

  it("createResearch POSTs the query and returns the job (202)", async () => {
    const job = { id: "abc", query: "q", status: "pending" };
    (global.fetch as any).mockResolvedValue(jsonResponse(202, job));

    const result = await createResearch("q");
    expect(global.fetch).toHaveBeenCalledWith(`${BASE}/research`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: "q", workflow_type: "deep_research" }),
    });
    expect(result.id).toBe("abc");
  });

  it("createResearch throws 422 as ApiError with a usable message", async () => {
    (global.fetch as any).mockResolvedValue(
      jsonResponse(422, {
        detail: [{ loc: ["query"], msg: "Field required", type: "value_error" }],
      }),
    );
    await expect(createResearch("")).rejects.toMatchObject({
      status: 422,
      message: "Field required",
    });
  });

  it("createResearch maps a 400 detail string", async () => {
    (global.fetch as any).mockResolvedValue(
      jsonResponse(400, { detail: "Query too long" }),
    );
    await expect(createResearch("x")).rejects.toMatchObject({
      status: 400,
      message: "Query too long",
    });
  });

  it("getResearch returns the job document", async () => {
    (global.fetch as any).mockResolvedValue(
      jsonResponse(200, { id: "1", status: "running" }),
    );
    const job = await getResearch("1");
    expect(job.id).toBe("1");
    expect(job.status).toBe("running");
  });

  it("getResearch throws ApiError on 404", async () => {
    (global.fetch as any).mockResolvedValue(jsonResponse(404, { detail: "Not found" }));
    await expect(getResearch("missing")).rejects.toMatchObject({ status: 404 });
  });

  it("getResearchTasks and getResearchSources parse list payloads", async () => {
    (global.fetch as any)
      .mockResolvedValueOnce(
        jsonResponse(200, { research_id: "1", tasks: [] }),
      )
      .mockResolvedValueOnce(
        jsonResponse(200, {
          research_id: "1",
          sources: [{ id: "s1", url: "https://x.test", title: "X", evidence: [] }],
        }),
      );
    const tasks = await getResearchTasks("1");
    const sources = await getResearchSources("1");
    expect(tasks.tasks).toEqual([]);
    expect(sources.sources[0].id).toBe("s1");
  });

  it("parseReport decodes the JSON string stored on a completed job", () => {
    const job: ResearchJob = {
      id: "1",
      query: "q",
      workflow_type: "deep_research",
      status: "completed",
      created_at: "",
      started_at: null,
      completed_at: null,
      error: null,
      stage: "completed",
      attempts: 1,
      progress: { completed_tasks: 1, total_tasks: 1 },
      report: JSON.stringify({
        title: "T",
        summary: "S",
        sections: [{ heading: "H", content: "C", citation_source_ids: ["a"] }],
        conclusion: "Done",
      }),
    };
    const report = parseReport(job);
    expect(report?.title).toBe("T");
    expect(report?.sections[0].heading).toBe("H");
    expect(report?.conclusion).toBe("Done");
  });

  it("parseReport returns null when the report is absent or malformed", () => {
    expect(parseReport({ report: null } as ResearchJob)).toBeNull();
    expect(
      parseReport({ report: "{not json" } as unknown as ResearchJob),
    ).toBeNull();
  });

  it("ApiError is exported and carries status", () => {
    const e = new ApiError(500, "boom");
    expect(e.status).toBe(500);
    expect(e.message).toBe("boom");
    expect(e instanceof Error).toBe(true);
  });
});
