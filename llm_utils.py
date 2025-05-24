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


def open_url_as_markdown(url: str, max_chars: int = 4000) -> Dict[str, str]:
    """Download a web page and return its body converted to Markdown.

    The Markdown is truncated to *max_chars* characters to keep replies short.
    """
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
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
        "function": {
            "name": "open_url_as_markdown",
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
    "open_url_as_markdown": open_url_as_markdown,
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

def chat(user_input: str, model: str = "gpt-4o-mini") -> str:
    """Send *user_input* to the model, handling function calls until we get an answer."""

    messages.append({"role": "user", "content": user_input})

    while True:
        # response = openai.ChatCompletion.create(
        #     model=model,
        #     messages=messages,
        #     tools=tools,
        #     temperature=0.3,
        # ).choices[0].message
        
        response = openai.chat.completions.create(
            model=model,
            messages=messages,
            functions=tools,
            function_call="auto",
            temperature=0.3,
        ).choices[0].message

        # If the model decides to use a tool, execute it and let the model continue.
        if response.get("tool_calls"):
            for call in response.tool_calls:
                func_name = call.function.name
                args = json.loads(call.function.arguments or "{}")
                result = FUNC_REGISTRY[func_name](**args)

                # Feed the tool result back to the conversation
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "name": func_name,
                        "content": json.dumps(result),
                    }
                )
            # Continue the loop – model will see the tool outputs next iteration
            continue

        # Otherwise we have the final model answer.
        messages.append(response)
        return response.content


# ---------------------------------------------------------------------------
#  SAMPLE EXECUTION (python demo_tools_chat_duckduckgo.py "query ...")
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python demo_tools_chat_duckduckgo.py \"Your question here\"")
        sys.exit(0)

    answer = chat(" ".join(sys.argv[1:]))
    print("\n===== ANSWER =====\n")
    print(answer)
