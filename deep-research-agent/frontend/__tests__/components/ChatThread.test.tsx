import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import ChatThread, {
  renderContentWithCitations,
} from "@/components/chat/ChatThread";
import type { ChatCitation, ChatMessage } from "@/lib/types/chat";

const citation: ChatCitation = {
  citation_key: "C1",
  document_id: "doc-1",
  document_name: "Nevada lithium report.pdf",
  page_number: 3,
  excerpt: "Nevada hosts roughly 1% of the world's lithium reserves.",
  score: 0.81,
};

function userMessage(content: string): ChatMessage {
  return {
    id: 1,
    conversation_id: "c1",
    role: "user",
    content,
    model: null,
    provider: null,
    prompt_tokens: null,
    completion_tokens: null,
    citations: [],
    created_at: "2026-01-01T00:00:00Z",
  };
}

function assistantMessage(content: string, citations: ChatCitation[]): ChatMessage {
  return {
    id: 2,
    conversation_id: "c1",
    role: "assistant",
    content,
    model: "gpt-test",
    provider: "openai",
    prompt_tokens: 10,
    completion_tokens: 5,
    citations,
    created_at: "2026-01-01T00:00:01Z",
  };
}

describe("renderContentWithCitations", () => {
  it("splits markers into cite parts bound to their citation", () => {
    const parts = renderContentWithCitations("A fact [C1] plus text.", [citation]);
    expect(parts).toHaveLength(3);
    expect(parts[0]).toMatchObject({ kind: "text", text: "A fact " });
    expect(parts[1]).toMatchObject({ kind: "cite", text: "[C1]" });
    expect(parts[1].citation?.document_id).toBe("doc-1");
    expect(parts[2].text).toBe(" plus text.");
  });

  it("maps unknown markers to cite parts without a citation", () => {
    const parts = renderContentWithCitations("x [C9] y", [citation]);
    expect(parts[1].citation).toBeUndefined();
  });

  it("returns a single text part when no markers exist", () => {
    const parts = renderContentWithCitations("plain answer", [citation]);
    expect(parts).toEqual([{ kind: "text", text: "plain answer" }]);
  });
});

describe("ChatThread", () => {
  it("renders an empty state for no messages", () => {
    render(<ChatThread messages={[]} />);
    expect(screen.getByTestId("chat-empty")).toBeInTheDocument();
  });

  it("renders user and assistant bubbles", () => {
    render(
      <ChatThread
        messages={[
          userMessage("What is lithium used for?"),
          assistantMessage("Batteries, mostly.", []),
        ]}
      />,
    );
    expect(screen.getByTestId("chat-message-user")).toHaveTextContent(
      "What is lithium used for?",
    );
    expect(screen.getByTestId("chat-message-assistant")).toHaveTextContent(
      "Batteries, mostly.",
    );
  });

  it("renders citation chips that expand into source detail", () => {
    render(
      <ChatThread
        messages={[
          userMessage("q"),
          assistantMessage("Nevada leads [C1].", [citation]),
        ]}
      />,
    );
    const chip = screen.getByTestId("cite-chip-C1");
    expect(chip).toHaveTextContent("[C1]");
    expect(screen.queryByTestId("citation-detail")).not.toBeInTheDocument();

    fireEvent.click(chip);
    const detail = screen.getByTestId("citation-detail");
    expect(detail).toHaveTextContent("Nevada lithium report.pdf");
    expect(detail).toHaveTextContent("Page 3");
    expect(detail).toHaveTextContent(
      "Nevada hosts roughly 1% of the world's lithium reserves.",
    );

    // Toggle off again.
    fireEvent.click(chip);
    expect(screen.queryByTestId("citation-detail")).not.toBeInTheDocument();
  });

  it("disables chips for unresolved citations", () => {
    render(
      <ChatThread
        messages={[userMessage("q"), assistantMessage("Invented [C9].", [citation])]}
      />,
    );
    expect(screen.getByTestId("cite-chip-C9")).toBeDisabled();
  });

  it("shows a source count on cited replies", () => {
    render(
      <ChatThread
        messages={[userMessage("q"), assistantMessage("With [C1].", [citation])]}
      />,
    );
    expect(screen.getByTestId("citation-count")).toHaveTextContent("1 source cited");
  });
});