"""Translate user-facing QQ numbers to AstrBot's internal message destinations."""
import re


def qq_numbers(value, label):
    if isinstance(value, str):
        if len(value) > 10000:
            raise ValueError('接收人数过多')
        value = [x for x in re.split(r'[\s,，;；]+', value.strip()) if x]
    if not isinstance(value, list) or len(value) > 100:
        raise ValueError(f'{label}格式不正确')
    result = []
    for item in value:
        if not isinstance(item, str) or not re.fullmatch(r'[1-9][0-9]{4,19}', item.strip()):
            raise ValueError(f'{label}请填写 5–20 位数字，多个号码可换行或用逗号分隔')
        if item.strip() not in result:
            result.append(item.strip())
    return result


def resolve_targets(value):
    if 'platform_id' not in value:
        return value.get('targets', [])  # Existing clients/channels remain compatible.
    platform = value['platform_id']
    if not isinstance(platform, str) or not platform.strip() or len(platform) > 150 or any(
        char in platform for char in ':\r\n\t'
    ):
        raise ValueError('请选择一个 QQ 机器人')
    platform = platform.strip()
    groups = qq_numbers(value.get('group_ids', []), '群号')
    users = qq_numbers(value.get('user_ids', []), '私聊 QQ 号')
    if not groups and not users:
        raise ValueError('请至少填写一个通知群号或私聊 QQ 号')
    return ([f'{platform}:GroupMessage:{number}' for number in groups] +
            [f'{platform}:FriendMessage:{number}' for number in users])


def recipient_fields(channel):
    """Derive fields from actual delivery targets, including pre-2.1 channels."""
    platform, groups, users = None, [], []
    for target in channel.get('targets', []):
        parts = target.split(':', 2)
        if len(parts) != 3 or not re.fullmatch(r'[1-9][0-9]{4,19}', parts[2]):
            return {'legacy': True}
        if platform is not None and platform != parts[0]:
            return {'legacy': True}
        platform = parts[0]
        if parts[1] == 'GroupMessage':
            groups.append(parts[2])
        elif parts[1] == 'FriendMessage':
            users.append(parts[2])
        else:
            return {'legacy': True}
    return {'legacy': False, 'platform_id': platform or '', 'group_ids': groups, 'user_ids': users}


def qq_platforms(context):
    """Only return safe display fields, never adapter credentials."""
    result = []
    for config in context.get_config().get('platform', []):
        if config.get('type') != 'aiocqhttp' or not config.get('id'):
            continue
        platform_id = str(config['id'])
        instance = context.get_platform_inst(platform_id)
        status = 'stopped' if config.get('enable', True) else 'disabled'
        if instance is not None:
            status = getattr(getattr(instance, 'status', None), 'value', status)
        result.append({'id': platform_id, 'label': str(config.get('name') or platform_id), 'status': status})
    return result
