import asyncio
import logging
import re
import time

from typing import Optional, List

# noinspection PyPackageRequirements
import nio
logger = logging.getLogger(__name__)

# Domain part from https://stackoverflow.com/a/106223/1489738
USER_ID_REGEX = r"@[a-z0-9_=\/\-\.]*:(([a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9\-]*[a-zA-Z0-9])\.)*([A-Za-z0-9]|[A-Za-z0-9]" \
                r"[A-Za-z0-9\-]*[A-Za-z0-9])*"

reply_regex = re.compile(r"<mx-reply><blockquote>.*</blockquote></mx-reply>(.*)", flags=re.RegexFlag.DOTALL)


def make_pill(user_id: str, displayname: str = None) -> str:
    """Convert a user ID (and optionally a display name) to a formatted user 'pill'
    Args:
        user_id: The MXID of the user.
        displayname: An optional displayname. Clients like Element will figure out the
            correct display name no matter what, but other clients may not. If not
            provided, the MXID will be used instead.
    Returns:
        The formatted user pill.
    """
    if not displayname:
        # Use the user ID as the displayname if not provided
        displayname = user_id

    return f'<a href="https://matrix.to/#/{user_id}">{displayname}</a>'

def get_username(user_id: str)-> str:
    """
    Convert a user id `@user:server` to `user`
    """
    username_pattern = re.compile(r"@(.*):")
    match = username_pattern.match(user_id)
    if match:
        return match[1]
def get_in_reply_to(event: nio.Event) -> Optional[str]:
    """
    Pulls an in reply to event ID from an event, if any.
    """
    return event.source.get("content", {}).get("m.relates_to", {}).get("m.in_reply_to", {}).get("event_id")


def get_mentions(text: str) -> List[str]:
    """
    Get mentions in a message.
    """
    matches = re.finditer(USER_ID_REGEX, text, re.MULTILINE)
    return list({match.group() for match in matches})


def get_replaces(event: nio.Event) -> Optional[str]:
    """
    Get the replaces relation, if any.
    """
    rel_type = event.source.get("content", {}).get("m.relates_to", {}).get("rel_type")
    if rel_type == "m.replace":
        return event.source.get("content").get("m.relates_to").get("event_id")


def _get_reply_msg(event: nio.Event) -> Optional[str]:
    # first check if this is edit
    if get_replaces(event):
        msg_plain = event.source.get("content", {}).get("m.new_content", {}).get("body")
        msg_formatted = event.source.get("content", {}).get("m.new_content", {}).get("formatted_body")
    else:
        msg_plain = event.source.get("content", {}).get("body")
        msg_formatted = event.source.get("content", {}).get("formatted_body")

    if msg_formatted and (reply_msg := reply_regex.findall(msg_formatted)):
        return reply_msg[0]
    elif msg_formatted:
        return msg_formatted
    else:
        #revert to old method
        message_parts = msg_plain.split('\n\n', 1)
        if len(message_parts) > 1:
            return '\n\n'.join(message_parts[1:])
        return msg_plain


def get_reply_msg(event: nio.Event, reply_to: Optional[str], replaces: Optional[str]) -> Optional[str]:
    if reply_to or replaces:
        if reply_section := _get_reply_msg(event):
            if any([reply_section.startswith(x) for x in ("!reply ", "<p>!reply ")]):
                return reply_section
def get_raise_msg(event: nio.Event, reply_to: Optional[str], replaces: Optional[str]) -> Optional[str]:
    if reply_to or replaces:
        if reply_section := _get_reply_msg(event):
            if any([reply_section.startswith(x) for x in ("!raise ", "<p>!raise ")]):
                return reply_section


async def get_room_id(client: nio.AsyncClient, room: str, logger: logging.Logger) -> str:
    if room.startswith("#"):
        response = await client.room_resolve_alias(room)
        if getattr(response, "room_id", None):
            logger.debug(f"Room '{room}' resolved to {response.room_id}")
            return response.room_id
        else:
            logger.warning(f"Could not resolve '{room}' to a room ID")
            raise ValueError("Unknown room alias")
    elif room.startswith("!"):
        return room
    else:
        logger.warning(f"Unknown type of room identifier: {room}")
        raise ValueError("Unknown room identifier")


async def sleep_ms(delay_ms):
    deadzone = 50  # 50ms additional wait time.
    delay_s = (delay_ms + deadzone) / 1000

    await asyncio.sleep(delay_s)

def with_ratelimit(func):
    """
    Decorator for calling client methods with backoff, specified in server response if rate limited.
    """
    async def wrapper(*args, **kwargs):
        while True:
            logger.debug(f"waiting for response")
            response = await func(*args, **kwargs)
            logger.debug(f"Response: {response}")
            if isinstance(response, nio.ErrorResponse):
                if response.status_code == "M_LIMIT_EXCEEDED":
                    await sleep_ms(response.retry_after_ms)
                else:
                    return response
            else:
                return response

    return wrapper