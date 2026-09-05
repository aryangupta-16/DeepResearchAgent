import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const { mockCreateResearch, mockCreateConversation, mockSendMessage } =
  vi.hoisted(() => ({
    mockCreateResearch: vi.fn(),
    mockCreateConversation: vi.fn(),
    mockSendMessage: vi.fn(),
  }));

const mockPush = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
}));

vi.mock("@/lib/api/research", () => ({
  createResearch: mockCreateResearch,
}));

vi.mock("@/lib/api/chat", () => ({
  createConversation: mockCreateConversation,
  sendMessage: mockSendMessage,
}));

vi.mock("@/lib/api/documents", () => ({
  listDocuments: vi.fn().mockResolvedValue({ documents: [] }),
}));

import HomePage from "@/app/page";

describe("HomePage composer modes", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("defaults to the deep-research composer", () => {
    render(<HomePage />);
    expect(screen.getByTestId("research-form")).toBeInTheDocument();
    expect(screen.queryByTestId("quick-composer")).not.toBeInTheDocument();
  });

  it("switches to the quick-answer composer on toggle", () => {
    render(<HomePage />);
    fireEvent.click(screen.getByTestId("mode-quick"));
    expect(screen.getByTestId("quick-composer")).toBeInTheDocument();
    expect(screen.queryByTestId("research-form")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("mode-research"));
    expect(screen.getByTestId("research-form")).toBeInTheDocument();
  });

  it("quick submit creates a conversation, sends the turn, and navigates", async () => {
    mockCreateConversation.mockResolvedValue({ id: "conv-9" });
    mockSendMessage.mockResolvedValue({ id: 1 });

    render(<HomePage />);
    fireEvent.click(screen.getByTestId("mode-quick"));
    fireEvent.change(screen.getByTestId("quick-query-input"), {
      target: { value: "What is RAG?" },
    });
    fireEvent.click(screen.getByTestId("quick-send"));

    await waitFor(() =>
      expect(mockCreateConversation).toHaveBeenCalledWith("What is RAG?"),
    );
    await waitFor(() =>
      expect(mockSendMessage).toHaveBeenCalledWith("conv-9", "What is RAG?"),
    );
    await waitFor(() => expect(mockPush).toHaveBeenCalledWith("/chat/conv-9"));
    // Quick answers must never create a research job.
    expect(mockCreateResearch).not.toHaveBeenCalled();
  });

  it("shows an error and stays put when the quick flow fails", async () => {
    mockCreateConversation.mockRejectedValue({
      name: "ApiError",
      status: 503,
      message: "Chat backend unreachable",
    });
    render(<HomePage />);
    fireEvent.click(screen.getByTestId("mode-quick"));
    fireEvent.change(screen.getByTestId("quick-query-input"), {
      target: { value: "Hello" },
    });
    fireEvent.click(screen.getByTestId("quick-send"));

    await waitFor(() => screen.getByTestId("quick-error"));
    expect(screen.getByTestId("quick-error")).toHaveTextContent(
      "Chat backend unreachable",
    );
    expect(mockPush).not.toHaveBeenCalled();
  });
});