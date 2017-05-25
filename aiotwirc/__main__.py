import sys
import time
import types
import asyncio
import inspect
import logging
import argparse
import functools
import importlib
import traceback

import irc.client

from aiotwirc.stdio import async_readlines


BASE_CONFIG = dict(
    APP_NAME='aiotwirc',
    DEFAULT_USERNAME='justinfan3141592653',
    DEFAULT_PASSWORD='blah',
    USERNAME=None,
    PASSWORD=None,
    SERVER='irc.chat.twitch.tv',
    PORT=6667,
    CAPS='twitch.tv/tags twitch.tv/commands twitch.tv/membership',
    CHANNELS=(),
    PLUGINS='hostnotify ping sub highlight log say'.split(),
)


def read_config():
    config = dict(BASE_CONFIG)
    with open('twitchconfig.py') as fp:
        config_source = fp.read()
    exec(config_source, {}, config)
    ns = types.SimpleNamespace()
    for k, v in config.items():
        setattr(ns, k, v)
    return ns


def init_logging(config):
    def f(name, filename, format, level=logging.INFO):
        logger = logging.getLogger(name)
        handler = logging.FileHandler(filename)
        handler.formatter = logging.Formatter(format)
        logger.addHandler(handler)
        logger.setLevel(level)

    f('irc.client', 'irc.log',
      '[%(asctime)s %(name)s %(levelname)s] %(message)s', level=logging.DEBUG)


class HandlerImportError(Exception):
    pass


class Client:
    def __init__(self, config, loop, args):
        self.config = config
        if args.channel:
            self.config.CHANNELS = args.channel
        self.loop = loop
        self.connection = irc.client.ServerConnection(
            self.event_handler, loop=loop)
        self.welcomed = asyncio.Event()
        self.subhandlers = {}
        self.intentional_disconnect = False

    async def connect(self):
        for m in self.config.PLUGINS:
            if m not in self.subhandlers:
                self.subhandlers[m] = await self.load_subhandler(m)
        if 'say' not in self.subhandlers:
            print("Remember to /load say")
        if self.config.USERNAME:
            username = self.config.USERNAME
            password = self.config.PASSWORD
        else:
            username = self.config.DEFAULT_USERNAME
            password = self.config.DEFAULT_PASSWORD
        await self.connection.connect(
            self.config.SERVER, self.config.PORT, username, password,
            caps=self.config.CAPS)
        await self.welcomed.wait()
        for c in self.config.CHANNELS:
            await self.connection.join('#'+c)

    async def handle_stdin(self):
        self.readlines = async_readlines(self.loop)
        async for linedata in self.readlines:
            try:
                line = linedata.decode()
            except UnicodeDecodeError:
                linedata.hide()
                print('Could not decode %r' % (line,))
                continue
            showhide = ShowHide(linedata.show, linedata.hide)
            line = line.rstrip('\r\n')
            if line.startswith('/'):
                method, sp, args = line[1:].partition(' ')
            else:
                method, args = 'say', line
            await self.input_command(method, args, showhide)
            showhide.show()
        self.intentional_disconnect = True
        try:
            await self.connection.quit()
        except irc.client.ServerNotConnectedError:
            pass
        await self.connection.disconnect()

    def set_default_msg(self, msg):
        last_buffer_set = getattr(self, 'last_buffer_set', '')
        current_buf = self.readlines.get_buffer()
        if current_buf in (last_buffer_set, ''):
            self.readlines.set_buffer(msg)
            self.last_buffer_set = msg
        else:
            print("Not overriding %r with %r" % (current_buf, msg))

    async def event_handler(self, connection, event):
        if event.type == 'all_raw_messages':
            return
        for handler in [self] + list(self.subhandlers.values()):
            try:
                method = getattr(handler, 'handle_' + event.type)
            except AttributeError:
                continue
            try:
                await method(connection, event)
            except Exception:
                print('Exception in %s.%s.%s' %
                      (handler.__class__.__module__,
                       handler.__class__.__name__,
                       getattr(handler, '__name__')))
                traceback.print_exc()

    async def handle_welcome(self, connection, event):
        self.welcomed.set()

    async def command_load(self, args, showhide):
        showhide.show()
        args = args.split()
        if not args:
            print("Usage: /load module")
        for m in args:
            prev = self.subhandlers.get(m)
            try:
                self.subhandlers[m] = r = await self.load_subhandler(m)
            except HandlerImportError as exn:
                print(exn)
            else:
                try:
                    on_reload = r.reload
                except AttributeError:
                    pass
                else:
                    await on_reload(prev)

    async def load_subhandler(self, m):
        name = 'handlers.%s' % m
        try:
            mod = importlib.import_module(name)
        except Exception:
            raise HandlerImportError("Failed to load module %s" % name)
        importlib.reload(mod)
        try:
            handler_class = mod.Handler
        except AttributeError:
            raise HandlerImportError('Could not find %s.Handler' % name)
        try:
            r = handler_class()
        except Exception:
            raise HandlerImportError('Could not initialize %s.Handler' % name)
        try:
            on_load = r.load
        except AttributeError:
            pass
        else:
            await on_load(self)
        return r

    async def command_unload(self, args, showhide):
        showhide.show()
        args = args.split()
        if not args:
            print("Usage: /unload module")
        for m in args:
            try:
                r = self.subhandlers.pop(m)
            except KeyError:
                print('Module %s not loaded' % m)
                continue
            try:
                on_unload = r.unload
            except AttributeError:
                pass
            else:
                await on_unload(self)

    async def command_quit(self, args, showhide):
        self.intentional_disconnect = True
        showhide.show()
        try:
            await self.connection.quit(args)
        except irc.client.ServerNotConnectedError:
            pass
        await self.connection.disconnect()
        assert not self.connection.connected

    async def command_quot(self, args, showhide):
        showhide.show()
        await self.connection.send_items(args)

    def find_command(self, method, args, showhide):
        method_lower = method.lower()
        cmd_method = 'command_' + method_lower
        if hasattr(self, cmd_method):
            return functools.partial(
                getattr(self, cmd_method), args, showhide)
        if '_' not in method:
            fn = getattr(self.connection, method_lower, None)
            if inspect.iscoroutinefunction(fn):
                return functools.partial(fn, *args.split())
        for subhandler in self.subhandlers.values():
            try:
                return functools.partial(
                    getattr(subhandler, cmd_method),
                    self, args, showhide)
            except AttributeError:
                pass

    async def input_command(self, method, args, showhide):
        fn = self.find_command(method, args, showhide)
        if fn is None:
            showhide.show()
            print('Invalid method %r' % method)
            return
        try:
            res = await fn()
        except Exception:
            traceback.print_exc()
        else:
            if res is not None:
                print(res)


class ShowHide:
    def __init__(self, show, hide):
        self._show = show
        self._hide = hide
        self._calls = 0

    def show(self):
        self._calls += 1
        if self._calls == 1:
            self._show()

    def hide(self):
        self._calls += 1
        if self._calls == 1:
            self._hide()


async def main_async(loop, config, args):
    delay = 0
    while True:
        client = Client(config, loop, args)
        await client.connect()
        task = loop.create_task(client.handle_stdin())
        try:
            t1 = time.time()
            await client.connection.wait_disconnected()
            t2 = time.time()
        finally:
            try:
                client.readlines.close()
            except Exception:
                pass
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if client.intentional_disconnect:
            print("Intentionally disconnecting")
            break
        elapsed = t2 - t1
        if elapsed < 60:
            delay = 2 * delay or 2
            print("We were disconnected. Try again in %s seconds" % delay)
            await asyncio.sleep(delay)
        else:
            print("We were disconnected. Try again.")
            delay = 0
    print("main_async is done")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('channel', nargs='*')
    args = parser.parse_args()
    config = read_config()
    init_logging(config)
    loop = asyncio.get_event_loop()
    main_task = loop.create_task(main_async(loop, config, args))
    try:
        loop.run_until_complete(main_task)
    except KeyboardInterrupt:
        main_task.cancel()
        try:
            loop.run_until_complete(main_task)
        except asyncio.CancelledError:
            pass


if __name__ == '__main__':
    try:
        main()
    except:
        print("Exiting main() via an exception")
        traceback.print_exc()
        raise
    else:
        print("Exiting main() without an exception")
