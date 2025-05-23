import os
import sys
import openai
import json
from detoxify import Detoxify

from ..config import settings
from ..database import db
from ..utils.ctx_utils import get_context

# Initialize Detoxify model and OpenAI key
detox_model = Detoxify('unbiased')
openai.api_key = settings.OPENAI_KEY

async def moderate_message(message):
    """
    Check message toxicity and decide DELETE or IGNORE.
    """
    # Score toxicity
    scores = detox_model.predict(message.content)
    # Get highest-scoring class
    tox_class, tox_score = max(scores.items(), key=lambda kv: kv[1])
    if tox_score < settings.TOX_THRESHOLD:
        return
    # Fetch context
    context_msgs = await get_context(message)
    context_text = [m.content for m in context_msgs]
    # Prompt LLM to decide action
    prompt = (
        f"A message was flagged as {tox_class} with score {tox_score:.2f}. "
        "Decide whether to DELETE or IGNORE this message. "
        f"Context: {context_text}. "
        "Respond in JSON: {\"action\": \"DELETE\" or \"IGNORE\", \"reason\": \"<=200 chars\"}."
    )
    response = await openai.ChatCompletion.acreate(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You moderate messages based on toxicity."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.0,
    )
    try:
        result = response.choices[0].message.content.strip()
        data = json.loads(result)
        action = data.get('action')
        reason = data.get('reason')
    except Exception:
        action = 'IGNORE'
        reason = 'Parsing error'
    # Perform action
    if action == 'DELETE':
        try:
            await message.delete()
            # DM user
            await message.author.send(
                f"Your message was removed for the following reason: {reason}\nContent: {message.content}"
            )
        except Exception:
            pass
    # Log moderation
    await db.moderation_logs.insert_one({
        'flaggedAt': message.created_at,
        'channelId': str(message.channel.id),
        'userId': str(message.author.id),
        'toxicity': tox_class,
        'action': action,
        'reason': reason
    })