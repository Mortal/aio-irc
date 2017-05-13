class Handler:
    async def handle_ping(self, connection, event):
        await connection.pong(event.target)
