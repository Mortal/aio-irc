import time
import asyncio
import irc.client
import traceback


class Handler:
    async def handle_ping(self, connection, event):
        await self._handle_any(connection, event)
        await connection.pong(event.args)

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

    async def command_pingnow(self, client, args, showhide):
        showhide.show()
        self._last_event = 0
        self._change_pingevery.set()

    async def _idle_ping(self):
        try:
            while True:
                wait_amount = self._last_event + self._pingevery - time.time()
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
                    print(id(self), "PING timeout")
                    await asyncio.sleep(0.1)
                    try:
                        await self._client.connection.quit("PING timeout")
                    except irc.client.ServerNotConnectedError:
                        pass
                    await self._client.connection.disconnect()
                    return
        except:
            traceback.print_exc()
        finally:
            print("_idle_ping() exiting")

    async def _ping(self):
        self._counter += 1
        c = str(self._counter)
        self._pongs[c] = asyncio.Future()
        await self._client.connection.ping(c)
        try:
            await asyncio.wait_for(
                asyncio.shield(self._pongs[c]), 1)
        except asyncio.TimeoutError:
            print("Waiting for PONG %s" % c)
            await self._pongs[c]
        del self._pongs[c]

    async def handle_pong(self, connection, event):
        await self._handle_any(connection, event)
        try:
            self._pongs[event.args].set_result(None)
        except KeyError:
            print("Unexpected PONG %r" % event.args)

    async def load(self, client):
        self._counter = 0
        self._timeout = 10
        self._pingevery = 10
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
