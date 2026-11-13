import asyncio
from sys import maxsize
from pathlib import Path
from aiohttp import web
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star
from astrbot.api.platform import Platform
from astrbot.api.message_components import At
from astrbot.api.web import error_response, json_response, request
from astrbot.core.utils.astrbot_path import get_astrbot_data_path
from .service import NotificationService
from .targets import notification_platforms, prepare_destination, recipient_fields
from .discovery import recipient_from_event

class NJUPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config, self.runner, self.service = config, None, None
        for path, handler, methods in [
            ('channels', self.channels, ['GET']), ('channels/save', self.save_channel, ['POST']),
            ('channels/delete', self.delete_channel, ['POST']), ('channels/rotate', self.rotate_channel, ['POST']),
            ('recipients/rename', self.rename_recipient, ['POST'])]:
            context.register_web_api('/astrbot_plugin_nju/' + path, handler, methods, 'NJU 通知管理')

    async def initialize(self):
        directory = Path(get_astrbot_data_path()) / 'plugin_data' / 'astrbot_plugin_nju'
        directory.mkdir(parents=True, exist_ok=True)
        async def send(target, text):
            instance = self.context.get_platform_inst(target.split(':', 1)[0])
            prepare_destination(instance, target, Platform.send_by_session)
            sent = await self.context.send_message(target, MessageChain().message(text))
            if sent is False:
                raise RuntimeError('平台未找到或拒绝发送')
        self.service = NotificationService(directory / 'notifications.sqlite', send)
        self.service.start()
        app = web.Application(client_max_size=256 * 1024)
        app.router.add_post('/api/v1/{module}/{channel}/{token}', self.receive)
        self.runner = web.AppRunner(app, access_log=None)
        try:
            await self.runner.setup()
            await web.TCPSite(self.runner, self.config.get('listen_host', '0.0.0.0'), int(self.config.get('listen_port', 9285))).start()
        except Exception:
            await self.terminate()
            raise
        logger.info('NJU小工具管理bot 通知接口已启动；请在插件通知通道视图复制地址')

    async def receive(self, req):
        try:
            body = await req.json()
            status, result = self.service.accept(req.match_info['module'], req.match_info['channel'], req.match_info['token'], body)
            return web.json_response(result, status=status, headers={'Cache-Control': 'no-store'})
        except (ValueError, TypeError):
            return web.json_response({'error': '通知格式不正确'}, status=400)

    def _url(self, channel):
        base = self.config.get('public_base_url', '').rstrip('/')
        return f"{base}/api/v1/{channel['module']}/{channel['id']}/{channel['token']}" if base else ''

    async def channels(self):
        if self.service is None:
            return error_response('通知服务尚未就绪', status_code=503)
        return json_response({'channels': [{**c, **recipient_fields(c), 'url': self._url(c)} for c in self.service.channels()],
                              'recipients': self.service.recipients(),
                              'platforms': notification_platforms(self.context, Platform.send_by_session),
                              'public_base_url': self.config.get('public_base_url', ''), 'modules': self.service.status()})

    async def save_channel(self):
        try:
            payload = await request.json(default={})
            if not isinstance(payload, dict):
                raise ValueError('配置格式不正确')
            id_format = 'qq_number'
            if 'platform_id' in payload:
                selected = next((p for p in notification_platforms(self.context, Platform.send_by_session)
                                 if p['id'] == payload['platform_id']), None)
                if selected is None:
                    raise ValueError('所选机器人已不存在，请刷新列表后重选')
                if selected['proactive'] is False and payload.get('enabled', payload.get('module', 'checkin') == 'checkin'):
                    raise ValueError('该适配器不支持主动通知，只能将通道保存为关闭状态')
                id_format = selected['id_format']
            channel = self.service.save_channel(payload, id_format=id_format)
            return json_response({**channel, **recipient_fields(channel), 'url': self._url(channel)})
        except (ValueError, TypeError) as error:
            return error_response(str(error), status_code=400)

    async def delete_channel(self):
        payload = await request.json(default={})
        self.service.delete_channel(str(payload.get('id', '')))
        return json_response({'ok': True})

    async def rotate_channel(self):
        payload = await request.json(default={})
        try:
            channel = self.service.rotate(str(payload.get('id', '')))
            return json_response({**channel, 'url': self._url(channel)})
        except ValueError as error:
            return error_response(str(error), status_code=400)

    async def rename_recipient(self):
        try:
            payload = await request.json(default={})
            if not isinstance(payload, dict) or not isinstance(payload.get('target'), str):
                raise ValueError('请选择接收目标')
            self.service.rename_recipient(payload['target'], payload.get('alias', ''))
            return json_response({'ok': True})
        except (ValueError, TypeError) as error:
            return error_response(str(error), status_code=400)

    @filter.event_message_type(filter.EventMessageType.ALL, priority=maxsize)
    async def discover_recipient(self, event: AstrMessageEvent):
        """Record mentioned groups and private conversations without replying."""
        if self.service is None:
            return
        try:
            recipient = recipient_from_event(event, At)
            if recipient:
                self.service.record_recipient(recipient)
        except Exception:
            # Discovery must not stop command handling or notification workers.
            logger.warning('NJU 接收目标记录暂时失败，不影响其他功能')

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command('nju会话')
    async def session(self, event: AstrMessageEvent):
        """在接收通知的群聊或私聊中获取会话标识，填入通知通道。"""
        yield event.plain_result('当前通知会话标识：\n' + event.unified_msg_origin)

    async def terminate(self):
        if self.runner:
            await self.runner.cleanup()
            self.runner = None
        if self.service:
            await self.service.close()
            self.service = None
