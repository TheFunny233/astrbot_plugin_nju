"""Read only routing IDs and display names from inbound messages."""


def _text(value, limit=100):
    return ''.join(char for char in str(value or '') if ord(char) >= 32 and ord(char) != 127).strip()[:limit]


def recipient_from_event(event, at_type):
    message_type = event.get_message_type()
    message_type = getattr(message_type, 'value', message_type)
    if message_type not in ('GroupMessage', 'FriendMessage'):
        return None
    sender, self_id = str(event.get_sender_id() or ''), str(event.get_self_id() or '')
    if sender and sender == self_id:
        return None
    if message_type == 'GroupMessage' and not any(
        isinstance(component, at_type) and self_id and str(component.qq) == self_id
        for component in event.get_messages()
    ):
        return None
    platform_id = str(event.get_platform_id() or '')
    parts = event.unified_msg_origin.split(':', 2)
    if len(parts) != 3 or parts[:2] != [platform_id, message_type] or not parts[2]:
        return None
    session = parts[2]
    if message_type == 'GroupMessage':
        group_id = str(event.get_group_id() or '')
        # Session isolation can prepend the current member's ID. A group must
        # appear once, independent of which member mentions the bot.
        if group_id and session == f'{sender}_{group_id}':
            session = group_id
        group = getattr(event.message_obj, 'group', None)
        name = _text(getattr(group, 'group_name', ''))
        kind = 'group'
    else:
        # Private session IDs can differ from user IDs on some adapters.
        name, kind = _text(event.get_sender_name()), 'user'
    target = f'{platform_id}:{message_type}:{session}'
    if len(target) > 512 or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in target):
        return None
    return {'target': target, 'platform_id': platform_id, 'kind': kind, 'name': name}
