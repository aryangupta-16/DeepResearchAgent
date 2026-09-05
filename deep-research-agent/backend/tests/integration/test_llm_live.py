"""Optional live LLM test.

Requires ``RUN_LIVE_LLM_TESTS=true`` and a valid ``LLM_PROVIDER``/API key in
settings. Skipped during normal pytest execution so the paid API is never called
by default.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.live

_RUN_LIVE = os.getenv("RUN_LIVE_LLM_TESTS") == "true"
_SKIP_REASON = "Set RUN_LIVE_LLM_TESTS=true to run the live LLM test"


@pytest.mark.skipif(not _RUN_LIVE, reason=_SKIP_REASON)
async def test_live_openai_chat() -> None:
    """Hit the real configured provider end-to-end via the chat service."""
    from app.workflows.chat.service import ChatService

    service = ChatService()
    response = await service.reply("Reply with exactly the two characters: OK")

    assert response.message.strip()
    assert response.model
    assert response.provider