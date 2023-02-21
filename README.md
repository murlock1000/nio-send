# nio-send

Matrix bot, that is used for creating text/file message send tasks to a user. 
When the bot is initialised, it creates any necessary new DM rooms, waits for the encryption to initialise and only then sends the messages. 
When all the message tasks have been completed - it shutdowns the main loop
