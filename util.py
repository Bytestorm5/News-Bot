import os
import json
import re
from typing import Union
import discord

async def batch_send(channel: Union[discord.TextChannel, discord.DMChannel], message: str):
    """
    Send a message in multiple parts if it exceeds Discord's 2000-char limit,
    preserving markdown blocks (```…```) and inline formatting
    (**bold**, __underline__, ~~strike~~, `code`) across chunk boundaries.
    """
    MAX_LEN = 2000
    lines = message.splitlines(keepends=True)
    chunks = []
    current = ""

    # State for fenced code blocks
    in_fence = False
    fence_marker = None

    # State for inline markers
    inline_markers = ["**", "__", "~~", "`"]
    open_inline = {m: False for m in inline_markers}

    def _count(text, marker):
        # naive count of occurrences
        return text.count(marker)

    for line in lines:
        # If adding this line would overflow, close/unroll and flush
        if len(current) + len(line) > MAX_LEN:
            # close any open fences
            if in_fence:
                current += fence_marker + "\n"
            # close any open inline markers
            for m, is_open in open_inline.items():
                if is_open:
                    current += m
            chunks.append(current)

            # start new chunk, reopening any still-open contexts
            current = ""
            if in_fence:
                current += fence_marker + "\n"
            for m, is_open in open_inline.items():
                if is_open:
                    current += m

        current += line

        # detect fenced code toggles
        stripped = line.rstrip("\n")
        if stripped.startswith("```"):
            if not in_fence:
                in_fence = True
                fence_marker = stripped
            else:
                in_fence = False
                fence_marker = None

        # update inline-marker states (skip backticks inside fences)
        for m in inline_markers:
            if m == "`" and in_fence:
                continue
            occ = _count(line, m)
            if occ % 2 == 1:
                open_inline[m] = not open_inline[m]

    # Flush the last chunk
    if in_fence:
        current += fence_marker + "\n"
    for m, is_open in open_inline.items():
        if is_open:
            current += m
    if current:
        chunks.append(current)

    # Send all the pieces
    for chunk in chunks:
        await channel.send(chunk)



class Util:
    """Utility class for processing messages and sending replies in Discord."""

    def __init__(self, client, guild):
        self.user_dict = {}
        self.client = client
        self.idxs = {}
        self.idx = 1
        self.last_ts = None
        self.guild = guild

    def get_name(self, id: int):
        if id in self.user_dict:
            return self.user_dict[id]
        member = self.guild.get_member(id)
        if member is None:
            return "Unknown/Deleted User"
        name = member.nick or self.client.get_user(id).display_name + "*"
        self.user_dict[id] = name
        return name

    def format_time_difference(self, start, end):
        delta = end - start
        total_seconds = int(delta.total_seconds())
        if abs(total_seconds) < 60:
            return f"{total_seconds:+d} sec"
        elif abs(total_seconds) < 3600:
            minutes = total_seconds // 60
            return f"{minutes:+d} min"
        elif abs(total_seconds) < 86400:
            hours = total_seconds // 3600
            return f"{hours:+d} h"
        days = total_seconds // 86400
        return f"{days:+d} d"

    def process_text(self, text: str):
        def replace_ping(match):
            user_id = int(match.group(1))
            return '@' + self.get_name(user_id)
        return re.sub(r'<@!(?P<id>\d+)>|<@(?P<id>\d+)>', replace_ping, text)

    def process(self, message: discord.Message):
        self.idxs[message.id] = self.idx
        line = f"{self.idx}: "
        if self.last_ts is not None:
            line += self.format_time_difference(self.last_ts, message.created_at)

        name = self.get_name(message.author.id)
        line += f" [{name}]: "

        if message.reference:
            reply_idx = self.idxs.get(message.reference.message_id, '?')
            line += f"(replyto: Msg {reply_idx}) "

        line += self.process_text(message.content) + "\n"
        self.last_ts = message.created_at
        self.idx += 1
        return line

    def get_idx(self):
        return self.idx

    def convert_mentions_to_string(self, message: discord.Message):
        for user in message.mentions:
            message.content = message.content.replace(f"<@{user.id}>", user.name)
        for role in message.role_mentions:
            message.content = message.content.replace(f"<@&{role.id}>", role.name)
        message.content = message.content.replace("@everyone", "everyone")
        message.content = message.content.replace("@here", "here")
        message.content = re.sub(r"<@!?\d+>", "unknown user", message.content)
        return message

    async def create_thread(self, channel, user_id_str):
        new_message = await channel.send(f"Anonymous User {user_id_str}")
        thread = await channel.create_thread(name=f"Anonymous User {user_id_str}", message=new_message)
        return thread

    async def send_attachment(self, message: discord.Message, destination):
        for attachment in message.attachments:
            file = await attachment.to_file()
            await destination.send(file=file)
