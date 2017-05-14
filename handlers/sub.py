import random


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


def get_next_msg():
    global last_msg
    msg = random.choice(MSGS)
    while msg == last_msg:
        msg = random.choice(MSGS)
    last_msg = msg
    return msg


class Handler:
    async def handle_pubmsg(self, connection, event):
        name = event.source.split('!')[0]
        if name != 'twitchnotify':
            # print("not twitchnotify")
            return
        if 'just subscribed' not in event.args:
            print('not "just subscribed"')
            return
        msg = get_next_msg()
        print("Send message to %s: %r" % (event.target, msg))
        await connection.privmsg(event.target, msg)

    async def handle_usernotice(self, connection, event):
        tags = {
            k: v
            for kv in (event.tags or ())
            for k, v in [(kv['key'], kv['value'])]
        }
        system_msg = tags.get('system-msg') or ''
        if not system_msg:
            print("No system-msg tag")
            return
        if 'just subscribed' not in system_msg:
            print('not "just subscribed"')
            return
        msg = get_next_msg()
        print("Send message to %s: %r" % (event.target, msg))
        await connection.privmsg(event.target, msg)
