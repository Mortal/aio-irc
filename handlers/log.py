import re
import random
import asyncio
import datetime
import traceback


WIDTH = 43

# https://discuss.dev.twitch.tv/t/default-user-color-in-chat/385/2
DEFAULT_COLORS = [
    ["Red", "#FF0000"],
    ["Blue", "#0000FF"],
    ["Green", "#00FF00"],
    ["FireBrick", "#B22222"],
    ["Coral", "#FF7F50"],
    ["YellowGreen", "#9ACD32"],
    ["OrangeRed", "#FF4500"],
    ["SeaGreen", "#2E8B57"],
    ["GoldenRod", "#DAA520"],
    ["Chocolate", "#D2691E"],
    ["CadetBlue", "#5F9EA0"],
    ["DodgerBlue", "#1E90FF"],
    ["HotPink", "#FF69B4"],
    ["BlueViolet", "#8A2BE2"],
    ["SpringGreen", "#00FF7F"],
]


def default_color(name):
    try:
        return default_color.cache[name]
    except KeyError:
        pass
    except AttributeError:
        default_color.cache = {}
    default_color.cache[name] = r = random.Random(name).choice(DEFAULT_COLORS)[1]
    return r


def adorn_name(name, tags, width, highlight):
    badges = tags.get('badges') or ''
    if 'staff' in badges:
        prefix = '&'
    elif 'moderator' in badges:
        prefix = '@'
    elif 'subscriber' in badges:
        prefix = '+'
    elif 'premium' in badges or 'bits' in badges or 'turbo' in badges:
        prefix = '-'
    else:
        prefix = ''
    padding = width - len(name) - len(prefix)
    name = adorn_highlight(name, highlight)
    color = tags.get('color') or default_color(name)
    mo = re.match(r'^#(..)(..)(..)$', color)
    r, g, b = [int(v, 16) for v in mo.group(1, 2, 3)]
    light = max(r, g, b)
    if light > 32:
        name = '\x1B[38;2;%s;%s;%sm%s\x1B[39m' % (r, g, b, name)
    name = prefix + name
    if padding > 0:
        name = ' ' * padding + name
    return name


def adorn_channel(name):
    color = default_color(name)
    mo = re.match(r'^#(..)(..)(..)$', color)
    r, g, b = [int(v, 16) for v in mo.group(1, 2, 3)]
    name = '\x1B[38;2;%s;%s;%sm%s\x1B[39m' % (r, g, b, name)
    return name


COLORS = {
    None: '33',
    'darbSubPipe': '32',
}


def adorn_highlight(message, pattern):
    if pattern:
        message = re.sub(pattern,
                         lambda mo: '\x1B[1m%s\x1B[0m' % mo.group(),
                         message)
    return message


def adorn_message(message, tags, highlight):
    if not tags.get('emotes'):
        return adorn_highlight(message, highlight)
    images = tags['emotes'].split('/')
    positions = []
    for img in images:
        emote_id, poses = img.split(':')
        for pos in poses.split(','):
            start, stop = map(int, pos.split('-'))
            positions.append((start, stop+1, emote_id))
    output = ''
    positions.sort()
    prev = 0
    for start, stop, emote_id in positions:
        output += message[prev:start]
        emote = message[start:stop]
        output += '\x1B[%sm%s\x1B[0m' % (COLORS.get(emote) or COLORS[None],
                                         emote)
        prev = stop
    output += message[prev:]
    return adorn_highlight(output, highlight)


class Handler:
    def __init__(self):
        self.messages = open('messages.txt', 'a')
        self.events = open('events.txt', 'a')
        self.joinparts = []
        self._delayed_print_joinpart_task = None
        self.recent_chatters = []

    async def load(self, client):
        self.client = client

    async def unload(self, client):
        self.messages.close()
        self.events.close()

    async def reload(self, prev):
        self.recent_chatters = getattr(prev, 'recent_chatters', [])

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
        s1 = self.time_str() + ' '
        s2 = f' {event.type} {source}'
        l = len(s1) + len(s2) + len(event.target)
        s = (s1 + adorn_channel(event.target) + s2) + ' ' * (WIDTH - l)
        print(f'[{s}] {event.args}')

    def log_custom_event(self, source, message, target, type, orig_event=None):
        event_dict = dict(target=target, source=source, msg=message, type=type)
        print(f'{self.now_str()} {repr(orig_event or event_dict)}',
              file=self.events, flush=True)
        nick = getattr(source, 'nick', source)
        if type != 'pubmsg':
            nick = f'{type} {nick}'
        s = self.time_str() + ' '
        l = len(s) + len(target) + 1
        s += adorn_channel(target) + ' '
        s += nick.rjust(WIDTH - l)
        print(f'[{s}] {message}')

    def print_message(self, event):
        tags = {
            k: v
            for kv in (event.tags or ())
            for k, v in [(kv['key'], kv['value'])]
        }
        name = tags.get('display-name') or event.source.nick
        try:
            self.recent_chatters.remove(name)
        except ValueError:
            pass
        self.recent_chatters.append(name)
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
        s = self.time_str() + ' '
        l = len(s) + len(event.target) + 1
        s += adorn_channel(event.target) + ' '
        highlight = self.client.config.HIGHLIGHT
        s += adorn_name(name, tags, WIDTH - l, highlight)
        msg = event.args
        try:
            msg = adorn_message(msg, tags, highlight)
        except Exception:
            traceback.print_exc()
        print(f'[{s}] {msg}')

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
        s = f'{self.time_str()} {target} '
        s += username.rjust(WIDTH - len(s))
        print(f'[{s}] {message}')

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

    async def handle_clearchat(self, connection, event):
        tags = {
            k: v
            for kv in (event.tags or ())
            for k, v in [(kv['key'], kv['value'])]
        }
        duration = tags.get('ban-duration')
        message = 'Timeout %s for %s second%s' % (
            event.args, duration, '' if duration == '1' else 's')
        self.log_custom_event('timeout', message, event.target, 'clearchat',
                              event)

    def __getattr__(self, key):
        if key.startswith('handle_'):
            return self._handle_event
        raise AttributeError(key)
