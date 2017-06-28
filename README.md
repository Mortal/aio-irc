IRC client with semi-automatic triggers
=======================================

This terminal-based IRC client has a few automatic and semi-automatic triggers
for subscriber's of [darbian's Twitch channel](https://twitch.tv/darbian).

Installation
------------

* Install [Python 3.6](https://www.python.org/).

* Download the code.

* In a terminal, navigate to the directory containing this README and type `python3.6 -m aiotwirc`.

Configuration
-------------

You need to create a [Twitch Chat OAuth Password](http://twitchapps.com/tmi/).

Create a file called `twitchconfig.py` in the same directory as this README containing something like:

```
USERNAME = 'Mortable'
PASSWORD = 'oauth:s1xinrwq9ds2u3kf7nkqrglo3no7he'
CHANNELS = ['darbian']
HIGHLIGHT = r'(?i)\b(mortable)\b'
PLUGINS = [
    'say',
    'ping',
    'log',
    'sub',
    'elena',
    'highlight',
    'hostnotify',
    'helpful',
    'eval',
]
```

The `USERNAME` should be your Twitch username
and the `PASSWORD` entry should be changed to your OAuth password.
The `HIGHLIGHT` entry is a regex which matches your nick and
anything else you want to be highlighted about.

The `PLUGINS` list is a list of plugins (located in the `handlers` directory).
They are:

* `say` **(required)**: Allows you to write in chat.
* `ping` **(required)**: Sends PING to the IRC server and responds to PINGs from the server.
* `log` **(required)**: Displays incoming messages on the terminal.
* `sub`: Automatically sends sub emotes when someone subscribes to darbian's channel.
* `elena`: Automatically sends emotes when Elena speaks in darbian's channel.
* `highlight`: Sends a desktop notification (Linux only) when someone mentions your name in chat.
* `hostnotify`: Automatically opens your webbrowser when darbian starts streaming.
* `helpful`: Pre-fill a chat message when someone poses a frequently asked question in chat.
* `eval`: Allows you to use `/exec` and `/eval` to run Python code.
