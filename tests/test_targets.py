import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from targets import resolve_targets, recipient_fields, qq_platforms
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

    def test_selector_only_exposes_configured_onebot_and_no_secrets(self):
        configs = [{'id':'one','type':'aiocqhttp','enable':True,'token':'secret'},
                   {'id':'two','type':'aiocqhttp','enable':False,'ws_reverse_host':'secret'},
                   {'id':'official','type':'qq_official','appid':'secret'}]
        context = SimpleNamespace(get_config=lambda: {'platform':configs}, get_platform_inst=lambda pid: (
            SimpleNamespace(status=SimpleNamespace(value='running')) if pid=='one' else None))
        self.assertEqual(qq_platforms(context), [
            {'id':'one','label':'one','status':'running'}, {'id':'two','label':'two','status':'disabled'}])
