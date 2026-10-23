"""Channel handler registry. `services.notify()` looks up a channel here by
name; a notification type can list a channel in `registry.py` before a
handler exists for it (the dispatch simply skips channels with no handler),
so new channels land additively without touching the registry or callers."""
from .email import EmailChannel
from .push import PushChannel
from .sms import SMSChannel
from .whatsapp import WhatsAppChannel

HANDLERS = {
    'email': EmailChannel(),
    'push': PushChannel(),
    'sms': SMSChannel(),
    'whatsapp': WhatsAppChannel(),
}


def get(channel):
    return HANDLERS.get(channel)
