import re
from handlers.hostnotify import create_and_show_notification


class Handler:
    async def load(self, client):
        self.client = client
        self.pattern = client.config.HIGHLIGHT

    async def handle_pubmsg(self, connection, event):
        if re.search(self.pattern, event.args):
            create_and_show_notification(
                'From %s in %s' % (event.source.split('!')[0], event.target),
                event.args)
