"""Protocol-aware recipients routed through AstrBot's platform adapters."""
import re


def target_ids(value, label, id_format='qq_number'):
    if isinstance(value, str):
        if len(value) > 10000:
            raise ValueError('接收人数过多')
        value = [x for x in re.split(r'[\s,，;；]+', value.strip()) if x]
    if not isinstance(value, list) or len(value) > 100:
        raise ValueError(f'{label}格式不正确')
    result = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f'{label}必须是文本，多个目标可换行或用逗号分隔')
        item = item.strip()
        if id_format == 'qq_number':
            if not re.fullmatch(r'[1-9][0-9]{4,19}', item):
                raise ValueError(f'{label}请填写 5–20 位数字，多个号码可换行或用逗号分隔')
        elif not 1 <= len(item) <= 200 or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in item):
            raise ValueError(f'{label}请填写 1–200 字符的目标 ID，不能包含空白或控制字符')
        if item.strip() not in result:
            result.append(item.strip())
    return result


def resolve_targets(value, id_format='qq_number'):
    if 'platform_id' not in value:
        return value.get('targets', [])  # Existing clients/channels remain compatible.
    platform = value['platform_id']
    if not isinstance(platform, str) or not platform.strip() or len(platform) > 150 or any(
        char in platform for char in ':\r\n\t'
    ):
        raise ValueError('请选择一个发送通知的机器人')
    platform = platform.strip()
    groups = target_ids(value.get('group_ids', []), '群聊目标', id_format)
    users = target_ids(value.get('user_ids', []), '私聊目标', id_format)
    if not groups and not users:
        raise ValueError('请至少填写一个群聊或私聊接收目标')
    return ([f'{platform}:GroupMessage:{number}' for number in groups] +
            [f'{platform}:FriendMessage:{number}' for number in users])


def recipient_fields(channel):
    """Derive fields from actual delivery targets, including pre-2.1 channels."""
    platform, groups, users = None, [], []
    for target in channel.get('targets', []):
        parts = target.split(':', 2)
        if len(parts) != 3 or not parts[2] or any(char.isspace() or ord(char) < 32 for char in parts[2]):
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


def address_spec(platform_type):
    spec = {
        'protocol_label': platform_type, 'id_format': 'platform_id', 'group_label': '群聊 / 频道 ID', 'user_label': '私聊会话 ID',
        'group_placeholder': '填写该协议使用的群聊或频道 ID，多个目标可换行分隔',
        'user_placeholder': '填写该协议使用的私聊目标 ID，多个目标可换行分隔',
        'hint': '请填写所选适配器使用的群聊、频道或私聊目标 ID；具体权限与主动消息限制由平台决定。',
    }
    if platform_type == 'aiocqhttp':
        spec.update(protocol_label='QQ / OneBot v11', id_format='qq_number', group_label='通知群号', user_label='私聊 QQ 号',
                    group_placeholder='填写 QQ 群号，例如：123456789',
                    user_placeholder='填写接收人的 QQ 号，例如：987654321',
                    hint='直接填写群号和 QQ 号；机器人需要已加入目标群，并能与接收人私聊。')
    elif platform_type.startswith('qq_official'):
        spec.update(protocol_label='QQ 官方机器人', group_label='群组 OpenID', user_label='用户 OpenID',
                    group_placeholder='填写 QQ 官方接口提供的群组 OpenID',
                    user_placeholder='填写 QQ 官方接口提供的用户 OpenID',
                    hint='QQ 官方接口使用 OpenID，普通群号和 QQ 号不能代替。平台可能要求先产生消息交互；官方权限、会话状态及主动消息额度仍然生效。')
    elif platform_type == 'telegram':
        spec.update(protocol_label='Telegram', group_label='群聊 / 频道 Chat ID', user_label='私聊 Chat ID',
                    group_placeholder='例如：-1001234567890', user_placeholder='例如：123456789',
                    hint='群聊 Chat ID 可以是负数。机器人须在目标群中，私聊用户需要先与机器人建立会话。')
    elif platform_type == 'discord':
        spec.update(protocol_label='Discord', group_label='频道 ID', user_label='私聊用户 ID',
                    hint='群聊通知填写频道 ID；机器人需要具有目标频道或私聊的发送权限。')
    return spec


def proactive_capability(instance, base_sender=None):
    if instance is None:
        return None
    sender = getattr(instance, 'send_by_session', None)
    if not callable(sender):
        return False
    if base_sender is not None and getattr(sender, '__func__', None) is base_sender:
        return False
    return bool(getattr(instance.meta(), 'support_proactive_message', True))


def prepare_destination(instance, target, base_sender=None):
    if instance is None:
        raise RuntimeError('目标机器人当前未运行')
    if proactive_capability(instance, base_sender) is False:
        raise RuntimeError('目标适配器不支持主动发送通知')
    # AstrBot's official QQ adapter distinguishes group OpenIDs from guild
    # channel IDs using its scene registry. Register explicitly supplied QQ
    # group OpenIDs through its public helper; do not change permissions or quotas.
    parts = target.split(':', 2)
    remember = getattr(instance, 'remember_session_scene', None)
    if (instance.meta().name == 'qq_official' and len(parts) == 3 and
            parts[1] == 'GroupMessage' and re.fullmatch(r'[0-9a-fA-F]{32}', parts[2]) and callable(remember)):
        remember(parts[2], 'group')


def notification_platforms(context, base_sender=None):
    """List all configured protocols; only expose safe fields and capabilities."""
    result = []
    for config in context.get_config().get('platform', []):
        if not isinstance(config, dict) or not config.get('id'):
            continue
        platform_id = str(config['id'])
        platform_type = str(config.get('type') or '')
        status = 'stopped' if config.get('enable', True) else 'disabled'
        capable = None
        try:
            instance = context.get_platform_inst(platform_id)
            if instance is not None:
                status = getattr(getattr(instance, 'status', None), 'value', status)
                capable = proactive_capability(instance, base_sender)
        except Exception:
            status = 'error'  # One faulty adapter must not hide the other choices.
        result.append({'id': platform_id, 'label': str(config.get('name') or platform_id),
                       'type': platform_type, 'status': status, 'proactive': capable,
                       **address_spec(platform_type)})
    return result
