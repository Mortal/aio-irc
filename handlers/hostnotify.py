import asyncio
import webbrowser
from aiotwirc.timer import spamming


try:
    notify2
except NameError:
    try:
        import notify2
        notify2.init('aiotwirc')
    except ImportError:
        print("Failed to import notify2; disabling desktop notifications")
        notify2 = None

try:
    notifications
except NameError:
    notifications = {}


def create_and_show_notification(summary, message, icon=None, key=None):
    if notify2 is None:
        return
    if icon is None:
        icon = 'notification-message-im'
    if key is None or key not in notifications:
        notification = notify2.Notification(summary, message, icon)
        if key is not None:
            notifications[key] = notification
    else:
        notification = notifications[key]  # type: notify2.Notification
        notification.update(summary, message, icon)
    notification.show()


class Handler:
    async def load(self, client):
        self.client = client
        self.host_mode = {}

    async def handle_hosttarget(self, connection, event):
        hosting_channel = event.target.lstrip('#')
        args = ' '.join(event.arguments)
        target_channel = args.split()[0]
        if target_channel == '-':
            summary = f'{hosting_channel}: Exit host mode'
            message = f'{hosting_channel} is no longer in host mode.'
            self.host_mode[hosting_channel] = 'host_off'
        else:
            summary = f'{hosting_channel}: Hosting {target_channel}'
            message = f'{hosting_channel} is now hosting {target_channel}.'
            self.host_mode[hosting_channel] = 'host_on'
        create_and_show_notification(summary, message, key='hosttarget')
        if target_channel == '-':
            self.client.loop.create_task(self.delayed_open(hosting_channel))

    async def delayed_open(self, hosting_channel):
        # Wait for 1 second and check if the host mode is still 'host_off'.
        await asyncio.sleep(1)
        # If it's 'host_on' or 'host_target_went_offline', don't do anything.
        if self.host_mode[hosting_channel] == 'host_off' and not spamming(60):
            # Probably the stream actually started -- open webbrowser.
            webbrowser.open('https://twitch.tv/' + hosting_channel)
            if hosting_channel == 'darbian':
                self.client.set_default_msg(
                    'darbBro hi chat, hi darb, good luck on the runs tonight!')

    async def handle_pubnotice(self, connection, event):
        hosting_channel = event.target.lstrip('#')
        msg_id = next((o['value'] for o in event.tags if o['key'] == 'msg-id'),
                      None)
        if msg_id in ('host_on', 'host_off', 'host_target_went_offline'):
            self.host_mode[hosting_channel] = msg_id
