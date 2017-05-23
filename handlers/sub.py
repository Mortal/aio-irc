import time
import random
import asyncio
import traceback


MSGS = (
    19*['darbSubPipe darbSubPipe darbSubPipe'] +
    15*['darbSubPipe'] +
    # 10*['darbSubPipe quickPipe'] +
    6*['darbSubPipe darbSubPipe'] +
    4*['darbSubPipe darbSubPipe darbSubPipe darbSubPipe darbSubPipe'] +
    3*['darbSubPipe darbHR darbSubPipe'] +
    2*['darbSubPipe darbSubPipe darbSubPipe darbSubPipe darbSubPipe darbSubPipe'] +
    [
        'darbSubPipe darbTasty darbSubPipe',
        'darbSubPipe darbSayNo darbBone darbSubPipe',
        'darbSubPipe darbHolyCow darbSubPipe',
        'darbHolyCow darbSubPipe darbHolyCow darbSubPipe darbHolyCow darbSubPipe',
    ]
)


try:
    last_msg
except NameError:
    last_msg = None

try:
    repost_mutex
except NameError:
    repost_mutex = asyncio.Lock()


def get_next_msg():
    global last_msg
    msg = random.choice(MSGS)
    while msg == last_msg:
        msg = random.choice(MSGS)
    last_msg = msg
    return msg


class Handler:
    def __init__(self):
        self.last_msg = {}

    def should_post(self, system_msg, target):
        if not system_msg:
            print("No system-msg")
            return
        if 'just subscribed' not in system_msg and 'subscribed for' not in system_msg:
            print('not "just subscribed"')
            return False
        if 'just subscribed to' in system_msg:
            print('"just subscribed to"')
            return False
        if target != '#darbian':
            print('not #darbian')
            return False
        return True

    async def post(self, connection, target):
        msg = get_next_msg()
        self.last_msg[target] = (msg, time.time())
        print("Send message to %s: %r" % (target, msg))
        await connection.privmsg(target, msg)

    async def handle_pubmsg(self, connection, event):
        name = event.source.split('!')[0]
        if name != 'twitchnotify':
            return
        if not self.should_post(event.args, event.target):
            return
        await self.post(connection, event.target)

    async def handle_usernotice(self, connection, event):
        tags = {
            k: v
            for kv in (event.tags or ())
            for k, v in [(kv['key'], kv['value'])]
        }
        system_msg = tags.get('system-msg') or ''
        if not self.should_post(system_msg, event.target):
            return
        await self.post(connection, event.target)

    async def handle_pubnotice(self, connection, event):
        tags = {
            k: v
            for kv in (event.tags or ())
            for k, v in [(kv['key'], kv['value'])]
        }
        if tags.get('msg-id') == 'msg_ratelimit':
            self.msg_ratelimit(connection, event.target)

    def msg_ratelimit(self, connection, target):
        loop = connection.loop
        try:
            last_msg, last_msg_time = self.last_msg[target]
        except KeyError:
            return
        elapsed = time.time() - last_msg_time
        if elapsed > 1:
            return
        loop.create_task(self.repost(connection, last_msg))

    async def repost(self, connection, target, msg):
        try:
            await repost_mutex.acquire()
            await asyncio.sleep(1)
            print("Repost message to %s: %r" % (target, msg))
            await connection.privmsg(target, msg)
        except Exception:
            traceback.print_exc()
        finally:
            repost_mutex.release()
