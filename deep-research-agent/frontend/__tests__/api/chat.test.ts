import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  createConversation,
  deleteConversation,
  getConversation,
  listConversations,
  sendMessage,
  updateConversation,
} from "@/lib/api/chat";

const BASE = "http://localhost:8000/api";

function jsonResponse(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("lib/api/chat", () => {
  const origFetch = global.fetch;

  beforeEach(() => {
    global.fetch = vi.fn();
  });
  afterEach(() => {
    global.fetch = origFetch;
  });

  it("createConversation POSTs title + context_mode", async () => {
    const conversation = { id: "c1", title: null, context_mode: "none" };
    (global.fetch as any).mockResolvedValue(jsonResponse(201, conversation));

    const result = await createConversation("My question", "documents");
    expect(global.fetch).toHaveBeenCalledWith(`${BASE}/conversations`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: "My question", context_mode: "documents" }),
    });
    expect(result.id).toBe("c1");
  });

  it("createConversation omits the title when not given", async () => {
    (global.fetch as any).mockResolvedValue(
      jsonResponse(201, { id: "c2", context_mode: "none" }),
    );
    await createConversation();
    expect((global.fetch as any).mock.calls[0][1].body).toBe(
      JSON.stringify({ context_mode: "none" }),
    );
  });

  it("listConversations fetches the list endpoint with pagination", async () => {
    (global.fetch as any).mockResolvedValue(
      jsonResponse(200, { conversations: [] }),
    );
    await listConversations(8, 4);
    expect(global.fetch).toHaveBeenCalledWith(
      `${BASE}/conversations?limit=8&offset=4`,
    );
  });

  it("getConversation returns the detail with messages", async () => {
    (global.fetch as any).mockResolvedValue(
      jsonResponse(200, {
        id: "c1",
        title: "T",
        context_mode: "documents",
        messages: [],
      }),
    );
    const detail = await getConversation("c1");
    expect(global.fetch).toHaveBeenCalledWith(`${BASE}/conversations/c1`);
    expect(detail.context_mode).toBe("documents");
  });

  it("getConversation throws ApiError on 404", async () => {
    (global.fetch as any).mockResolvedValue(jsonResponse(404, { detail: "nf" }));
    await expect(getConversation("missing")).rejects.toMatchObject({
      status: 404,
    });
  });

  it("updateConversation PATCHes the context mode", async () => {
    (global.fetch as any).mockResolvedValue(
      jsonResponse(200, { id: "c1", context_mode: "documents" }),
    );
    const result = await updateConversation("c1", "documents");
    expect(global.fetch).toHaveBeenCalledWith(`${BASE}/conversations/c1`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ context_mode: "documents" }),
    });
    expect(result.context_mode).toBe("documents");
  });

  it("deleteConversation tolerates 404 but throws other errors", async () => {
    (global.fetch as any)
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(jsonResponse(500, { detail: "boom" }));

    await expect(deleteConversation("gone")).resolves.toBeUndefined();
    await expect(deleteConversation("c1")).rejects.toMatchObject({ status: 500 });
  });

  it("sendMessage POSTs the content and returns the assistant reply", async () => {
    (global.fetch as any).mockResolvedValue(
      jsonResponse(200, {
        id: 1,
        conversation_id: "c1",
        role: "assistant",
        content: "reply [C1]",
        citations: [
          {
            citation_key: "C1",
            document_id: "doc-1",
            document_name: "d.pdf",
            page_number: 3,
            excerpt: "x",
            score: 0.9,
          },
        ],
      }),
    );
    const reply = await sendMessage("c1", "question");
    expect(global.fetch).toHaveBeenCalledWith(
      `${BASE}/conversations/c1/messages`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: "question" }),
      },
    );
    expect(reply.role).toBe("assistant");
    expect(reply.citations[0].citation_key).toBe("C1");
  });

  it("streamMessage parses SSE frames and emits typed chunks", async () => {
    const frames = [
      'event: start\ndata: {"user_message_id": 1}\n\n',
      'event: delta\ndata: {"text": "Hel"}\n\n',
      'event: delta\ndata: {"text": "lo"}\n\n',
      'event: done\ndata: {"id": 2, "role": "assistant", "content": "Hello"}\n\n',
    ].join("");
    // Split across chunk boundaries (3 chars) to exercise the buffer logic
    // without the es2018-only `s` regex flag.
    const rawChunks: string[] = [];
    for (let i = 0; i < frames.length; i += 3) {
      rawChunks.push(frames.slice(i, i + 3));
    }

    const encoder = new TextEncoder();
    let index = 0;
    (global.fetch as any).mockResolvedValue({
      ok: true,
      body: {
        getReader: () => ({
          read: async () => {
            if (index < rawChunks.length) {
              const chunk = encoder.encode(rawChunks[index]);
              index += 1;
              return { done: false, value: chunk };
            }
            return { done: true, value: undefined };
          },
        }),
      },
    });

    const { streamMessage } = await import("@/lib/api/chat");
    const events: Array<{ event: string; data: any }> = [];
    const handle = streamMessage("c1", "hi", (chunk) => events.push(chunk));
    await vi.waitFor(() => expect(events).toHaveLength(4));

    expect(events.map((e) => e.event)).toEqual([
      "start",
      "delta",
      "delta",
      "done",
    ]);
    expect(events[1].data.text).toBe("Hel");
    expect(events[3].data.content).toBe("Hello");
    handle.cancel();
  });

  it("streamMessage emits an error chunk on non-2xx responses", async () => {
    (global.fetch as any).mockResolvedValue({ ok: false, status: 500 });

    const { streamMessage } = await import("@/lib/api/chat");
    const events: Array<{ event: string; data: any }> = [];
    streamMessage("c1", "hi", (chunk) => events.push(chunk));
    await vi.waitFor(() => expect(events).toHaveLength(1));
    expect(events[0]).toMatchObject({
      event: "error",
      data: { code: "http_error" },
    });
  });
});