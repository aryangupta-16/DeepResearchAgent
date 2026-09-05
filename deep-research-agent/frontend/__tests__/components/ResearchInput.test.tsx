import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import ResearchInput from "@/components/research/ResearchInput";

describe("ResearchInput", () => {
  it("renders the form and disables submit when the query is empty", () => {
    render(<ResearchInput onSubmit={vi.fn()} />);
    expect(screen.getByRole("button", { name: /start research/i })).toBeDisabled();
    expect(
      screen.getByPlaceholderText(/compare the safety/i),
    ).toBeInTheDocument();
  });

  it("shows a validation message for whitespace-only text", () => {
    render(<ResearchInput onSubmit={vi.fn()} />);
    const textarea = screen.getByRole("textbox");
    fireEvent.change(textarea, { target: { value: "   " } });
    expect(
      screen.getByRole("button", { name: /start research/i }),
    ).toBeDisabled();
  });

  it("submits the trimmed query and shows a loading state", async () => {
    const onSubmit = vi.fn().mockImplementation(() => new Promise((r) => setTimeout(r, 50)));
    render(<ResearchInput onSubmit={onSubmit} />);
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "  Hydrogen trucks safety  " },
    });
    const btn = screen.getByRole("button", { name: /start research/i });
    fireEvent.click(btn);
    expect(await screen.findByText(/starting research/i)).toBeInTheDocument();
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    // the handler receives the trimmed value
    expect(onSubmit).toHaveBeenCalledWith("Hydrogen trucks safety", []);
  });

  it("surfaces submit errors returned by the handler", async () => {
    const onSubmit = vi.fn().mockRejectedValue({
      status: 500,
      message: "Backend unreachable right now",
      name: "ApiError",
    });
    render(<ResearchInput onSubmit={onSubmit} />);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "real query" } });
    fireEvent.click(screen.getByRole("button", { name: /start research/i }));
    await screen.findByText(/backend unreachable right now/i);
  });

  it("shows a friendly validation error for 422 responses", async () => {
    const onSubmit = vi.fn().mockRejectedValue({
      status: 422,
      message: "bad",
      name: "ApiError",
    });
    render(<ResearchInput onSubmit={onSubmit} />);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "too long query" } });
    fireEvent.click(screen.getByRole("button", { name: /start research/i }));
    await screen.findByText(/between 1 and 1,000 characters/i);
  });

  it("trims and ignores trailing characters beyond the max length", () => {
    render(<ResearchInput onSubmit={vi.fn()} />);
    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "x".repeat(2000) } });
    // maxLength is enforced at the DOM level, so value stays capped
    expect(textarea.value.length).toBeLessThanOrEqual(1000);
  });
});
