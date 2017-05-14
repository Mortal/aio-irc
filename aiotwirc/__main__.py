import sys
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
    def f(name, filename, format, outformat=None, level=logging.INFO):
        logger = logging.getLogger(name)
        handler = logging.FileHandler(filename)
        handler.formatter = logging.Formatter(format)
        logger.addHandler(handler)
        if outformat is not None:
            outhandler = logging.StreamHandler(sys.stdout)
            outhandler.formatter = logging.Formatter(outformat)
            logger.addHandler(outhandler)
        logger.setLevel(level)

    f('irc.client', 'irc.log',
      '[%(asctime)s %(name)s %(levelname)s] %(message)s', level=logging.DEBUG)
    f('aiotwirc.messages', 'messages.txt',
      '%(asctime)s %(event)r',
      '[%(asctime)s %(target)s %(source)30s] %(message)s')
    f('aiotwirc.events', 'events.txt',
      '%(asctime)s %(event)r',
      '[%(asctime)s %(type)10s] %(message)s')


class Client:
    def __init__(self, config, loop):
        self.config = config
        self.loop = loop
        self.connection = irc.client.ServerConnection(
            self.event_handler, loop=loop)
        self.welcomed = asyncio.Event()
        self.subhandlers = {
            m: importlib.import_module('handlers.%s' % m).Handler()
            for m in 'hostnotify ping sub highlight log'.split()
        }

    async def connect(self):
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
        async for linedata in async_readlines(self.loop):
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
        await self.connection.quit()
        await self.connection.disconnect()

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
                print('Exception in %s.handle_%s' %
                      (handler.__class__.__qualname__,
                       event.type))
                traceback.print_exc()

    async def handle_welcome(self, event):
        self.welcomed.set()

    async def command_load(self, *args):
        if not args:
            print("Usage: /load module")
        for m in args:
            name = 'handlers.%s' % m
            try:
                mod = importlib.import_module(name)
            except Exception:
                print("Failed to load module %s" % name)
                continue
            importlib.reload(mod)
            try:
                handler_class = mod.Handler
            except AttributeError:
                print('Could not find %s.Handler' % name)
                continue
            try:
                self.subhandlers[m] = handler_class()
            except Exception:
                print('Could not initialize %s.Handler' % name)
                continue

    async def command_unload(self, *args):
        if not args:
            print("Usage: /unload module")
        for m in args:
            try:
                del self.subhandlers[m]
            except KeyError:
                print('Module %s not loaded' % m)

    async def command_quit(self, *args):
        try:
            await self.connection.quit(' '.join(args))
        except irc.client.ServerNotConnectedError:
            pass
        await self.connection.disconnect()
        assert not self.connection.connected

    async def command_quot(self, *args):
        await self.connection.send_items(*args)

    async def command_say(self, args, showhide):
        if args.strip() == '':
            showhide.hide()
            return
        if not self.config.USERNAME:
            showhide.show()
            return 'Not logged in! ' + self.config.USERNAME
        elif len(self.config.CHANNELS) != 1:
            showhide.show()
            print("Wrong number of channels in config (%r)" %
                  len(self.config.CHANNELS))
        else:
            showhide.hide()
            channel = '#'+self.config.CHANNELS[0]
            self.subhandlers['log'].log_sent(
                channel, self.config.USERNAME, args)
            await self.connection.privmsg(channel, args)

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


async def main_async(loop, config):
    client = Client(config, loop)
    await client.connect()
    task = loop.create_task(client.handle_stdin())
    try:
        await client.connection.wait_disconnected()
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def main():
    parser = argparse.ArgumentParser()
    parser.parse_args()
    config = read_config()
    init_logging(config)
    loop = asyncio.get_event_loop()
    main_task = loop.create_task(main_async(loop, config))
    try:
        loop.run_until_complete(main_task)
    except KeyboardInterrupt:
        main_task.cancel()
        try:
            loop.run_until_complete(main_task)
        except asyncio.CancelledError:
            pass


if __name__ == '__main__':
    main()
