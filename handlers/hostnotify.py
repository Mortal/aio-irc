import webbrowser
from aiotwirc.timer import spamming


try:
    notify2
except NameError:
    import notify2
    notify2.init('aiotwirc')

try:
    notifications
except NameError:
    notifications = {}


def create_and_show_notification(summary, message, icon=None, key=None):
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

    async def handle_hosttarget(self, connection, event):
        hosting_channel = event.target.lstrip('#')
        args = ' '.join(event.arguments)
        target_channel = args.split()[0]
        if target_channel == '-':
            summary = f'{hosting_channel}: Exit host mode'
            message = f'{hosting_channel} is no longer in host mode.'
        else:
            summary = f'{hosting_channel}: Hosting {target_channel}'
            message = f'{hosting_channel} is now hosting {target_channel}.'
        create_and_show_notification(summary, message, key='hosttarget')
        if target_channel == '-' and not spamming(60):
            webbrowser.open('https://twitch.tv/' + hosting_channel)
        if hosting_channel == 'darbian' and target_channel == '-':
            self.client.set_default_msg(
                'darbBro hi chat, hi darb, good luck on the runs tonight!')
