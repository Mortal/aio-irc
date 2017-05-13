#! /usr/bin/env python
#
# Example program using irc.client.
#
# This program is free without restrictions; do anything you like with
# it.
#
# Joel Rosdahl <joel@rosdahl.net>

import sys
import json
import asyncio
import logging
import argparse
import datetime
import itertools

import irc.client
import jaraco.logging
import collections

target = None
"The nick or channel to which to send messages"

def on_connect(connection, event):
    if irc.client.is_channel(target):
        asyncio.get_event_loop().create_task(
            connection.join(target))

async def main_loop(connection, handler: 'Handler'):
    loop = asyncio.get_event_loop()
    await handler.disconnected.wait()
    await connection.quit("Using irc.client.py")

def on_disconnect(connection, event):
    raise SystemExit()

def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('server')
    parser.add_argument('nickname')
    parser.add_argument('password')
    parser.add_argument('target', help="a nickname or channel")
    parser.add_argument('-p', '--port', default=6667, type=int)
    jaraco.logging.add_arguments(parser, logging.INFO)
    return parser.parse_args()


class Handler:
    def __init__(self):
        self.fp = open('messages.txt', 'a')
        self.event_fp = open('events.txt', 'a')
        self.disconnected = asyncio.Event()

    def print_event(self, event):
        now = datetime.datetime.now()
        now_str = now.isoformat()
        print(f'{now_str} {event!r}', file=self.event_fp, flush=True)

    def __call__(self, connection, event):
        method = getattr(self, 'handle_' + event.type, self.generic_handle)
        method(connection, event)

    def handle_disconnect(self, connection, event):
        self.disconnected.set()
        self.print_event(event)

    def handle_all_raw_messages(self, connection, event):
        pass

    def handle_ping(self, connection, event):
        asyncio.get_event_loop().create_task(
            connection.pong(event.target))
        self.print_event(event)

    def print_arg(self, connection, event):
        print(f'[{event.type:10}] {" ".join(event.arguments).strip()}')
        self.print_event(event)

    handle_welcome = handle_yourhost = handle_created = print_arg
    handle_myinfo = handle_motdstart = handle_motd = print_arg
    handle_endofmotd = handle_namreply = handle_endofnames = print_arg

    generic_handle = print_arg

    def handle_join(self, connection, event):
        print(f'[{event.type:10}] {event.source} {event.target}')
        now = datetime.datetime.now().isoformat()
        print(json.dumps(dict(
            time=now,
            target=event.target,
            source=event.source,
            join=True)),
            file=self.fp, flush=True)
        self.print_event(event)

    def handle_pubmsg(self, connection, event):
        tags = {
            k: v
            for kv in (event.tags or ())
            for k, v in [(kv['key'], kv['value'])]
        }
        name = tags.get('display-name') or event.source.split('!')[0]
        args = ' '.join(event.arguments)
        now = datetime.datetime.now()
        now_str = now.isoformat()
        time_str = now.strftime('%H:%M:%S')
        data = collections.OrderedDict([
            ('time', now_str),
            ('target', event.target),
            ('source', event.source),
            ('msg', ' '.join(event.arguments).rstrip('\r')),
        ])
        if event.type != 'pubmsg':
            data['type'] = event.type
            name = f'{event.type} {name}'
        if tags:
            data['tags'] = tags
        print(json.dumps(data), file=self.fp, flush=True)
        print(f'[{time_str} {event.target} {name:30}] {args.strip()}')

    handle_usernotice = handle_pubmsg


def main():
    global target

    args = get_args()
    jaraco.logging.setup(args)
    target = args.target

    loop = asyncio.get_event_loop()
    print("Connect...")
    handler = Handler()
    try:
        c = loop.run_until_complete(
            irc.client.ServerConnection(handler, loop=loop).connect(
                args.server, args.port, args.nickname, args.password or None,
                caps='twitch.tv/tags twitch.tv/commands'
            ))
    except irc.client.ServerConnectionError:
        print(sys.exc_info()[1])
        raise SystemExit(1)
    print("Connected")

    c.handlers['welcome'] = [on_connect]
    c.handlers['disconnect'] = [on_disconnect]
    loop.run_until_complete(main_loop(c, handler))

if __name__ == '__main__':
    main()
