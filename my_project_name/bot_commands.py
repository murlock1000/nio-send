import logging

from nio import AsyncClient, MatrixRoom, RoomMessageText, RoomRedactResponse

from my_project_name.chat_functions import ChatFunctions
from my_project_name.config import Config
from my_project_name.storage import Storage

logger = logging.getLogger(__name__)


class Command:
    def __init__(
        self,
        client: AsyncClient,
        store: Storage,
        config: Config,
        command: str,
        room: MatrixRoom,
        event: RoomMessageText,
        chat: ChatFunctions
    ):
        """A command made by a user.

        Args:
            client: The client to communicate to matrix with.

            store: Bot storage.

            config: Bot configuration parameters.

            command: The command and arguments.

            room: The room the command was sent in.

            event: The event describing the command.
        """
        self.client = client
        self.store = store
        self.config = config
        self.command = command
        self.room = room
        self.event = event
        self.chat = chat
        self.args = self.command.split()[1:]

    async def process(self):
        """Process the command"""
        if self.command.startswith("echo"):
            await self._echo()
        elif self.command.startswith("react"):
            await self._react()
        elif self.command.startswith("help"):
            await self._show_help()
        else:
            await self._unknown_command()

    async def filter_channel(self):
        # First check the power level of the sender. 0 - default, 50 - moderator, 100 - admin, others - custom.
        logger.debug(
            f"{self.room.user_name(self.event.sender)} has power level: {self.room.power_levels.get_user_level(self.event.sender)}"
        )
        if self.room.power_levels.get_user_level(self.event.sender) < 50:
            if self.room.power_levels.can_user_redact(self.client.user_id):

                # Redact the message
                tries = 0
                redact_response = None
                while type(redact_response) is not RoomRedactResponse and tries < 3:
                    redact_response = await self.client.room_redact(
                        self.room.room_id,
                        self.event.event_id,
                        "You are not a moderator of this channel.",
                    )
                    tries += 1
                if type(redact_response) is not RoomRedactResponse:
                    logger.error(f"Unable to redact message: {redact_response}")

                # Get user attempts from database
                fails = self.store.get_fail(self.event.sender, self.room.room_id)

                # Ban or increment attempts
                if fails < 3:
                    self.store.update_or_create_fail(
                        self.event.sender, self.room.room_id
                    )
                    new_room_id = await self.chat.send_msg(
                        self.event.sender,
                        ("""Your comment has been deleted {} times in {} discussion due to being improperly sent. Please reply in threads. \n
How to enable threads: \n
1. Hover on a message and click 'Reply in Thread' button. \n
2. Press 'Join the beta' button. \n
3. Reply to a message using the 'Reply in Thread' button.""").format(fails+1, self.room.name),
                        roomname = "WARNING!",
                    )
                    if new_room_id is None:
                        logger.error("Unable to find previously created room id.")
                    else:
                        await self.chat.send_msg(
                            self.event.sender,
                            "media/info_threads.gif",
                            is_image = True,
                            room_id = new_room_id,
                        )
                    
                else:
                    logger.info(
                        f"{self.room.user_name(self.event.sender)} has been banned from room {self.room.name}"
                    )
                    # Delete the user attempt entry
                    self.store.delete_fail(self.event.sender, self.room.room_id)

                    # Mute user
                    await self.chat.set_user_power(
                        self.room.room_id, self.event.sender, -1
                    )
                    # Inform user about the ban
                    await self.chat.send_msg(
                        self.event.sender,
                        f"# You have made >3 improper comments in {self.room.name} discussion. Please seek help from the group admin",
                        roomname = "WARNING!",
                    )
            else:
                logger.error(
                    f"Bot does not have sufficient power to redact others in group: {self.room.name}"
                )
