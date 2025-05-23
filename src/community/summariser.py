import os
import sys
from datetime import datetime, timedelta

# Include YWCC-RG-Bot utilities
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'ref', 'YWCC-RG-Bot')))
from util import Util
import llm_parse

from ..config import settings
from ..utils.ctx_utils import get_history
from ..database import db

async def handle_summarise(ctx, hours: int):
    """
    Summarise chat history from the channel/thread for the past 'hours' hours.
    """
    # Determine window
    since = datetime.utcnow() - timedelta(hours=hours)
    channel = ctx.channel
    # Initialize utility with bot client and guild
    util = Util(ctx.bot, ctx.guild)
    # Fetch and process messages
    messages = await get_history(channel, since)
    processed = [util.process(m) for m in messages]
    content = "\n".join(processed)
    # Generate summary
    report = llm_parse.process_large_text(content)
    footnote = (
        f"\n> Summary of messages from the last {hours} hours"
        f" ({len(processed)} messages; {len(content)} chars)"
    )
    report += footnote
    # Send summary response (split into chunks if necessary)
    if len(report) <= 2000:
        await ctx.send(report)
    else:
        lines = report.splitlines(keepends=True)
        chunk = ""
        for line in lines:
            if len(chunk) + len(line) > 2000:
                await ctx.send(chunk)
                chunk = line
            else:
                chunk += line
        if chunk:
            await ctx.send(chunk)
    # Cache summary in database
    await db.summaries.insert_one({
        "channelId": str(channel.id),
        "windowStart": since,
        "windowEnd": datetime.utcnow(),
        "summary": report,
        "createdAt": datetime.utcnow()
    })