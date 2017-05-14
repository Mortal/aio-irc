import asyncio
import logging


class Handler:
    def __init__(self):
        self.messages = logging.getLogger('aiotwirc.messages')
        self.events = logging.getLogger('aiotwirc.events')
        self.joinparts = []
        self._delayed_print_joinpart_task = None

    async def _delayed_print_joinpart(self):
        n = len(self.joinparts)
        buf = []
        while self.joinparts:
            buf.extend(self.joinparts)
            del self.joinparts[:]
            await asyncio.sleep(0.1)
        if not buf:
            return
        if len(buf) == 1:
            self.print_message(buf[0])
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
            self.messages.info(join_msg,
                               extra=dict(event=None, target=buf[0].target,
                                          source='-', type='joinpart'))
        if parts:
            part_msg = '%s parted' % ', '.join(e.source.nick for e in parts)
            self.messages.info(part_msg,
                               extra=dict(event=None, target=buf[0].target,
                                          source='-', type='joinpart'))

    def print_event(self, event):
        try:
            msg = ' '.join(event.arguments)
        except TypeError:
            raise ValueError(event.arguments)
        self.events.info(msg.strip(),
                         extra=dict(event=event, target=event.target,
                                    type=event.type))

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
        self.messages.info(' '.join(event.arguments),
                           extra=dict(event=data, target=event.target,
                                      source=name, type=event.type))

    async def _handle_message(self, connection, event):
        self.print_message(event)

    handle_pubmsg = handle_usernotice = handle_mode = _handle_message

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

    def log_sent(self, target, username, message):
        type = 'sent'
        data = {
            'target': target,
            'source': username,
            'msg': message,
            'type': type,
        }
        self.messages.info(message,
                           extra=dict(event=data, target=target,
                                      source=username, type=type))
