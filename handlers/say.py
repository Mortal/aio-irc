class Handler:

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
            channel = '#'+client.config.CHANNELS[0]
            client.subhandlers['log'].log_sent(
                channel, client.config.USERNAME, args)
            await client.connection.privmsg(channel, args)
