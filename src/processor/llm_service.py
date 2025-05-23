import json
import openai
from ..config import settings

openai.api_key = settings.OPENAI_KEY

async def analyze_item(title: str, content: str) -> dict:
    """
    Use OpenAI to generate summary, tags, sourceBias, and interpretations for a news item.
    Returns a dict with keys: summary, tags, sourceBias, interpretations.
    """
    system_prompt = (
        "You are a news-processing assistant. "
        "Given a title and content, produce a JSON object containing:\n"
        "- summary: a concise abstract with citations (string),\n"
        "- tags: list of strings categorizing the topic,\n"
        "- sourceBias: {sources: [{name, bias}], blurb: string},\n"
        "- interpretations: {leftFrame: string, rightFrame: string}."
        "Respond with pure JSON."
    )
    user_prompt = (
        f"Title: {title}\nContent: {content}\n"
        "Return the JSON object as specified."
    )
    # Call the OpenAI ChatCompletion API
    response = await openai.ChatCompletion.acreate(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
    )
    text = response.choices[0].message.content
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Attempt to extract JSON substring
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1:
            return json.loads(text[start:end+1])
        raise