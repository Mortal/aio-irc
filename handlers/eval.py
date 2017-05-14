class Handler:
    async def command_eval(self, client, args, showhide):
        showhide.show()
        return eval(args, dict(client=client, connection=client.connection,
                               config=client.config))

    async def command_exec(self, client, args, showhide):
        showhide.show()
        locals = {}
        exec(args, dict(client=client, connection=client.connection,
                        config=client.config), locals)
        return locals or None
