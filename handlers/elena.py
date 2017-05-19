import random
from handlers.hostnotify import create_and_show_notification


MSGS = [
    'darbElena darbElena darbElena',
    'darbElena darbElena darbElena',
    'darbElena darbHR darbElena darbHR darbElena',
    'darbElena darbHR darbHolyCow',
    'darbBro darbElena',
]


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
    def should_post(self, msg, target):
        if 'SEX' not in msg:
            print('No SEX')
            return False
        if 'http' not in msg:
            print('No link')
            return False
        if target != '#darbian':
            print('not #darbian')
            return False
        return True

    async def post(self, connection, target):
        msg = get_next_msg()
        print("Send message to %s: %r" % (target, msg))
        create_and_show_notification(
            'darbElena', msg, key='elena')
        await connection.privmsg(target, msg)

    async def handle_pubmsg(self, connection, event):
        name = event.source.split('!')[0]
        if not name.startswith('elena'):
            return
        if not self.should_post(event.args, event.target):
            return
        await self.post(connection, event.target)
