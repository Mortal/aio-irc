import time
import asyncio


class Handler:
    async def handle_ping(self, connection, event):
        await self._handle_any(connection, event)
        await connection.pong(event.target)

    async def _handle_any(self, connection, event):
        self._last_event = time.time()

    def __getattr__(self, key):
        if key.startswith('handle_'):
            return self._handle_any
        raise AttributeError(key)

    async def command_pingevery(self, client, args, showhide):
        showhide.show()
        try:
            v = float(args)
        except ValueError:
            return '/PINGEVERY: Not a valid number: %r' % args
        if v < 2:
            return '/PINGEVERY: Must be at least 2 seconds'
        self._pingevery = v
        self._change_pingevery.set()

    async def _idle_ping(self):
        while True:
            wait_amount = self._last_event + self._pingevery - time.time()
            print(wait_amount)
            if wait_amount > 0:
                try:
                    await asyncio.wait_for(self._change_pingevery.wait(),
                                           wait_amount)
                except asyncio.TimeoutError:
                    pass
                self._change_pingevery.clear()
                continue
            try:
                await asyncio.wait_for(self._ping(), self._timeout)
            except asyncio.TimeoutError:
                print("PING timeout")
                await self._client.connection.quit("PING timeout")
                await self._client.connection.disconnect()
                return

    async def _ping(self):
        self._counter += 1
        c = str(self._counter)
        print("Registering pong %r" % c)
        self._pongs[c] = asyncio.Future()
        await self._client.connection.ping(c)
        await self._pongs[c]
        del self._pongs[c]

    async def handle_pong(self, connection, event):
        print("PONG %r" % event.args)
        await self._handle_any(connection, event)
        try:
            self._pongs[event.args].set_result(None)
        except KeyError:
            print("Unexpected PONG %r" % event.args)

    async def load(self, client):
        self._counter = 0
        self._timeout = 10
        self._pingevery = 300
        self._pongs = {}
        self._client = client
        self._last_event = time.time()
        self._change_pingevery = asyncio.Event()
        self._idle_ping_task = client.loop.create_task(self._idle_ping())

    async def reload(self, old_self):
        self._counter = old_self._counter
        self._timeout = old_self._timeout
        self._pingevery = old_self._pingevery
        self._last_event = old_self._last_event
        self._change_pingevery.set()

    async def unload(self, client):
        self._idle_ping_task.cancel()
        try:
            await self._idle_ping_task
        except asyncio.CancelledError:
            pass
        self._idle_ping_task = None