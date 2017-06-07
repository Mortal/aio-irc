import time


class Handler:

    SPAM_DELAY = 5

    async def load(self, client):
        self.client = client
        self.last_cmd = {}

    async def reload(self, prev):
        try:
            self.last_cmd = prev.last_cmd
        except AttributeError:
            pass

    def cmd_spam(self, args):
        if not args[:1] == '!':
            return
        cmd = args.split()[0].lower()
        try:
            t, nick = self.last_cmd.pop(cmd)
        except KeyError:
            return
        elapsed = time.time() - t
        if elapsed < self.SPAM_DELAY:
            print("%s just said %s, " % (nick, cmd) +
                  "%.1f seconds ago. " % elapsed +
                  "Press Enter to send, or CTRL-U to cancel.")
            self.client.set_default_msg(args)
            return True

    async def command_say(self, client, args, showhide):
        if args.strip() == '':
            showhide.hide()
            return
        if not client.config.USERNAME:
            showhide.show()
            return 'Not logged in! ' + client.config.USERNAME
        elif len(client.config.CHANNELS) != 1:
            showhide.show()
            print("Wrong number of channels in config (%r)" %
                  len(client.config.CHANNELS))
        else:
            showhide.hide()
            if self.cmd_spam(args):
                return
            channel = '#'+client.config.CHANNELS[0]
            client.subhandlers['log'].log_sent(
                channel, client.config.USERNAME, args)
            await client.connection.privmsg(channel, args)

    async def handle_pubmsg(self, connection, event):
        if not event.args[:1] == '!':
            return
        cmd = event.args.split()[0].lower()
        self.last_cmd[cmd] = (time.time(), event.source.nick)
