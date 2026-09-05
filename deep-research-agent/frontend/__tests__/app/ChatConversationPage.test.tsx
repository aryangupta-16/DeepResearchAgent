import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const {
  mockGetConversation,
  mockStreamMessage,
  mockUpdateConversation,
  mockCreateConversation,
} = vi.hoisted(() => ({
  mockGetConversation: vi.fn(),
  mockStreamMessage: vi.fn(),
  mockUpdateConversation: vi.fn(),
  mockCreateConversation: vi.fn(),
}));

const mockPush = vi.fn();
const mockReplace = vi.fn();

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "conv-1" }),
  useRouter: () => ({ push: mockPush, replace: mockReplace }),
}));

vi.mock("@/lib/api/chat", () => ({
  getConversation: mockGetConversation,
  streamMessage: mockStreamMessage,
  updateConversation: mockUpdateConversation,
  createConversation: mockCreateConversation,
  listConversations: vi.fn(),
  deleteConversation: vi.fn(),
}));

// The composer lists documents to decide if the context toggle is available.
vi.mock("@/lib/api/documents", () => ({
  listDocuments: vi.fn().mockResolvedValue({
    documents: [
      { id: "d1", filename: "a.pdf", status: "ready" },
    ],
  }),
  documentDownloadUrl: (id: string) => `${id}/download`,
}));

import ChatConversationPage from "@/app/chat/[id]/page";
import type { ChatCitation, ConversationDetail } from "@/lib/types/chat";

const citation: ChatCitation = {
  citation_key: "C1",
  document_id: "doc-1",
  document_name: "Nevada lithium report.pdf",
  page_number: 3,
  excerpt: "Nevada hosts roughly 1% of reserves.",
  score: 0.8,
};

function detail(overrides: Partial<ConversationDetail> = {}): ConversationDetail {
  return {
    id: "conv-1",
    title: "Lithium question",
    context_mode: "none",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    messages: [
      {
        id: 1,
        conversation_id: "conv-1",
        role: "user",
        content: "What about lithium?",
        model: null,
        provider: null,
        prompt_tokens: null,
        completion_tokens: null,
        citations: [],
        created_at: "2026-01-01T00:00:00Z",
      },
      {
        id: 2,
        conversation_id: "conv-1",
        role: "assistant",
        content: "Nevada leads [C1].",
        model: "gpt-test",
        provider: "openai",
        prompt_tokens: 10,
        completion_tokens: 5,
        citations: [citation],
        created_at: "2026-01-01T00:00:01Z",
      },
    ],
    ...overrides,
  };
}

describe("ChatConversationPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetConversation.mockResolvedValue(detail());
    // Default streaming mock: full lifecycle, resolving on `done`.
    mockStreamMessage.mockImplementation(
      (
        _id: string,
        _content: string,
        onEvent: (chunk: {
          event: string;
          data: Record<string, unknown>;
        }) => void,
      ) => {
        void (async () => {
          onEvent({ event: "start", data: { user_message_id: 9 } });
          onEvent({ event: "delta", data: { text: "Streaming " } });
          onEvent({ event: "delta", data: { text: "answer" } });
          onEvent({
            event: "done",
            data: {
              id: 10,
              conversation_id: "conv-1",
              role: "assistant",
              content: "Streaming answer",
              model: "fake",
              provider: "fake",
              prompt_tokens: 3,
              completion_tokens: 4,
              citations: [],
              created_at: "2026-01-01T00:00:02Z",
            },
          });
        })();
        return { cancel: vi.fn() };
      },
    );
    mockUpdateConversation.mockImplementation(
      async (_id: string, mode: string) => ({ id: "conv-1", context_mode: mode }),
    );
  });

  it("renders the conversation thread and composer", async () => {
    render(<ChatConversationPage />);
    await waitFor(() =>
      expect(screen.getByTestId("chat-thread")).toBeInTheDocument(),
    );
    expect(screen.getByText("Lithium question")).toBeInTheDocument();
    expect(screen.getByTestId("chat-message-user")).toHaveTextContent(
      "What about lithium?",
    );
    expect(screen.getByTestId("chat-message-assistant")).toHaveTextContent(
      "Nevada leads",
    );
    expect(screen.getByTestId("cite-chip-C1")).toBeInTheDocument();
    expect(screen.getByTestId("chat-composer")).toBeInTheDocument();
  });

  it("sends a message, streams the reply, and refreshes the thread", async () => {
    render(<ChatConversationPage />);
    await waitFor(() => screen.getByTestId("chat-composer"));

    const input = screen
      .getByRole("textbox")
      .closest("form")!
      .querySelector("textarea") as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: "Follow-up question" } });
    fireEvent.click(screen.getByTestId("send-message"));

    await waitFor(() =>
      expect(mockStreamMessage).toHaveBeenCalledWith(
        "conv-1",
        "Follow-up question",
        expect.any(Function),
      ),
    );
    // The thread refreshes after the stream completes (canonical state).
    await waitFor(() => expect(mockGetConversation).toHaveBeenCalledTimes(2));
  });

  it("shows the streaming bubble while the reply is in flight", async () => {
    // Hold the stream open until we assert the in-flight UI.
    mockStreamMessage.mockImplementation(() => ({ cancel: vi.fn() }));
    render(<ChatConversationPage />);
    await waitFor(() => screen.getByTestId("chat-composer"));

    const input = screen
      .getByRole("textbox")
      .closest("form")!
      .querySelector("textarea") as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: "hello?" } });
    fireEvent.click(screen.getByTestId("send-message"));

    await waitFor(() => screen.getByTestId("chat-streaming-message"));
    expect(screen.getByTestId("chat-streaming-message")).toHaveTextContent("…");
  });

  it("deletes the conversation after confirmation and routes to /chat", async () => {
    const { deleteConversation } = await import("@/lib/api/chat");
    (deleteConversation as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);

    render(<ChatConversationPage />);
    await waitFor(() => screen.getByTestId("delete-conversation"));
    fireEvent.click(screen.getByTestId("delete-conversation"));

    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith("/chat"));
    expect(deleteConversation).toHaveBeenCalledWith("conv-1");
    confirmSpy.mockRestore();
  });

  it("does not delete when the confirmation is dismissed", async () => {
    const { deleteConversation } = await import("@/lib/api/chat");
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);

    render(<ChatConversationPage />);
    await waitFor(() => screen.getByTestId("delete-conversation"));
    fireEvent.click(screen.getByTestId("delete-conversation"));

    expect(deleteConversation).not.toHaveBeenCalled();
    expect(mockReplace).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it("toggles document grounding via the composer", async () => {
    render(<ChatConversationPage />);
    await waitFor(() => screen.getByTestId("chat-composer"));

    const toggle = screen.getByRole("checkbox", {
      name: /answer from uploaded documents/i,
    });
    fireEvent.click(toggle);

    await waitFor(() =>
      expect(mockUpdateConversation).toHaveBeenCalledWith(
        "conv-1",
        "documents",
      ),
    );
  });

  it("shows a not-found view on 404", async () => {
    mockGetConversation.mockRejectedValue({
      name: "ApiError",
      status: 404,
      message: "nf",
    });
    render(<ChatConversationPage />);
    await waitFor(() => screen.getByTestId("chat-not-found"));
  });

  it("starts a new conversation from the header", async () => {
    mockCreateConversation.mockResolvedValue({ id: "conv-2" });
    render(<ChatConversationPage />);
    await waitFor(() => screen.getByTestId("new-conversation"));
    fireEvent.click(screen.getByTestId("new-conversation"));
    await waitFor(() => expect(mockPush).toHaveBeenCalledWith("/chat/conv-2"));
  });
});