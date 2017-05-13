# -*- coding: utf-8 -*-

"""
Internet Relay Chat (IRC) protocol client library.

This library is intended to encapsulate the IRC protocol in Python.
It provides an event-driven IRC client framework.  It has
a fairly thorough support for the basic IRC protocol, CTCP, and DCC chat.

To best understand how to make an IRC client, the reader more
or less must understand the IRC specifications.  They are available
here: [IRC specifications].

The main features of the IRC client framework are:

  * Abstraction of the IRC protocol.
  * Handles multiple simultaneous IRC server connections.
  * Handles server PONGing transparently.
  * Messages to the IRC server are done by calling methods on an IRC
    connection object.
  * Messages from an IRC server triggers events, which can be caught
    by event handlers.
  * Reading from and writing to IRC server sockets are normally done
    by an internal select() loop, but the select()ing may be done by
    an external main loop.
  * Functions can be registered to execute at specified times by the
    event-loop.
  * Decodes CTCP tagging correctly (hopefully); I haven't seen any
    other IRC client implementation that handles the CTCP
    specification subtilties.
  * A kind of simple, single-server, object-oriented IRC client class
    that dispatches events to instance methods is included.

Current limitations:

  * Data is not written asynchronously to the server, i.e. the write()
    may block if the TCP buffers are stuffed.
  * DCC file transfers are not supported.
  * RFCs 2810, 2811, 2812, and 2813 have not been considered.

Notes:
  * connection.quit() only sends QUIT to the server.
  * ERROR from the server triggers the error event and the disconnect event.
  * dropping of the connection triggers the disconnect event.


.. [IRC specifications] http://www.irchelp.org/irchelp/rfc/
"""

from __future__ import absolute_import, division

import re
import socket
import struct
import logging
import abc
import collections
import asyncio

import six

try:
    import pkg_resources
except ImportError:
    pass

from . import events
from . import features
from . import ctcp
from . import message

log = logging.getLogger(__name__)

# set the version tuple
try:
    VERSION_STRING = pkg_resources.require('irc')[0].version
    VERSION = tuple(int(res) for res in re.findall('\d+', VERSION_STRING))
except Exception:
    VERSION_STRING = 'unknown'
    VERSION = ()


class IRCError(Exception):
    "An IRC exception"

class InvalidCharacters(ValueError):
    "Invalid characters were encountered in the message"

class MessageTooLong(ValueError):
    "Message is too long"

_cmd_pat = "^(@(?P<tags>[^ ]*) )?(:(?P<prefix>[^ ]+) +)?(?P<command>[^ ]+)( *(?P<argument> .+))?"
_rfc_1459_command_regexp = re.compile(_cmd_pat)


class ServerConnectionError(IRCError):
    pass

class ServerNotConnectedError(ServerConnectionError):
    pass


class ServerConnection:
    """
    An IRC server connection.

    ServerConnection objects are instantiated by calling the server
    method on a Reactor object.
    """

    socket = None

    def __init__(self, handler=None, *, loop=None):
        self.loop = loop if loop else asyncio.get_event_loop()
        self.handler = handler
        self.connected_event = asyncio.Event()
        self.disconnected_event = asyncio.Event()
        self.features = features.FeatureSet()
        self._reader = self._writer = None

    @property
    def connected(self):
        return self.connected_event.is_set()

    def wait_disconnected(self):
        return self.disconnected_event.wait()

    def get_server_name(self):
        """Get the (real) server name.

        This method returns the (real) server name, or, more
        specifically, what the server calls itself.
        """
        return self.real_server_name or ""

    def get_nickname(self):
        """Get the (real) nick name.

        This method returns the (real) nickname.  The library keeps
        track of nick changes, so it might not be the nick name that
        was passed to the connect() method.
        """
        return self.real_nickname

    # save the method args to allow for easier reconnection.
    # @irc_functools.save_method_args
    async def connect(self, server, port, nickname, password=None,
                      username=None, ircname=None, caps=None):
        """Connect/reconnect to a server.

        Arguments:

        * server - Server name
        * port - Port number
        * nickname - The nickname
        * password - Password (if any)
        * username - The username
        * ircname - The IRC name ("realname")
        * server_address - The remote host/port of the server

        This function can be called to reconnect a closed connection.

        Returns the ServerConnection object.
        """
        log.debug("connect(server=%r, port=%r, nickname=%r, ...)", server,
            port, nickname)
        self._saved_connect_args = (server, port, nickname, password,
                                    username, ircname, caps)

        if self.connected:
            await self.quit("Changing servers")
            await self.disconnect()

        self.handlers = {}
        self.real_server_name = ""
        self.real_nickname = nickname
        self.server = server
        self.port = port
        self.server_address = (server, port)
        self.nickname = nickname
        self.username = username or nickname
        self.ircname = ircname or nickname
        self.password = password
        try:
            self._reader, self._writer = await asyncio.open_connection(
                server, port, loop=self.loop)
        except Exception as ex:
            raise ServerConnectionError("Couldn't connect to socket: %s" % ex)

        self._handler_coroutine = self.loop.create_task(
            self._handle_client())
        self.disconnected_event.clear()
        self.connected_event.set()

        # Log on...
        if caps:
            await self.cap('REQ', ':' + caps)
        if self.password:
            await self.pass_(self.password)
        await self.nick(self.nickname)
        await self.user(self.username, self.ircname)
        return self

    def reconnect(self):
        """
        Reconnect with the last arguments passed to self.connect()
        """
        self.connect(*self._saved_connect_args)

    async def disconnect(self, timeout=None):
        """Hang up the connection."""
        if not self.connected:
            return
        writer, self._writer = self._writer, None
        if not writer:
            # Another disconnect in progress
            return
        if writer.can_write_eof():
            writer.write_eof()
            await writer.drain()
        if timeout is None:
            timeout = 1
        try:
            await asyncio.wait_for(self._handler_coroutine,
                                   timeout, loop=self.loop)
        except asyncio.TimeoutError:
            log.error('Server did not close connection after %s s, aborting',
                      timeout)
            writer.abort()
            self._handler_coroutine.cancel()
        await self._handle_event(Event("disconnect", self.server, "", [message]))

    async def _handle_client(self):
        while True:
            try:
                line = await self._reader.readline()
            except Exception as exn:
                log.exception("readline() failed")
                self.connected_event.clear()
                self.disconnected_event.set()
                try:
                    if self._writer:
                        await self.quit('Read error')
                except Exception:
                    log.exception('quit() also failed')
                await self.disconnect()
                break
            try:
                if line == b'':
                    log.info('EOF from server')
                    self.connected_event.clear()
                    self.disconnected_event.set()
                    assert not self.connected
                    await self.disconnect()
                    break
                log.debug("FROM SERVER: %r", line)
                line = line.rstrip(b'\r\n')
                if line:
                    await self._process_line(line.decode())
            except Exception as exn:
                log.exception("_process_line failed, line = %r", line)
        log.info('_handle_client is done')

    async def _process_line(self, line):
        event = Event("all_raw_messages", self.get_server_name(), None,
            [line])
        await self._handle_event(event)

        grp = _rfc_1459_command_regexp.match(line).group

        source = NickMask.from_group(grp("prefix"))
        command = self._command_from_group(grp("command"))
        arguments = message.Arguments.from_group(grp('argument'))
        tags = message.Tag.from_group(grp('tags'))

        if source and not self.real_server_name:
            self.real_server_name = source

        if command == "nick":
            if source.nick == self.real_nickname:
                self.real_nickname = arguments[0]
        elif command == "welcome":
            # Record the nickname in case the client changed nick
            # in a nicknameinuse callback.
            self.real_nickname = arguments[0]
        elif command == "featurelist":
            self.features.load(arguments)

        handler = (
            self._handle_message
            if command in ["privmsg", "notice"]
            else self._handle_other
        )
        await handler(arguments, command, source, tags)

    async def _handle_message(self, arguments, command, source, tags):
        target, msg = arguments[:2]
        messages = ctcp.dequote(msg)
        if command == "privmsg":
            if is_channel(target):
                command = "pubmsg"
        else:
            if is_channel(target):
                command = "pubnotice"
            else:
                command = "privnotice"
        for m in messages:
            if isinstance(m, tuple):
                if command in ["privmsg", "pubmsg"]:
                    command = "ctcp"
                else:
                    command = "ctcpreply"

                m = list(m)
                log.debug("command: %s, source: %s, target: %s, "
                          "arguments: %s, tags: %s", command, source, target, m, tags)
                event = Event(command, source, target, m, tags)
                await self._handle_event(event)
                if command == "ctcp" and m[0] == "ACTION":
                    event = Event("action", source, target, m[1:], tags)
                    await self._handle_event(event)
            else:
                log.debug("command: %s, source: %s, target: %s, "
                          "arguments: %s, tags: %s", command, source, target, [m], tags)
                event = Event(command, source, target, [m], tags)
                await self._handle_event(event)

    async def _handle_other(self, arguments, command, source, tags):
        target = None
        if command == "quit":
            arguments = [arguments[0]]
        elif command == "ping":
            target = arguments[0]
        else:
            target = arguments[0] if arguments else None
            arguments = arguments[1:]
        if command == "mode":
            if not is_channel(target):
                command = "umode"
        log.debug("command: %s, source: %s, target: %s, "
                  "arguments: %s, tags: %s", command, source, target, arguments, tags)
        event = Event(command.strip(), source, target, arguments, tags)
        await self._handle_event(event)

    @staticmethod
    def _command_from_group(group):
        command = group.lower()
        # Translate numerics into more readable strings.
        return events.numeric.get(command, command)

    async def _handle_event(self, event: 'Event'):
        """[Internal]"""
        try:
            if self.handler is not None:
                await self.handler(self, event)
            if event.type in self.handlers:
                for fn in self.handlers[event.type]:
                    fn(self, event)
        except Exception:
            log.exception("Handler raised an exception")

    async def send_items(self, *items):
        """
        Send all non-empty items, separated by spaces.
        """
        await self.send_raw(' '.join(filter(None, items)))

    async def send_raw(self, string):
        """Send raw string to the server.

        The string will be padded with appropriate CR LF.
        """
        if not self.connected:
            raise ServerNotConnectedError("Not connected.")
        writer = self._writer
        if not writer:
            raise ServerNotConnectedError("Connection shutting down.")
        writer.write(self._prep_message(string))
        log.debug("TO SERVER: %s", string)
        await writer.drain()

    def _prep_message(self, string):
        # The string should not contain any carriage return other than the
        # one added here.
        if '\n' in string:
            msg = "Carriage returns not allowed in privmsg(text)"
            raise InvalidCharacters(msg)
        bytes = string.encode('utf-8') + b'\r\n'
        # According to the RFC http://tools.ietf.org/html/rfc2812#page-6,
        # clients should not transmit more than 512 bytes.
        if len(bytes) > 512:
            msg = "Messages limited to 512 bytes including CR/LF"
            raise MessageTooLong(msg)
        return bytes

    async def action(self, target, action):
        """Send a CTCP ACTION command."""
        await self.ctcp("ACTION", target, action)

    async def admin(self, server=""):
        """Send an ADMIN command."""
        await self.send_items('ADMIN', server)

    async def cap(self, subcommand, *args):
        """
        Send a CAP command according to `the spec
        <http://ircv3.atheme.org/specification/capability-negotiation-3.1>`_.

        Arguments:

            subcommand -- LS, LIST, REQ, ACK, CLEAR, END
            args -- capabilities, if required for given subcommand

        Example:

            .cap('LS')
            .cap('REQ', 'multi-prefix', 'sasl')
            .cap('END')
        """
        cap_subcommands = set('LS LIST REQ ACK NAK CLEAR END'.split())
        client_subcommands = set(cap_subcommands) - {'NAK'}
        assert subcommand in client_subcommands, "invalid subcommand"

        def _multi_parameter(args):
            """
            According to the spec::

                If more than one capability is named, the RFC1459 designated
                sentinel (:) for a multi-parameter argument must be present.

            It's not obvious where the sentinel should be present or if it
            must be omitted for a single parameter, so follow convention and
            only include the sentinel prefixed to the first parameter if more
            than one parameter is present.
            """
            if len(args) > 1:
                return (':' + args[0],) + args[1:]
            return args

        await self.send_items('CAP', subcommand, *_multi_parameter(args))

    async def ctcp(self, ctcptype, target, parameter=""):
        """Send a CTCP command."""
        ctcptype = ctcptype.upper()
        tmpl = (
            "\001{ctcptype} {parameter}\001" if parameter else
            "\001{ctcptype}\001"
        )
        await self.privmsg(target, tmpl.format(**vars()))

    async def ctcp_reply(self, target, parameter):
        """Send a CTCP REPLY command."""
        await self.notice(target, "\001%s\001" % parameter)

    async def globops(self, text):
        """Send a GLOBOPS command."""
        await self.send_items('GLOBOPS', ':' + text)

    async def info(self, server=""):
        """Send an INFO command."""
        await self.send_items('INFO', server)

    async def invite(self, nick, channel):
        """Send an INVITE command."""
        await self.send_items('INVITE', nick, channel)

    async def ison(self, nicks):
        """Send an ISON command.

        Arguments:

            nicks -- List of nicks.
        """
        await self.send_items('ISON', *tuple(nicks))

    async def join(self, channel, key=""):
        """Send a JOIN command."""
        await self.send_items('JOIN', channel, key)

    async def kick(self, channel, nick, comment=""):
        """Send a KICK command."""
        await self.send_items('KICK', channel, nick, comment and ':' + comment)

    async def links(self, remote_server="", server_mask=""):
        """Send a LINKS command."""
        await self.send_items('LINKS', remote_server, server_mask)

    async def list(self, channels=None, server=""):
        """Send a LIST command."""
        await self.send_items('LIST', ','.join(channels), server)

    async def lusers(self, server=""):
        """Send a LUSERS command."""
        await self.send_items('LUSERS', server)

    async def mode(self, target, command):
        """Send a MODE command."""
        await self.send_items('MODE', target, command)

    async def motd(self, server=""):
        """Send an MOTD command."""
        await self.send_items('MOTD', server)

    async def names(self, channels=None):
        """Send a NAMES command."""
        if isinstance(channels, str):
            channels = [channels]
        await self.send_items('NAMES', ','.join(channels))

    async def nick(self, newnick):
        """Send a NICK command."""
        await self.send_items('NICK', newnick)

    async def notice(self, target, text):
        """Send a NOTICE command."""
        # Should limit len(text) here!
        await self.send_items('NOTICE', target, ':' + text)

    async def oper(self, nick, password):
        """Send an OPER command."""
        await self.send_items('OPER', nick, password)

    async def part(self, channels, message=""):
        """Send a PART command."""
        await self.send_items('PART', ','.join(channels), message)

    async def pass_(self, password):
        """Send a PASS command."""
        await self.send_items('PASS', password)

    async def ping(self, target, target2=""):
        """Send a PING command."""
        await self.send_items('PING', target, target2)

    async def pong(self, target, target2=""):
        """Send a PONG command."""
        await self.send_items('PONG', target, target2)

    async def privmsg(self, target, text):
        """Send a PRIVMSG command."""
        await self.send_items('PRIVMSG', target, ':' + text)

    async def privmsg_many(self, targets, text):
        """Send a PRIVMSG command to multiple targets."""
        target = ','.join(targets)
        return await self.privmsg(target, text)

    async def quit(self, message=""):
        """Send a QUIT command."""
        # Note that many IRC servers don't use your QUIT message
        # unless you've been connected for at least 5 minutes!
        await self.send_items('QUIT', message and ':' + message)

    async def squit(self, server, comment=""):
        """Send an SQUIT command."""
        await self.send_items('SQUIT', server, comment and ':' + comment)

    async def stats(self, statstype, server=""):
        """Send a STATS command."""
        await self.send_items('STATS', statstype, server)

    async def time(self, server=""):
        """Send a TIME command."""
        await self.send_items('TIME', server)

    async def topic(self, channel, new_topic=None):
        """Send a TOPIC command."""
        await self.send_items('TOPIC', channel, new_topic and ':' + new_topic)

    async def trace(self, target=""):
        """Send a TRACE command."""
        await self.send_items('TRACE', target)

    async def user(self, username, realname):
        """Send a USER command."""
        cmd = 'USER {username} 0 * :{realname}'.format(**locals())
        await self.send_raw(cmd)

    async def userhost(self, nicks):
        """Send a USERHOST command."""
        await self.send_items('USERHOST', ",".join(nicks))

    async def users(self, server=""):
        """Send a USERS command."""
        await self.send_items('USERS', server)

    async def version(self, server=""):
        """Send a VERSION command."""
        await self.send_items('VERSION', server)

    async def wallops(self, text):
        """Send a WALLOPS command."""
        await self.send_items('WALLOPS', ':' + text)

    async def who(self, target="", op=""):
        """Send a WHO command."""
        await self.send_items('WHO', target, op and 'o')

    async def whois(self, targets):
        """Send a WHOIS command."""
        await self.send_items('WHOIS', ",".join(targets))

    async def whowas(self, nick, max="", server=""):
        """Send a WHOWAS command."""
        await self.send_items('WHOWAS', nick, max, server)


class Event(object):
    """
    An IRC event.

    >>> print(Event('privmsg', '@somebody', '#channel'))
    type: privmsg, source: @somebody, target: #channel, arguments: [], tags: []
    """
    def __init__(self, type, source, target, arguments=None, tags=None):
        """
        Initialize an Event.

        Arguments:

            type -- A string describing the event.

            source -- The originator of the event (a nick mask or a server).

            target -- The target of the event (a nick or a channel).

            arguments -- Any event-specific arguments.
        """
        self.type = type
        self.source = source
        self.target = target
        if arguments is None:
            arguments = []
        self.arguments = arguments
        if tags is None:
            tags = []
        self.tags = tags

    @property
    def args(self):
        return ' '.join(self.arguments)

    def __str__(self):
        tmpl = (
            "type: {type}, "
            "source: {source}, "
            "target: {target}, "
            "arguments: {arguments}, "
            "tags: {tags}"
        )
        return tmpl.format(**vars(self))

    def __repr__(self):
        args = [repr(self.type), repr(self.source), repr(self.target)]
        if self.arguments:
            args.append('arguments=' + repr(self.arguments))
        if self.tags:
            args.append('tags=' + repr(self.tags))
        return '%s(%s)' % (self.__class__.__name__, ', '.join(args))


def is_channel(string):
    """Check if a string is a channel name.

    Returns true if the argument is a channel name, otherwise false.
    """
    return string and string[0] in "#&+!"

def ip_numstr_to_quad(num):
    """
    Convert an IP number as an integer given in ASCII
    representation to an IP address string.

    >>> ip_numstr_to_quad('3232235521')
    '192.168.0.1'
    >>> ip_numstr_to_quad(3232235521)
    '192.168.0.1'
    """
    n = int(num)
    packed = struct.pack('>L', n)
    bytes = struct.unpack('BBBB', packed)
    return ".".join(map(str, bytes))

def ip_quad_to_numstr(quad):
    """
    Convert an IP address string (e.g. '192.168.0.1') to an IP
    number as a base-10 integer given in ASCII representation.

    >>> ip_quad_to_numstr('192.168.0.1')
    '3232235521'
    """
    bytes = map(int, quad.split("."))
    packed = struct.pack('BBBB', *bytes)
    return str(struct.unpack('>L', packed)[0])

class NickMask(six.text_type):
    """
    A nickmask (the source of an Event)

    >>> nm = NickMask('pinky!username@example.com')
    >>> nm.nick
    'pinky'

    >>> nm.host
    'example.com'

    >>> nm.user
    'username'

    >>> isinstance(nm, six.text_type)
    True

    >>> nm = 'красный!red@yahoo.ru'
    >>> if not six.PY3: nm = nm.decode('utf-8')
    >>> nm = NickMask(nm)

    >>> isinstance(nm.nick, six.text_type)
    True

    Some messages omit the userhost. In that case, None is returned.

    >>> nm = NickMask('irc.server.net')
    >>> nm.nick
    'irc.server.net'
    >>> nm.userhost
    >>> nm.host
    >>> nm.user
    """
    @classmethod
    def from_params(cls, nick, user, host):
        return cls('{nick}!{user}@{host}'.format(**vars()))

    @property
    def nick(self):
        nick, sep, userhost = self.partition("!")
        return nick

    @property
    def userhost(self):
        nick, sep, userhost = self.partition("!")
        return userhost or None

    @property
    def host(self):
        nick, sep, userhost = self.partition("!")
        user, sep, host = userhost.partition('@')
        return host or None

    @property
    def user(self):
        nick, sep, userhost = self.partition("!")
        user, sep, host = userhost.partition('@')
        return user or None

    @classmethod
    def from_group(cls, group):
        return cls(group) if group else None
