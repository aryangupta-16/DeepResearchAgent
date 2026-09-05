"""Prompt templates for the planner agent."""

PLANNER_SYSTEM_PROMPT = (
    "You are a research planner. Given a research topic, decompose it into a set of "
    "discrete, focused research tasks. You only plan; you never research."
)

_PLAN_JSON_SHAPE = (
    '{"objective": "one-line objective", '
    '"tasks": [{"description": "task description", "notes": "optional note"}]}'
)


def build_planner_prompt(
    topic: str,
    *,
    available_documents: list[str] | None = None,
    user_context: list[str] | None = None,
) -> str:
    """Build the planner task prompt for a given topic.

    ``available_documents`` carries only *metadata* (filenames) for uploaded
    documents — never their content. It lets the planner shape tasks that can
    exploit document evidence without inflating the prompt.

    ``user_context`` carries long-term memory lines (Phase 9). They are
    personalization context ONLY — never evidence, never citable.
    """
    document_block = ""
    if available_documents:
        listed = "\n".join(f"- {name}" for name in available_documents)
        document_block = (
            "\n\nDocuments uploaded by the user (may be consulted as evidence):\n"
            f"{listed}\n"
            "If the topic benefits from these documents, include at least one task "
            "that analyzes details from them (you do not need to name file formats)."
        )

    memory_block = ""
    if user_context:
        lines = "\n".join(f"- {line}" for line in user_context)
        memory_block = (
            "\n\nUSER CONTEXT / LONG-TERM MEMORY (background personalization "
            "only — NOT evidence, NOT citable, do not treat as facts):\n"
            f"{lines}"
        )

    return (
        f'Given the research query: "{topic}"\n'
        f"{document_block}{memory_block}\n\n"
        "Return a JSON object with this exact shape and nothing else:\n"
        f"{_PLAN_JSON_SHAPE}\n"
        "Use 3 to 6 tasks that together cover the topic."
    )