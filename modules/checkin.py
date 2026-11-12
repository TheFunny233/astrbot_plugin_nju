def format_event(event):
    if not isinstance(event, dict) or event.get('version') != 1:
        raise ValueError('不支持的通知版本')
    event_id = event.get('event_id')
    if not isinstance(event_id, str) or not 1 <= len(event_id) <= 200:
        raise ValueError('event_id 必须为 1–200 字符')
    if event.get('test') is True:
        return 'NJU 签到通知连接测试\n收到此消息表示当前通道可以发送通知。'
    results = event.get('results')
    if not isinstance(results, list) or not 1 <= len(results) <= 1000:
        raise ValueError('results 必须包含 1–1000 项')
    for item in results:
        if not isinstance(item, dict) or not isinstance(item.get('ok'), bool):
            raise ValueError('每项结果必须有布尔值 ok')
    def clean(value, limit):
        return str(value or '').replace('\n', ' ').replace('\r', ' ')[:limit]
    success = sum(item['ok'] for item in results)
    lines = ['NJU 签到结果', clean(event.get('activity_name', '签到'), 120),
             f'成功 {success} 人，失败 {len(results) - success} 人', clean(event.get('finished_at'), 40)]
    for item in sorted(results, key=lambda x: x['ok'])[:30]:
        name = clean(item.get('name', '未命名'), 40)
        lines.append(f"{'✓' if item['ok'] else '✗'} {name}" + ('' if item['ok'] else '：签到失败，请在客户端查看详情'))
    if len(results) > 30:
        lines.append(f'其余 {len(results) - 30} 人请在客户端查看。')
    return '\n'.join(x for x in lines if x)
