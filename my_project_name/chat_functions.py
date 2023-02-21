import logging
from collections import defaultdict
from typing import Union, Dict, Iterator
import aiofiles
import aiofiles.os
import os
import magic
import traceback

from commonmark import commonmark
# noinspection PyPackageRequirements
from nio import (
    SendRetryError,
    RoomSendResponse,
    RoomSendError,
    LocalProtocolError,
    AsyncClient,
    RoomCreateResponse,
    RoomCreateError,
    RoomPreset,
    RoomVisibility,
    RoomInviteError,
    RoomInviteResponse, RoomKickResponse, RoomKickError, MatrixRoom, RoomAvatarEvent,
    ToDeviceMessage,
    ErrorResponse,
    UploadResponse
)
from nio.crypto import OlmDevice, InboundGroupSession, Session

from my_project_name.utils import get_room_id, with_ratelimit

logger = logging.getLogger(__name__)

async def send_text_to_room(
    client: AsyncClient, room: str, message: str, notice: bool = True, markdown_convert: bool = True,
    reply_to_event_id: str = None, replaces_event_id: str = None,
) -> Union[RoomSendResponse, RoomSendError, str]:
    """Send text to a matrix room
    Args:
        client (nio.AsyncClient): The client to communicate to matrix with
        room (str): The ID or alias of the room to send the message to
        message (str): The message content
        notice (bool): Whether the message should be sent with an "m.notice" message type
            (will not ping users)
        markdown_convert (bool): Whether to convert the message content to markdown.
            Defaults to true.
        reply_to_event_id (str): Optional event ID that this message is a reply to.
        replaces_event_id (str): Optional event ID that this message replaces.
    """
    try:
        room_id = await get_room_id(client, room, logger)
    except ValueError as ex:
        return str(ex)

    # Determine whether to ping room members or not
    msgtype = "m.notice" if notice else "m.text"

    content = {
        "msgtype": msgtype,
        "format": "org.matrix.custom.html",
        "body": message,
    }

    if markdown_convert:
        content["formatted_body"] = commonmark(message)

    if replaces_event_id:
        content["m.relates_to"] = {
            "rel_type": "m.replace",
            "event_id": replaces_event_id,
        }
        content["m.new_content"] = {
            "msgtype": msgtype,
            "format": "org.matrix.custom.html",
            "body": message,
        }
        if markdown_convert:
            content["m.new_content"]["formatted_body"] = commonmark(message)
    # We don't store the original message content so cannot provide the fallback, unfortunately
    elif reply_to_event_id:
        content["m.relates_to"] = {
            "m.in_reply_to": {
                "event_id": reply_to_event_id,
            },
        }

    try:
        return await client.room_send(
            room_id,
            "m.room.message",
            content,
            ignore_unverified_devices=True,
        )
    except (LocalProtocolError, SendRetryError) as ex:
        logger.exception(f"Unable to send message response to {room_id}")
        return f"Failed to send message: {ex}"

async def send_media_to_room(
    client: AsyncClient, room: str, media_type: str, body: str, media_url: str = None,
    media_file: dict = None, media_info: dict = None, reply_to_event_id: str = None,
) -> Union[RoomSendResponse, RoomSendError, str]:
    """Send media to a matrix room
    Args:
        client (nio.AsyncClient): The client to communicate to matrix with
        room (str): The ID or alias of the room to send the message to
        media_type (str): The media type
        body (str): The media body
        media_url (str): The media url
        media_file (dict): The media metadata
        media_info (dict): The media url and metadata
        reply_to_event_id (str): Optional event ID that this message is a reply to.
    """
    try:
        room_id = await get_room_id(client, room, logger)
    except ValueError as ex:
        return str(ex)

    if not (media_url or media_file):
        logger.warning(f"Empty media url for room identifier: {room}")
        return "Empty media url"

    content = {
        "msgtype": media_type,
        "body": body,
    }

    if media_url:
        content.update({"url": media_url})

    if media_file:
        content.update({"file": media_file})

    if media_info:
        content.update({"info": media_info})

    # We don't store the original message content so cannot provide the fallback, unfortunately
    if reply_to_event_id:
        content["m.relates_to"] = {
            "m.in_reply_to": {
                "event_id": reply_to_event_id,
            },
        }

    try:
        return await client.room_send(
            room_id,
            "m.room.message",
            content,
            ignore_unverified_devices=True,
        )
    except (LocalProtocolError, SendRetryError) as ex:
        logger.exception(f"Unable to send media response to {room_id}")
        return f"Failed to send media: {ex}"


async def create_private_room(
        client: AsyncClient, mxid: str, roomname: str
    ) -> Union[RoomCreateResponse, RoomCreateError, RoomAvatarEvent]:

        """
        :param mxid: user id to create a DM for
        :param roomname: The DM room name
        :return: the Room Response from room_create()
        """
        initial_state = [{"type":"m.room.power_levels", "content":{"users":{mxid:100, client.user_id:100}}}]
        resp = await with_ratelimit(client.room_create)(
                visibility=RoomVisibility.private,
                name=roomname,
                is_direct=True,
                preset=RoomPreset.private_chat,
                initial_state = initial_state,
                invite={mxid},
            )
        if isinstance(resp, RoomCreateResponse):
            logger.debug(f"Created a new DM for user {mxid} with roomID: {resp.room_id}")
        elif isinstance(resp, RoomCreateError):
            logger.exception(f"Failed to create a new DM for user {mxid} with error: {resp.status_code}")
        return resp

def is_user_in_room(room:MatrixRoom, mxid:str) -> bool:
    for user in room.users:
        if user == mxid:
            return True
    for user in room.invited_users:
        if user == mxid:
            return True
    return False

def is_room_private_msg(room: MatrixRoom, mxid: str) -> bool:
    if room.member_count == 2:
        return is_user_in_room(room, mxid)
    return False

def find_private_msg(client:AsyncClient, mxid: str) -> MatrixRoom:
    # Find if we already have a common room with user:
    msg_room = None
    for roomid in client.rooms:
        room = client.rooms[roomid]
        if is_room_private_msg(room, mxid):
            msg_room = room
            break

    if msg_room:
        logger.debug(f"Found existing DM for user {mxid} with roomID: {msg_room.room_id}")
    return msg_room

async def create_room(
        client: AsyncClient, roomname: str
) -> Union[RoomCreateResponse, RoomCreateError]:
    """
    :param roomname: The room name
    :return: the Room Response from room_create()
    """
    resp = await with_ratelimit(client.room_create)(
        name=roomname,
    )
    if isinstance(resp, RoomCreateResponse):
        logger.debug(f"Created a new room with roomID: {resp.room_id}")
    elif isinstance(resp, RoomCreateError):
        logger.exception(f"Failed to create a new room with error: {resp.status_code}")
    return resp

async def invite_to_room(
        client: AsyncClient, mxid: str, room_id: str
    ) -> Union[RoomInviteResponse, RoomInviteError]:

        """
        :param mxid: user id to invite
        :param roomname: The room name
        :return: the Room Response from room_create()
        """
        resp = await with_ratelimit(client.room_invite)(
                room_id=room_id,
                user_id=mxid,
            )
        if isinstance(resp, RoomInviteResponse):
            logger.debug(f"Invited user {mxid} to room: {room_id}")
        elif isinstance(resp, RoomInviteError):
            logger.exception(f"Failed to invite user {mxid} to room {room_id} with error: {resp.status_code}")
        return resp
    
async def send_file_to_room(
    client: AsyncClient,
    room_id: str,
    file: str,
    type: str,
) -> Union[RoomSendResponse, ErrorResponse]:
    """Process file.
    Upload file to server and then send link to rooms.
    Works and tested for .pdf, .txt, .ogg, .wav.
    All these file types are treated the same.
    Arguments:
    ---------
    rooms : list
        list of room_id-s
    file : str
        file name of file from --file argument
    """
    if not os.path.isfile(file):
        logger.debug(f"File {file} is not a file. Doesn't exist or "
                     "is a directory."
                     "This file is being droppend and NOT sent.")
        return

    mime_type = magic.from_file(file, mime=True)

    # first do an upload of file if it hasn't already been uploaded
    # see https://matrix-nio.readthedocs.io/en/latest/nio.html#nio.AsyncClient.upload # noqa
    # then send URI of upload to room
    file_stat = await aiofiles.os.stat(file)
    
    content_uri = None #self.store.get_uri(file)
    if content_uri is None:
        async with aiofiles.open(file, "r+b") as f:
            resp, maybe_keys = await client.upload(
                f,
                content_type=mime_type,  # application/pdf
                filename=os.path.basename(file),
                filesize=file_stat.st_size)
        if (isinstance(resp, UploadResponse)):
            logger.debug("File was uploaded successfully to server. "
                        f"Response is: {resp.content_uri}")
            content_uri = resp.content_uri
            # Store the content uri in our database for later reuse
            logger.debug(f"Storing file {file} uri {content_uri} to the DB.")
            #self.store.set_uri(file, content_uri)
        else:
            logger.info(f"Failed to upload file to server. "
                        "Please retry. This could be temporary issue on "
                        "your server. "
                        "Sorry.")
            logger.info(f"file=\"{file}\"; mime_type=\"{mime_type}\"; "
                        f"filessize=\"{file_stat.st_size}\""
                        f"Failed to upload: {resp}")
            return
    else:
        logger.debug(f"Found URI of {file} in the DB, using: {content_uri}")
    print("Finished file upload")

    content = {
        "body": os.path.basename(file),  # descriptive title
        "info": {
            "size": file_stat.st_size,
            "mimetype": mime_type,
        },
        "msgtype": type,
        "url": content_uri,
    }
    try:
        await client.room_send(
            room_id,
            message_type="m.room.message",
            content=content
        )
        logger.debug(f"This file was sent: \"{file}\" "
                     f"to room \"{room_id}\".")
    except Exception:
        logger.debug(f"File send of file {file} failed. "
                     "Sorry. Here is the traceback.")
        logger.debug(traceback.format_exc())
    return content_uri