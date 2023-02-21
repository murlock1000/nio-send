import asyncio
import json
import logging
from datetime import datetime

# noinspection PyPackageRequirements
from nio import (
    JoinError, MatrixRoom, Event, RoomKeyEvent, RoomMessageText, MegolmEvent, LocalProtocolError,
    RoomKeyRequestError, RoomMemberEvent, Response, RoomKeyRequest, RoomCreateResponse, RoomEncryptionEvent,
)

from my_project_name.chat_functions import create_private_room, find_private_msg, send_file_to_room, send_text_to_room

logger = logging.getLogger(__name__)

DUPLICATES_CACHE_SIZE = 1000


class Callbacks(object):
    def __init__(self, client, store, config):
        """
        Args:
            client (nio.AsyncClient): nio client used to interact with matrix
            store (Storage): Bot storage
            config (Config): Bot configuration parameters
        """
        self.client = client
        self.store = store
        self.config = config
        self.received_events = []
        self.rooms_pending = {}
        self.user_rooms_pending = {}
        self.message_tasks = []
        self.lock = asyncio.Lock()
        self.items_to_send = 0
        self.main_loop = None
        
        self.recent_user_rooms = {}

    def trim_duplicates_caches(self):
        if len(self.received_events) > DUPLICATES_CACHE_SIZE:
            self.received_events = self.received_events[:DUPLICATES_CACHE_SIZE]
    
    def should_process(self, event_id: str) -> bool:
        logger.debug("Callback received event: %s", event_id)
        if event_id in self.received_events:
            logger.debug("Skipping %s as it's already processed", event_id)
            return False
        self.received_events.insert(0, event_id)
        return True
        
        
    async def member(self, room: MatrixRoom, event: RoomMemberEvent) -> None:
        """Callback for when a room member event is received.
        Args:
            room (nio.rooms.MatrixRoom): The room the event came from
            event (nio.events.room_events.RoomMemberEvent): The event
        """
        #logger.debug(
        #        f"Received a room member event for {room.display_name} | "
        #        f"{event.sender}: {event.membership}"
        #    )
        #logger.debug(event)
        async with self.lock:
            self.trim_duplicates_caches()
            if self.should_process(event.event_id) is False:
                return

            # Ignore messages older than 15 seconds
            if (
                    datetime.now() - datetime.fromtimestamp(event.server_timestamp / 1000.0)
            ).total_seconds() > 15:
                return

            logger.debug(
                f"Received a room member event for {room.display_name} | "
                f"{event.sender}: {event.membership}"
            )

            # Ignore if it was not us joining the room
            if event.sender != self.client.user:
                return
            logger.debug(f"ENCRYPTED: {self.client.rooms[room.room_id].encrypted}")
            logger.debug(event)

            # Ignore if any other membership event
            if event.membership != "invite": #or event.prev_content is None or event.prev_content.get("membership") == "join":
                logger.debug("IGNORING DUE TO NOT JOINING")
                return

            # Update User Communication room id
            logger.debug(f"Set new communications room for user to: {room.room_id}")
            logger.debug(f"messages left: {self.items_to_send}")
            logger.debug(f"Queue: {self.rooms_pending}")
            logger.debug(f"User queue: {self.user_rooms_pending}")
            
            # Ignore event, if no messages waiting to be processed
            if room.room_id not in self.rooms_pending.keys():
                return
            
            # Check if this is the invited user, other than us
            receiving_user = event.state_key
            if receiving_user not in self.user_rooms_pending.keys():
                return
            
            for message_task in self.rooms_pending[room.room_id]:
                logger.debug(f"ENCRYPTED: {self.client.rooms[room.room_id].encrypted}")
                #while self.client.rooms[room.room_id].encrypted is False:
                #    await asyncio.sleep(0.5)
                    #await self.client.synced.wait()
                logger.debug(f"FOUND ROOM: {self.client.rooms[room.room_id]}")
                logger.debug(f"SENDING MESSAGE TO ROOM {room.room_id}")
                await message_task
                self.items_to_send -= 1

            # Remove room from queue
            self.rooms_pending.pop(room.room_id)
            #self.user_rooms_pending = {key:val for key, val in self.user_rooms_pending.items() if val != room.room_id}

            # Check if that was the last messages to be sent - exit the program.
            if self.items_to_send == 0:
                self.main_loop.cancel()
            
            logger.debug(f"messages left: {self.items_to_send}")
            logger.debug(f"Queue: {self.rooms_pending}")
            logger.debug(f"User queue: {self.user_rooms_pending}")
    
    async def send_msg(self, mxid: str, content: str, message_type:str, room_id: str = None, roomname: str = ""):
        """
        :Code from - https://github.com/vranki/hemppa/blob/dcd69da85f10a60a8eb51670009e7d6829639a2a/bot.py
        :param mxid: A Matrix user id to send the message to
        :param roomname: A Matrix room id to send the message to
        :param message: Text to be sent as message
        :return bool: Returns room id upon sending the message
        """

        room_initialized = True
        
        # Acquire lock to process room for user - so duplicate room requests are not sent.
        async with self.lock:
            # Sends private message to user. Returns true on success.
            if room_id is None:
                msg_room = find_private_msg(self.client, mxid)
                logger.debug(f"Searching msg room: {msg_room} for {mxid}")
                if msg_room is not None:
                    msg_room = msg_room.room_id
                elif mxid in self.user_rooms_pending.keys():
                    msg_room = self.user_rooms_pending[mxid]
            else:
                msg_room = room_id

            # If Existing room not found - create a new one, if it hasn't been created by another message request yet.
            if msg_room is None and mxid not in self.user_rooms_pending.keys():
                resp = await create_private_room(self.client, mxid, roomname)
                logger.debug(f"Got resp msg room")
                if isinstance(resp, RoomCreateResponse):
                    room_id = resp.room_id
                    room_initialized = False
                    if room_id not in self.rooms_pending.keys():
                        self.rooms_pending[room_id] = []
                else:
                    return
            else:
                room_id = msg_room

            logger.debug(room_id)
            task = None

            if message_type == 'text':
                task = send_text_to_room(self.client, room_id, content)
            elif message_type == 'image':
                task = send_file_to_room(self.client, room_id, content, "m.image")
            elif message_type =='file':
                task = send_file_to_room(self.client, room_id, content, "m.file")
            else:
                logger.error(f"Unknown message type: {message_type}")
                return

            if room_initialized:
                if room_id not in self.client.rooms.keys() or self.client.rooms[room_id].encrypted is False:
                    self.rooms_pending[room_id].append(task)
                    self.user_rooms_pending[mxid] = room_id
                    print(f"Message appended to queue to be sent to {mxid} in room {room_id}")
                    return 
                await task
                print(f"Message sent to {mxid} in room {room_id}")
                self.items_to_send -= 1
                 # Check if that was the last messages to be sent - exit the program.
                if self.items_to_send == 0:
                    self.main_loop.cancel()
            else:
                self.rooms_pending[room_id].append(task)
                self.user_rooms_pending[mxid] = room_id
                print(f"Message appended to queue to be sent to {mxid} in room {room_id}")
            logger.debug(f"messages left: {self.items_to_send}")
            logger.debug(f"Queue: {self.rooms_pending}")
            logger.debug(f"User queue: {self.user_rooms_pending}")
        