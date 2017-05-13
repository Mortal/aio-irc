import re
from handlers.hostnotify import create_and_show_notification


class Handler:
    async def handle_pubmsg(self, connection, event):
        if re.search(r'\bmort(able)?\b', event.args, re.I):
            create_and_show_notification(
                'From %s in %s' % (event.source.split('!')[0], event.target),
                event.args)
