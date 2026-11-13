"""Explicit-field venue notifications; never forward credentials or school responses."""
import re

STATUS_LABELS={'paid':'预约成功，已确认','unpaid':'订单已创建，待确认','failed':'预约失败，请在预约助手查看详情',
               'unknown':'结果待确认，请到学校平台核对，勿重复提交','missed':'错过执行时间'}


def _text(value,limit):
    return ''.join(c for c in str(value or '') if ord(c)>=32 and ord(c)!=127).strip()[:limit]


def format_event(event):
    if not isinstance(event,dict) or event.get('version')!=1:
        raise ValueError('不支持的通知版本')
    event_id=event.get('event_id')
    if not isinstance(event_id,str) or not 1<=len(event_id)<=200:
        raise ValueError('event_id 必须为 1–200 字符')
    if event.get('test') is True:
        return 'NJU 场馆预约通知连接测试\n收到此消息表示当前抢场通道可以接收通知。'
    status=event.get('status')
    reservation=event.get('reservation')
    if status not in STATUS_LABELS or not isinstance(reservation,dict):
        raise ValueError('请提供有效的预约状态和 reservation 对象')
    day=_text(reservation.get('date'),10)
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',day):
        raise ValueError('预约日期需使用 YYYY-MM-DD 格式')
    start,end=(_text(reservation.get(key),5) for key in ['start_time','end_time'])
    for value in [start,end]:
        if value and not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',value):
            raise ValueError('预约时间需使用 HH:MM 格式')
    venue=_text(reservation.get('venue_name'),120)
    site=_text(reservation.get('site_name'),80)
    space=_text(reservation.get('space_name'),80)
    lines=['NJU 场馆预约结果',STATUS_LABELS[status],venue,site,day,
           ' — '.join(x for x in [start,end] if x),space,_text(event.get('finished_at'),40)]
    return '\n'.join(x for x in lines if x)
