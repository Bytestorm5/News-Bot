from __future__ import annotations

import datetime
import json
import os
import time
import uuid
from typing import List, Dict, Optional, Tuple

import html2text
import openai
import requests
from dotenv import load_dotenv
from duckduckgo_search import DDGS
from duckduckgo_search.exceptions import (
    ConversationLimitException,
    DuckDuckGoSearchException,
    RatelimitException,
    TimeoutException,
)

# ---------------------------------------------------------------------------
#  ENV & GLOBAL CLIENT SETUP
# ---------------------------------------------------------------------------

load_dotenv()  # Loads variables from .env if present.
openai.api_key = os.getenv("OPENAI_API_KEY")

html2md = html2text.HTML2Text()
html2md.ignore_links = False  # Keep hyperlinks

# Ensure chats directory exists
os.makedirs("chats", exist_ok=True)

# ---------------------------------------------------------------------------
#  TOOL IMPLEMENTATIONS
# ---------------------------------------------------------------------------

DDGS_RATE_LIMIT_SLEEP = 60
def search_web(query: str, num_results: int = 5) -> List[Dict[str, str]]:
    """Run a DuckDuckGo web search and return the top results.

    Each result dict contains: title, link, snippet.
    If rate limit is encountered, waits before retrying."""
    results: List[Dict[str, str]] = []
    with DDGS() as ddgs:
        while True:
            try:
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
                break  # successful fetch, exit retry loop
            except DuckDuckGoSearchException as e:
                # Hit rate limit: wait and retry
                print(f"Rate limit hit: {e}. Sleeping for {DDGS_RATE_LIMIT_SLEEP}s...")
                time.sleep(DDGS_RATE_LIMIT_SLEEP)
                continue
    return results[:num_results]


def open_url(url: str, max_chars: int = 4000) -> Dict[str, str]:
    """Download a web page and return its body converted to Markdown.

    The Markdown is truncated to *max_chars* characters to keep replies short.
    """
    resp = None
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        if resp is not None and hasattr(resp, 'status_code') and resp.status_code != 200:
            return {"url": url, "markdown": f"Error {resp.status_code}: {resp.reason}"}
        return {"url": url, "markdown": f"Error: {str(e)}"}
    md = html2md.handle(resp.text)
    if len(md) > max_chars:
        md = md[:max_chars] + " …"
    return {"url": url, "markdown": md}

# ---------------------------------------------------------------------------
#  OPENAI FUNCTION-CALLING SCHEMAS (TOOLS)
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
                    "num_results": {"type": "integer", "description": "how many results (1-10)", "default": 5},
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
                    "max_chars": {"type": "integer", "description": "truncate Markdown to this many characters", "default": 4000},
                },
                "required": ["url"],
            },
        },
    },
]
FUNC_REGISTRY = {"search_web": search_web, "open_url": open_url}

# ---------------------------------------------------------------------------
#  SYSTEM PROMPT
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are an expert news analyst. Reason step-by-step. "
    "Use the provided tools whenever helpful. Make sure to pull recent & up-to-date information. "
    "While thinking, consider the reliability and biases of the sources, and aim to capture a diverse set of opinions."
    f" The current date is {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}."
)

# ---------------------------------------------------------------------------
#  CHAT FUNCTION WITH THREAD MANAGEMENT
# ---------------------------------------------------------------------------

def chat(
    user_input: str,
    thread_id: Optional[str] = None,
    save: bool = True,
    use_tools: bool = True,
    model: str = "o4-mini"
) -> Tuple[Dict, str]:
    """
    Send a message to the chat model, optionally in a specific thread.

    Returns a tuple of (response_message, thread_id).

    :param user_input: The user's message.
    :param thread_id: Identifier for the conversation thread. If None, a new thread is created.
    :param save: If True, save the updated chat history to a file under chats/.
    :param use_tools: If False, disable tool use for this call.
    :param model: Model name for the OpenAI API.
    """
    # Determine thread and load history
    if thread_id is None:
        # New thread
        date_prefix = datetime.datetime.now().strftime("%Y%m%d")
        # Base thread id
        base_id = f"{date_prefix}_{uuid.uuid4().hex}"
        thread_id = base_id
        file_path = os.path.join("chats", f"{thread_id}.json")
        counter = 1
        # Avoid collisions by appending an incrementing suffix
        while os.path.exists(file_path):
            thread_id = f"{base_id}_{counter}"
            file_path = os.path.join("chats", f"{thread_id}.json")
            counter += 1
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    else:
        # Existing thread: load from file if available
        file_path = os.path.join("chats", f"{thread_id}.json")
        if os.path.isfile(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                messages = json.load(f)
        else:
            messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Add user message
    messages.append({"role": "user", "content": user_input})

    # Prepare API call arguments
    api_args = {"model": model, "messages": messages}
    if use_tools:
        api_args.update({"tools": tools, "tool_choice": "auto"})
    else:
        api_args.update({"tool_choice": "none"})

    # Call model, handling tool calls
    while True:
        response = openai.chat.completions.create(**api_args).choices[0].message

        # Handle tool calls if allowed
        if use_tools and getattr(response, "tool_calls", None):
            # Register the assistant's tool request
            messages.append(
                {"role": "assistant", "content": None, "tool_calls": [
                    {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in response.tool_calls
                ]}
            )
            print(f"Tool calls: {response.tool_calls}")
            # Execute each tool and add its output
            for tc in response.tool_calls:
                func_name = tc.function.name
                print("-", func_name)
                args = json.loads(tc.function.arguments or "{}")
                result = FUNC_REGISTRY[func_name](**args)
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result, ensure_ascii=False)})
            # Next iteration to let model consume tool outputs
            api_args["messages"] = messages
            continue

        # Final assistant response
        messages.append(response.to_dict())
        break

    # Save history if requested
    if save:
        file_path = os.path.join("chats", f"{thread_id}.json")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(messages, f, ensure_ascii=False, indent=2)

    return response, thread_id

# ---------------------------------------------------------------------------
#  SAMPLE EXECUTION
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Example: start a new thread and save history
    resp, tid = chat("What is today's news?", save=True, use_tools=True)
    print(f"Thread {tid} response:\n", resp.content)
