import asyncio
from pathlib import Path
from aiohttp import web
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star
from astrbot.api.web import error_response, json_response, request
from astrbot.core.utils.astrbot_path import get_astrbot_data_path
from .service import NotificationService
from .targets import qq_platforms, recipient_fields

class NJUPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config, self.runner, self.service = config, None, None
        for path, handler, methods in [
            ('channels', self.channels, ['GET']), ('channels/save', self.save_channel, ['POST']),
            ('channels/delete', self.delete_channel, ['POST']), ('channels/rotate', self.rotate_channel, ['POST'])]:
            context.register_web_api('/astrbot_plugin_nju/' + path, handler, methods, 'NJU 通知管理')

    async def initialize(self):
        directory = Path(get_astrbot_data_path()) / 'plugin_data' / 'astrbot_plugin_nju'
        directory.mkdir(parents=True, exist_ok=True)
        async def send(target, text):
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
        logger.info('NJU 通知接口已启动；请在插件通知通道视图复制地址')

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
                              'platforms': qq_platforms(self.context),
                              'public_base_url': self.config.get('public_base_url', ''), 'modules': self.service.status()})

    async def save_channel(self):
        try:
            payload = await request.json(default={})
            if not isinstance(payload, dict):
                raise ValueError('配置格式不正确')
            if 'platform_id' in payload and payload['platform_id'] not in {p['id'] for p in qq_platforms(self.context)}:
                raise ValueError('所选 QQ 机器人已不存在，请刷新列表后重选')
            channel = self.service.save_channel(payload)
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
