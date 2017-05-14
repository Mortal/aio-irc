import re
import asyncio
import datetime


CHANNEL = 12
NAME = 25


class Handler:
    def __init__(self):
        self.messages = open('messages.txt', 'a')
        self.events = open('events.txt', 'a')
        self.joinparts = []
        self._delayed_print_joinpart_task = None

    async def _delayed_print_joinpart(self):
        buf = []
        while self.joinparts:
            buf.extend(self.joinparts)
            del self.joinparts[:]
            await asyncio.sleep(0.1)
        if not buf:
            return
        joins = []
        parts = []
        for e in buf:
            if e.type == 'join':
                joins.append(e)
            elif e.type == 'part':
                parts.append(e)
            else:
                print("Invalid type %r" % e.type)
        if joins:
            join_msg = '%s joined' % ', '.join(e.source.nick for e in joins)
            self.log_custom_event('-', join_msg, buf[0].target, 'joinpart')
        if parts:
            part_msg = '%s parted' % ', '.join(e.source.nick for e in parts)
            self.log_custom_event('-', part_msg, buf[0].target, 'joinpart')

    def now_str(self):
        return datetime.datetime.now().isoformat()

    def time_str(self):
        return datetime.datetime.now().strftime('%H:%M:%S')

    def print_event(self, event):
        print(f'{self.now_str()} {repr(event)}',
              file=self.events, flush=True)
        source = getattr(event.source, 'nick', event.source)
        s = f'{event.target} {event.type} {source}'
        print(f'[{self.time_str()} {s.ljust(CHANNEL+NAME+1)}] {event.args}')

    def log_custom_event(self, source, message, target, type):
        event_dict = dict(target=target, source=source, msg=message, type=type)
        print(f'{self.now_str()} {repr(event_dict)}',
              file=self.events, flush=True)
        nick = getattr(source, 'nick', source)
        if type != 'pubmsg':
            nick = f'{type} {nick}'
        print(f'[{self.time_str()} {target.ljust(CHANNEL)} {nick.rjust(NAME)}] {message}')

    def print_message(self, event):
        tags = {
            k: v
            for kv in (event.tags or ())
            for k, v in [(kv['key'], kv['value'])]
        }
        name = tags.get('display-name') or event.source.nick
        data = {
            'target': event.target,
            'source': event.source,
            'msg': event.args,
        }
        if event.type != 'pubmsg':
            data['type'] = event.type
            name = f'{event.type} {name}'
        if tags:
            data['tags'] = tags
        print(f'{self.now_str()} {repr(data)}',
              file=self.messages, flush=True)
        name_pad = name.rjust(NAME)
        if tags.get('color'):
            mo = re.match(r'^#(..)(..)(..)$', tags['color'])
            r, g, b = [int(v, 16) for v in mo.group(1, 2, 3)]
            light = max(r, g, b)
            if light > 32:
                name_pad = '\x1B[38;2;%s;%s;%sm%s\x1B[39m' % (r, g, b, name_pad)
        print(f'[{self.time_str()} {event.target.ljust(CHANNEL)} {name_pad}] {event.args}')

    def log_sent(self, target, username, message):
        type = 'sent'
        data = {
            'target': target,
            'source': username,
            'msg': message,
            'type': type,
        }
        print(f'{self.now_str()} {repr(data)}',
              file=self.messages, flush=True)
        print(f'[{self.time_str()} {target.ljust(CHANNEL)} {username.rjust(NAME)}] {message}')

    async def _handle_message(self, connection, event):
        self.print_message(event)

    handle_pubmsg = handle_usernotice = _handle_message

    async def _handle_event(self, connection, event):
        self.print_event(event)

    async def handle_join(self, connection, event):
        self.joinparts.append(event)
        t = self._delayed_print_joinpart_task
        if t is None or t.done():
            loop = asyncio.get_event_loop()
            self._delayed_print_joinpart_task = loop.create_task(
                self._delayed_print_joinpart())

    handle_part = handle_join

    async def handle_ping(self, connection, event):
        pass

    async def handle_userstate(self, connection, event):
        pass

    def __getattr__(self, key):
        if key.startswith('handle_'):
            return self._handle_event
        raise AttributeError(key)
