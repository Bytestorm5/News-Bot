"""
news_firehose_responses_refactor.py

Refactored to use the **OpenAI Responses API** with local (cost‑free) DuckDuckGo search
and Markdown‑scraping helpers. The new `chat()` returns `(assistant_text, response_id)`
where `response_id` is the **Responses API ID** you must pass as
`previous_response_id` on the next turn.
"""
from __future__ import annotations

import datetime
import json
import os
import time
from typing import List, Dict, Optional, Tuple

import html2text
import openai
import requests
from dotenv import load_dotenv
from duckduckgo_search import DDGS
from duckduckgo_search.exceptions import (
    DuckDuckGoSearchException,
)
from dataclasses import dataclass
import db

# ---------------------------------------------------------------------------
#  ENV & GLOBAL CLIENT SETUP
# ---------------------------------------------------------------------------
load_dotenv()  # Loads variables from .env if present.
openai.api_key = os.getenv("OPENAI_API_KEY")

# ---------------------------------------------------------------------------
#  UTILITIES
# ---------------------------------------------------------------------------
html2md = html2text.HTML2Text()
html2md.ignore_links = False  # Keep hyperlinks

DDGS_RATE_LIMIT_SLEEP = 60  # seconds


def _rate_limited_ddg(query: str, max_results: int) -> List[Dict[str, str]]:
    """Return `max_results` DDG results, retrying politely if rate‑limited."""
    with DDGS() as ddgs:
        while True:
            try:
                results = []
                for r in ddgs.text(query, max_results=max_results):
                    results.append({
                        "title": r.get("title", ""),
                        "link": r.get("href", ""),
                        "snippet": r.get("body", ""),
                    })
                    if len(results) >= max_results:
                        break
                return results
            except DuckDuckGoSearchException as e:
                print(f"DDG rate‑limit hit → sleeping {DDGS_RATE_LIMIT_SLEEP}s … ({e})")
                time.sleep(DDGS_RATE_LIMIT_SLEEP)


# ---------------------------------------------------------------------------
#  LOCAL FUNCTION TOOLS (search / scrape / scheduling)
# ---------------------------------------------------------------------------


def search_web(query: str, num_results: int = 5) -> List[Dict[str, str]]:
    """Local DuckDuckGo search wrapper used as an OpenAI tool."""
    return _rate_limited_ddg(query, max_results=min(max(num_results, 1), 10))


def open_url(url: str, max_chars: int = 4000) -> Dict[str, str]:
    """Fetch *url* and return a Markdown version (truncated to *max_chars*)."""
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        status = getattr(resp, "status_code", "?") if "resp" in locals() else "?"
        reason = getattr(resp, "reason", "") if "resp" in locals() else ""
        return {"url": url, "markdown": f"Error {status}: {reason or e}"}

    md = html2md.handle(resp.text)
    if len(md) > max_chars:
        md = md[: max_chars] + " …"
    return {"url": url, "markdown": md}


@dataclass
class Followup:
    prompt: str
    timestamp: datetime.datetime

    def to_dict(self):
        return {"prompt": self.prompt, "timestamp": self.timestamp}


def schedule_followup_offset(prompt: str, days: int = 0, weeks: int = 0, months: int = 0) -> Dict:
    """Schedule *prompt* a relative time into the future."""
    try:
        now = datetime.datetime.now()
        followup_date = now + datetime.timedelta(days=days, weeks=weeks) + datetime.timedelta(days=30 * months)
        db.db["follow_ups"].insert_one(Followup(prompt, followup_date).to_dict())
        return {"success": True, "message": f"Scheduled for {followup_date.isoformat()}"}
    except Exception as e:
        return {"success": False, "message": str(e)}


def schedule_followup_at(prompt: str, datetime_str: str) -> Dict:
    """Schedule *prompt* at an explicit ISO‑8601 timestamp."""
    try:
        followup_date = datetime.datetime.fromisoformat(datetime_str)
        db.db["follow_ups"].insert_one(Followup(prompt, followup_date).to_dict())
        return {"success": True, "message": f"Scheduled for {followup_date.isoformat()}"}
    except ValueError:
        return {"success": False, "message": "Invalid ISO‑8601 datetime."}
    except Exception as e:
        return {"success": False, "message": str(e)}

# Map tool names → callables for dispatch
FUNC_REGISTRY = {
    "search_web": search_web,
    "open_url": open_url,
    "schedule_followup_offset": schedule_followup_offset,
    "schedule_followup_at": schedule_followup_at,
}

# ---------------------------------------------------------------------------
#  RESPONSES‑API TOOL SCHEMAS
# ---------------------------------------------------------------------------

tools = [
    {
        "name": "search_web",
        "type": "function",
        "description": "Run a DuckDuckGo search and return top results.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search phrase"},
                "num_results": {
                    "type": "integer",
                    "description": "Number of results (1‑10)",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "open_url",
        "type": "function",
        "description": "Download a web page and return Markdown (truncated).",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "max_chars": {
                    "type": "integer",
                    "description": "Maximum characters of Markdown to return",
                    "default": 4000,
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "schedule_followup_offset",
        "type": "function",
        "description": "Schedule a follow‑up relative to now (days/weeks/months).",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "days": {"type": "integer"},
                "weeks": {"type": "integer"},
                "months": {"type": "integer"},
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "schedule_followup_at",
        "type": "function",
        "description": "Schedule a follow‑up at an explicit ISO‑8601 datetime.",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "datetime_str": {"type": "string", "format": "date-time"},
            },
            "required": ["prompt", "datetime_str"],
        },
    },
]

# ---------------------------------------------------------------------------
#  SYSTEM PROMPT
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = (
    "You are an expert news analyst. Reason step-by-step. "
    "Use the provided tools whenever helpful. Make sure to pull recent & up-to-date information. "
    "While thinking, consider the reliability and biases of the sources, and aim to capture a diverse set of opinions. "
    f"The current date is {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}."
)
# ---------------------------------------------------------------------------
#  CHAT/RESPONSE LOOP
# ---------------------------------------------------------------------------

def _invoke_tools_if_needed(resp):
    """Handle any required_action cycle, returning the final response."""
    while getattr(resp, "requires_action", False):
        required = resp.required_action
        if required.type != "submit_tool_outputs":
            raise RuntimeError(f"Unhandled required_action: {required.type}")

        outputs = []
        for call in required.submit_tool_outputs.tool_calls:
            fn = FUNC_REGISTRY[call.name]
            result = fn(**call.arguments)
            outputs.append({"tool_call_id": call.id, "output": result})

        # Submit tool outputs and get the follow‑up response
        resp = openai.responses.submit_tool_outputs(
            id=resp.id,
            tool_outputs=outputs,
        )
    return resp


def chat(user_input: str, response_id: Optional[str] = None, model: str = "o4-mini") -> Tuple[str, str]:
    """Send *user_input* through the Responses API. Returns (assistant_text, response_id)."""
    resp = openai.responses.create(
        model=model,
        input=user_input,
        tools=tools,
        store=True,  # keep server‑side state
        instructions=SYSTEM_PROMPT,
        previous_response_id=response_id if response_id else None,
        parallel_tool_calls=True,  # allow parallel tool calls
        tool_choice="auto",  # let the model decide which tool to use
        reasoning={"effort": "high"},  # encourage detailed reasoning
    )
    resp = _invoke_tools_if_needed(resp)

    return resp.output_text, resp.id

# ---------------------------------------------------------------------------
#  SAMPLE EXECUTION
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    answer, rid = chat("What are today’s top AI policy headlines?")
    print(answer)
    print(f"(Store next time as previous_response_id={rid})")
