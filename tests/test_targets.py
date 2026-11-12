import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from targets import resolve_targets, recipient_fields, notification_platforms, proactive_capability, prepare_destination
from service import NotificationService


class TargetsTest(unittest.TestCase):
    def test_plain_group_and_qq_numbers_with_mixed_separators(self):
        self.assertEqual(resolve_targets({'platform_id': 'my-qq',
            'group_ids': '123456，234567\n123456', 'user_ids': '345678;456789'}), [
                'my-qq:GroupMessage:123456', 'my-qq:GroupMessage:234567',
                'my-qq:FriendMessage:345678', 'my-qq:FriendMessage:456789'])

    def test_group_and_private_can_share_number_without_colliding(self):
        fields = {'platform_id': 'qq', 'group_ids': ['123456'], 'user_ids': ['123456']}
        self.assertEqual(recipient_fields({'targets': resolve_targets(fields)}), {'legacy': False, **fields})

    def test_invalid_numbers_never_turn_into_other_destinations(self):
        for number in ['12345:GroupMessage:99999', 'abc', '012345', '1234', '1e10', '12345/67890', 123456]:
            with self.subTest(number=number), self.assertRaises(ValueError):
                resolve_targets({'platform_id': 'qq', 'group_ids': [number]})
        with self.assertRaises(ValueError): resolve_targets({'platform_id': 'qq', 'group_ids': []})
        with self.assertRaises(ValueError): resolve_targets({'platform_id': 'qq:other', 'group_ids': ['123456']})

    def test_existing_channel_update_preserves_api_and_recipients(self):
        with tempfile.TemporaryDirectory() as folder:
            service = NotificationService(Path(folder)/'data.sqlite', None)
            old = service.save_channel({'name': '原通道', 'targets': ['qq:GroupMessage:123456', 'qq:FriendMessage:234567']})
            updated = service.save_channel({**old, **recipient_fields(old), 'name': '新名称'})
            self.assertEqual(updated['id'], old['id'])
            self.assertEqual(updated['token'], old['token'])
            self.assertEqual(updated['targets'], old['targets'])
            service.db.close()

    def test_multi_bot_legacy_channel_remains_untouched(self):
        old = {'targets': ['qq1:GroupMessage:123456','qq2:FriendMessage:234567']}
        self.assertTrue(recipient_fields(old)['legacy'])
        self.assertEqual(resolve_targets(old), old['targets'])

    def test_all_protocols_are_listed_without_exposing_credentials(self):
        configs = [{'id':'one','type':'aiocqhttp','enable':True,'token':'secret'},
                   {'id':'two','type':'aiocqhttp','enable':False,'ws_reverse_host':'secret'},
                   {'id':'official','type':'qq_official','appid':'secret'},
                   {'id':'tg','type':'telegram','token':'secret'},
                   {'id':'custom','type':'future_protocol','api_key':'secret'}]
        class Sender:
            status = SimpleNamespace(value='running')
            def meta(self): return SimpleNamespace(support_proactive_message=True)
            async def send_by_session(self, *args): pass
        context = SimpleNamespace(get_config=lambda: {'platform':configs}, get_platform_inst=lambda pid: (
            Sender() if pid in ['one','official'] else None))
        platforms = notification_platforms(context)
        self.assertEqual([p['id'] for p in platforms], ['one','two','official','tg','custom'])
        self.assertEqual(platforms[0]['id_format'], 'qq_number')
        self.assertEqual(platforms[2]['id_format'], 'platform_id')
        self.assertEqual(platforms[2]['group_label'], '群组 OpenID')
        self.assertEqual(platforms[3]['group_label'], '群聊 / 频道 Chat ID')
        self.assertEqual(platforms[1]['status'], 'disabled')
        self.assertIsNone(platforms[1]['proactive'])
        self.assertNotIn('secret', str(platforms))

    def test_opaque_ids_and_negative_chat_ids_preserve_routes(self):
        examples = [('telegram', '-1001234567890', '123456789'),
                    ('official', 'groupOpenID_ABC123', 'userOpenID_XYZ789'),
                    ('matrix', '!room:example.org', '!dm:example.org'),
                    ('custom', 'server/channel-42', 'private@chatroom')]
        for platform, group, user in examples:
            with self.subTest(platform=platform):
                targets = resolve_targets({'platform_id':platform,'group_ids':[group],'user_ids':[user]}, 'platform_id')
                self.assertEqual(targets, [f'{platform}:GroupMessage:{group}', f'{platform}:FriendMessage:{user}'])
                self.assertEqual(recipient_fields({'targets':targets}), {
                    'legacy':False,'platform_id':platform,'group_ids':[group],'user_ids':[user]})

    def test_generic_ids_cannot_replace_platform_or_message_type(self):
        target = resolve_targets({'platform_id':'matrix','group_ids':['other:FriendMessage:12345']}, 'platform_id')[0]
        self.assertEqual(target.split(':',2), ['matrix','GroupMessage','other:FriendMessage:12345'])
        for value in ['room\x00bad', 'room\tbad', '', 'a'*201]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                resolve_targets({'platform_id':'matrix','group_ids':[value]}, 'platform_id')

    def test_non_qq_channel_edit_preserves_existing_api_and_targets(self):
        with tempfile.TemporaryDirectory() as folder:
            service = NotificationService(Path(folder)/'data.sqlite', None)
            old = service.save_channel({'name':'旧频道','targets':['matrix:GroupMessage:!room:server.test']})
            new = service.save_channel({**old, **recipient_fields(old),'name':'新名称'}, id_format='platform_id')
            self.assertEqual((new['id'],new['token'],new['targets']), (old['id'],old['token'],old['targets']))
            service.db.close()

    def test_capabilities_distinguish_real_senders_from_unsupported_and_offline(self):
        class Base:
            def meta(self): return SimpleNamespace(support_proactive_message=True)
            async def send_by_session(self, *args): pass
        class Sender(Base):
            async def send_by_session(self, *args): pass
        class Unsupported(Sender):
            def meta(self): return SimpleNamespace(support_proactive_message=False)
        self.assertIsNone(proactive_capability(None, Base.send_by_session))
        self.assertTrue(proactive_capability(Sender(), Base.send_by_session))
        self.assertFalse(proactive_capability(Base(), Base.send_by_session))
        self.assertFalse(proactive_capability(Unsupported(), Base.send_by_session))

    def test_broken_adapter_does_not_hide_other_protocols(self):
        def instance(platform_id):
            if platform_id=='broken': raise RuntimeError('secret configuration')
            return None
        context=SimpleNamespace(get_config=lambda:{'platform':[
            {'id':'broken','type':'custom'}, {'id':'working','type':'telegram'}]}, get_platform_inst=instance)
        platforms=notification_platforms(context)
        self.assertEqual([p['id'] for p in platforms], ['broken','working'])
        self.assertEqual(platforms[0]['status'], 'error')
        self.assertNotIn('secret', str(platforms))

    def test_official_group_openid_uses_public_scene_helper_without_touching_guild_routes(self):
        calls=[]
        class Official:
            def meta(self): return SimpleNamespace(name='qq_official',support_proactive_message=True)
            async def send_by_session(self,*args): pass
            def remember_session_scene(self,session,scene): calls.append((session,scene))
        instance=Official()
        group='A1'*16
        prepare_destination(instance,f'official:GroupMessage:{group}')
        prepare_destination(instance,'official:GroupMessage:123456789012345678')
        prepare_destination(instance,f'official:FriendMessage:{group}')
        self.assertEqual(calls,[(group,'group')])

    def test_missing_and_unsupported_adapters_fail_before_delivery(self):
        class Unsupported:
            def meta(self): return SimpleNamespace(name='unsupported',support_proactive_message=False)
            async def send_by_session(self,*args): self.fail('Must not send')
        for instance in [None,Unsupported()]:
            with self.assertRaises(RuntimeError): prepare_destination(instance,'bot:GroupMessage:12345')
