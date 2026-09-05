"""Mock provider environment for deterministic end-to-end tests.

Serves three concerns in one process:

1. ``/v1/chat/completions`` — an OpenAI-compatible chat endpoint that routes on
   stable prompt markers and returns JSON that validates against our agent schemas.
2. ``/mock_search`` — a Serper-compatible search endpoint returning organic
   results that point at local demo pages.
3. ``/demo/page/{n}`` — small HTML pages that the real FetchTool can download.

No real external API (LLM or search) is touched.
"""

from __future__ import annotations

import json
import re

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

app = FastAPI()

PAGE_TEMPLATE = """<!doctype html>
<html><head><title>{title}</title></head><body>
<h1>{title}</h1>
<p>{sentence}</p>
<p>This page is part of a deterministic research sandbox.</p>
<script>document.write("ignored");</script>
<style>.noise {{ color: red; }}</style>
</body></html>
"""

# Every demo page contains this sentence so quotes validated against the fetched
# content are guaranteed to match verbatim.
SHARED_SENTENCE = "Humanoid robots are advancing rapidly across industry."

PAGES = {
    1: {"title": "Humanoid Robotics Market Overview", "sentence": SHARED_SENTENCE},
    2: {"title": "Technical Advances in Humanoid Robots", "sentence": SHARED_SENTENCE},
    3: {"title": "Humanoid Applications Across Industry", "sentence": SHARED_SENTENCE},
}


def _chat_response(content: str, model: str) -> JSONResponse:
    return JSONResponse(
        {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
            },
        }
    )


PLANNER_RESPONSE = {
    "objective": "Investigate the current state of humanoid robotics development",
    "tasks": [
        {
            "description": "Major humanoid robot manufacturers and their products",
            "notes": "Focus on commercial platforms",
        },
        {
            "description": "Key technical capabilities and limitations",
            "notes": "Locomotion, manipulation, battery life",
        },
    ],
}


def _researcher_route(user: str) -> str:
    if "generate_search_queries" in user:
        return json.dumps({"queries": ["humanoid robotics web sources"]}, indent=2)
    if "select_relevant_search_results" in user:
        return json.dumps({"indices": [0, 1]}, indent=2)
    if "extract_evidence" in user:
        return json.dumps(
            {
                "evidence": [
                    {
                        "claim": "Humanoid robotics development is advancing quickly.",
                        "excerpt": SHARED_SENTENCE,
                        "locator": "paragraph 1",
                    },
                    {
                        "claim": "Industry sources track commercial humanoid progress.",
                        "excerpt": SHARED_SENTENCE,
                        "locator": "paragraph 1",
                    },
                ]
            },
            indent=2,
        )
    if "summarize_findings" in user:
        return json.dumps(
            {"summary": "Humanoid robotics is progressing quickly across sectors."},
            indent=2,
        )
    return json.dumps({"summary": "No findings."}, indent=2)


_SOURCE_LINE = re.compile(r"^- ([0-9a-f]{8}-[0-9a-f-]{27}): .*$", re.MULTILINE)


def _synthesizer_response(user: str) -> str:
    """Return a citation-aware report citing source ids from the prompt."""
    source_ids = _SOURCE_LINE.findall(user)
    sections = [
        {
            "heading": "State of the Field",
            "content": "Humanoid robotics is advancing rapidly across multiple fronts.",
            "citation_source_ids": source_ids[:1],
        },
        {
            "heading": "Industry Momentum",
            "content": "Commercial and research efforts continue to expand.",
            "citation_source_ids": source_ids[1:2] if len(source_ids) > 1 else [],
        },
    ]
    payload = {
        "title": "Current State of Humanoid Robotics Development",
        "summary": "Humanoid robotics is entering a period of rapid progress.",
        "sections": sections,
        "conclusion": "Progress is accelerating across the field.",
    }
    return json.dumps(payload, indent=2)


def _route(messages: list[dict]) -> str:
    system, user = "", ""
    for msg in messages:
        role = msg.get("role")
        if role == "system" and not system:
            system = msg.get("content", "")
        if role == "user" and not user:
            user = msg.get("content", "")
    lowered = system.lower()
    if "decompose" in lowered:
        return json.dumps(PLANNER_RESPONSE, indent=2)
    if "research analyst" in lowered or "report writer" in lowered:
        return _synthesizer_response(user)
    return _researcher_route(user)


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> JSONResponse:
    payload = await request.json()
    messages = payload.get("messages", [])
    model = payload.get("model", "gpt-4o-mini")
    return _chat_response(_route(messages), model)


@app.post("/mock_search")
async def mock_search(request: Request) -> JSONResponse:
    """Serper-compatible response: three organic results to local demo pages."""
    base = str(request.base_url).rstrip("/")
    return JSONResponse(
        {
            "searchParameters": {"q": "humanoid robots"},
            "organic": [
                {
                    "title": "Humanoid Robotics Market Overview",
                    "link": f"{base}/demo/page/1",
                    "snippet": "Humanoid robots are advancing rapidly.",
                },
                {
                    "title": "Technical Advances in Humanoid Robots",
                    "link": f"{base}/demo/page/2",
                    "snippet": "Commercial humanoid platforms are maturing.",
                },
                {
                    "title": "Humanoid Applications Across Industry",
                    "link": f"{base}/demo/page/3",
                    "snippet": "Humanoids are entering real deployments.",
                },
            ],
        }
    )


@app.get("/demo/page/{page_id}")
async def demo_page(request: Request, page_id: int):
    page = PAGES.get(page_id)
    if page is None:
        return JSONResponse({"detail": "not found"}, status_code=404)
    html = PAGE_TEMPLATE.format(title=page["title"], sentence=page["sentence"])
    return PlainTextResponse(html, media_type="text/html")