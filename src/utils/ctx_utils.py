from datetime import timedelta

async def get_history(channel, since):
    """
    Fetch all messages in a channel or thread sent after the 'since' datetime.
    """
    messages = []
    async for msg in channel.history(after=since, limit=None):
        messages.append(msg)
    return messages

async def get_context(message, range_ms=5 * 60 * 1000):
    """
    Fetch messages around a given message within range_ms milliseconds before and after.
    """
    start = message.created_at - timedelta(milliseconds=range_ms)
    end = message.created_at + timedelta(milliseconds=range_ms)
    messages = []
    async for msg in message.channel.history(after=start, before=end, limit=None):
        messages.append(msg)
    return messages