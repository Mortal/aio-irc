import re

from handlers.hostnotify import create_and_show_notification


RULES = {
    '!flagpole': r'^(?=.*(\btop\b|\bback|\bfast|\bgrab)).*flag ?pole.*\?',
    # !flagpole
    # 'is lost level the only game you turn around at the flagpole?'
    # "why always the top of the flag pole? Would think less time to run it down? Maybe it doesn't matter cause the flag still has to come down?"
    # 'is there any reason to grab the flagpole backwards?'
    # 'My bad, i was curious about lost levels and the frame rule. i just heard you mention it, so im assuming this one does have frame rules.'
    # 'I thought it was faster to grab the pole at the bottom of it, no?'
    # 'Ok'

    '!fireworks': r'^(?=.*\b(count|amount)).*\bcoin.*\?',
    # !fireworks
    # 'What does having a certain amount of coins do?'
    # "@brawlofthewest That wasn't a 9 on the timer but no fireworks... I don't understand..."
    # 'what does the coin count matter?'

    '!wr': r'\bmany\b.*\brecord.*\?',
    # !wrs
    # 'Is darbian a record holder?'
    # 'How many world records as he got?'

    '!differences': r'difference.*\?',
    # !differences
    # "Is there a reason it's on super Mario all stars is there version differences besides the graphics?"

    '!prime': r'\bcrown\b.*\?',
    # !prime
    # 'What does my crown mean?'

    '!race': r'\bvoices\b.*\?',
    # !race
    # 'im so confused. where r the voices coming from'

    '!discord': r'\bdiscord.*\?',
    # !discord
    # 'Is there a public darb discord?'

    '!agdq': r'adgq.*\?',
    # !agdq
    # 'what are you running at AGDQ??'

    '!age': r'how old.*\?',
    # !age
    # 'How old is darbian?'

    '!category': r'd-4 (mean|stand).*\?',
    # !category
    # '@Darbian what is d-4 means my man?'
    # 'what does d-4 means?'
    # 'what does d-4 mean im new kinda lol'
    # 'what does D-4 mean?'
    # 
    # !pedal
    # 'how are the splits marked? is there a button darb hits (with his foot?) or is it automatic or software or?'

    '!parens': r'(\bnumbers? in.*\bparen|\(\d\)).*\?',
    # !parens
    # 'what does 7-3 (6) mean'
    # 'what does it mean where it says (4) and (6) etc'

    '!bowser': r'\b(kill|fast).*bowser.*\?',
    # !bowser
    # 'is it faster to kill bowser even if you make it past him?'

    '!framerules': r'frame ?rule.*\?',
    # !framerules
    # "Sorry for the amateur question but what's a frame rule?"

    '!capcard': r'\bhow.*\bstream\b.*\b(console|snes)',

    'darbian\'s real name is Brad which is darb backwards':
    r'^(?=.*\bdarb).*\bname\b.*\?',

    '!elena': r'who(\'| i)?s elena\?',

    '!8-1 smb1_any': r'\b(good|bad).*\bjudge.*\?',

    'no problem DarbiansGame': r'\bthank(s| ?(you|u\b)).*\bmort(able*)?\b',
}


try:
    last_buffer_set
except NameError:
    last_buffer_set = None


class Handler:
    async def load(self, client):
        self.client = client

    def get_command(self, msg):
        for command, pattern in RULES.items():
            if re.search(pattern, msg, re.I):
                return command

    async def handle_pubmsg(self, connection, event):
        tags = {
            k: v
            for kv in (event.tags or ())
            for k, v in [(kv['key'], kv['value'])]
        }
        name = tags.get('display-name') or event.source.nick
        if name == 'dbSRL':
            return
        command = self.get_command(event.args)
        if command is None:
            return
        line = '%s @%s' % (command, name)
        create_and_show_notification(
            line, '%s: %s' % (name, event.args), key='helpful')
        self.client.set_default_msg(line)
