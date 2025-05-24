"""
demo_tools_chat_duckduckgo.py

Call GPT‑4 / GPT‑4o (or any OpenAI chat model) with two reasoning‑time tools:
  1) search_web            – general DuckDuckGo search
  2) open_url_as_markdown  – fetch & return page as Markdown

The assistant can decide when to invoke these tools while thinking.
No Google API, no MCP, no headless browser – everything is plain Python HTTP calls.
"""

from __future__ import annotations

import json
import os
from typing import List, Dict

import html2text
import openai
import requests
from dotenv import load_dotenv
from duckduckgo_search import DDGS

# ---------------------------------------------------------------------------
#  ENV & GLOBAL CLIENT SETUP
# ---------------------------------------------------------------------------

load_dotenv()  # Loads variables from .env if present.
openai.api_key = os.getenv("OPENAI_API_KEY")

html2md = html2text.HTML2Text()
html2md.ignore_links = False  # Keep hyperlinks

# ---------------------------------------------------------------------------
#  TOOL IMPLEMENTATIONS
# ---------------------------------------------------------------------------

def search_web(query: str, num_results: int = 5) -> List[Dict[str, str]]:
    """Run a DuckDuckGo web search and return the top results.

    Each result dict contains: title, link, snippet.
    """
    results: List[Dict[str, str]] = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=num_results):
            results.append(
                {
                    "title": r.get("title", ""),
                    "link": r.get("href", ""),
                    "snippet": r.get("body", ""),
                }
            )
            if len(results) >= num_results:
                break
    return results


def open_url(url: str, max_chars: int = 4000) -> Dict[str, str]:
    """Download a web page and return its body converted to Markdown.

    The Markdown is truncated to *max_chars* characters to keep replies short.
    """
    resp = requests.get(url, timeout=15)
    if resp.status_code != 200:
        return {"url": url, "markdown": f"Error {resp.status_code}: {resp.reason}"}
    md = html2md.handle(resp.text)
    if len(md) > max_chars:
        md = md[: max_chars] + " …"
    return {"url": url, "markdown": md}


# ---------------------------------------------------------------------------
#  OPENAI FUNCTION‑CALLING SCHEMAS (a.k.a. "tools")
# ---------------------------------------------------------------------------

tools = [
    {
        "type": "function",
        "name": "search_web",
        "function": {
            "name": "search_web",
            "description": "Run a web search and get top results.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "search phrase"},
                    "num_results": {
                        "type": "integer",
                        "description": "how many results (1‑10)",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "name": "open_url",
        "function": {
            "name": "open_url",
            "description": "Download a web page and return its body converted to Markdown.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "max_chars": {
                        "type": "integer",
                        "description": "truncate Markdown to this many characters",
                        "default": 4000,
                    },
                },
                "required": ["url"],
            },
        },
    },
]
# Map from function name to the actual Python callable.
FUNC_REGISTRY = {
    "search_web": search_web,
    "open_url": open_url,
}


# ---------------------------------------------------------------------------
#  CONVERSATION LOOP
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are an expert research assistant. Reason step‑by‑step. "
    "Use the provided tools whenever helpful."
)

messages: List[Dict[str, str]] = [
    {"role": "system", "content": SYSTEM_PROMPT}
]

def chat(user_input: str, model: str = "o4-mini") -> str:
    messages.append({"role": "user", "content": user_input})

    while True:
        response = openai.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=1,
        ).choices[0].message

        # ------------------------------------------------------------------
        # 1) Did the model ask to call one or more tools?
        # ------------------------------------------------------------------
        if response.tool_calls:
            # Record the assistant’s tool-request turn exactly once
            messages.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in response.tool_calls
                    ],
                }
            )

            # Run every requested tool
            for tc in response.tool_calls:
                func_name = tc.function.name
                args = json.loads(tc.function.arguments or "{}")
                result = FUNC_REGISTRY[func_name](**args)

                # Feed the result back with the correct tool_call_id
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                print(tc.id, func_name, args, result)

            # Loop so the model can see the new tool messages
            continue

        # ------------------------------------------------------------------
        # 2) Normal answer – we’re done
        # ------------------------------------------------------------------
        messages.append(response)
        return response.content

# ---------------------------------------------------------------------------
#  SAMPLE EXECUTION (python demo_tools_chat_duckduckgo.py "query ...")
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    # if len(sys.argv) < 2:
    #     print("Usage: python demo_tools_chat_duckduckgo.py \"Your question here\"")
    #     sys.exit(0)
    
    
    answer = chat("What is today's news?") #chat(" ".join(sys.argv[1:]))
    print("\n===== ANSWER =====\n")
    print(answer)
