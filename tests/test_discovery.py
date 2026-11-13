import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from discovery import recipient_from_event
from service import NotificationService


class At:
    def __init__(self, qq): self.qq = qq


def event(kind='GroupMessage', platform='official', group='A1'*16, sender='member', session=None, mention=True, name='测试群'):
    session = session if session is not None else group if kind == 'GroupMessage' else 'private-session'
    return SimpleNamespace(
        get_message_type=lambda: SimpleNamespace(value=kind), get_platform_id=lambda: platform,
        get_sender_id=lambda: sender, get_self_id=lambda: 'bot', get_sender_name=lambda: name,
        get_group_id=lambda: group, get_messages=lambda: [At('bot' if mention else 'other'), object()],
        unified_msg_origin=f'{platform}:{kind}:{session}',
        message_obj=SimpleNamespace(group=SimpleNamespace(group_name=name), message_str='not stored', raw_message={'password':'not stored'}))


class DiscoveryTest(unittest.TestCase):
    def test_only_bot_mentions_and_private_messages_are_recorded(self):
        self.assertIsNone(recipient_from_event(event(mention=False), At))
        self.assertIsNone(recipient_from_event(event(sender='bot'), At))
        self.assertIsNone(recipient_from_event(event(kind='OtherMessage'), At))
        group = recipient_from_event(event(), At)
        user = recipient_from_event(event(kind='FriendMessage', mention=False), At)
        self.assertEqual(group['kind'], 'group')
        self.assertEqual(user['kind'], 'user')
        self.assertTrue(user['target'].endswith(':private-session'))
        self.assertEqual(set(group), {'target','platform_id','kind','name'})

    def test_member_isolation_does_not_duplicate_the_group(self):
        group = 'B2'*16
        first = recipient_from_event(event(sender='member1', group=group, session='member1_'+group), At)
        second = recipient_from_event(event(sender='member2', group=group, session='member2_'+group), At)
        self.assertEqual(first['target'], second['target'])
        self.assertEqual(first['target'], 'official:GroupMessage:'+group)

    def test_opaque_session_ids_keep_platform_and_delivery_route(self):
        received = recipient_from_event(event(platform='matrix', group='!room:example.org', name='<群名>'), At)
        self.assertEqual(received['target'], 'matrix:GroupMessage:!room:example.org')
        private = recipient_from_event(event(kind='FriendMessage', session='dm-channel', sender='user-id'), At)
        self.assertTrue(private['target'].endswith(':dm-channel'))
        invalid = event();invalid.unified_msg_origin='another:GroupMessage:wrong'
        self.assertIsNone(recipient_from_event(invalid, At))

    def test_recording_is_durable_deduplicated_and_keeps_alias_without_subscribing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'notifications.sqlite'
            service = NotificationService(path, None)
            recipient = recipient_from_event(event(name='课程群'), At)
            service.record_recipient(recipient)
            service.rename_recipient(recipient['target'], '高数通知群')
            service.record_recipient({**recipient, 'name':''})
            self.assertEqual(service.channels(), [])
            self.assertEqual(service.db.execute('SELECT count(*) FROM deliveries').fetchone()[0], 0)
            service.db.close()
            reopened = NotificationService(path, None)
            self.assertEqual(len(reopened.recipients()), 1)
            self.assertEqual(reopened.recipients()[0]['alias'], '高数通知群')
            self.assertEqual(reopened.recipients()[0]['name'], '课程群')
            reopened.db.close()

    def test_picker_rejects_unseen_and_cross_bot_targets(self):
        service = NotificationService(':memory:', None)
        group = recipient_from_event(event(), At)
        user = recipient_from_event(event(kind='FriendMessage'), At)
        other = recipient_from_event(event(platform='other'), At)
        for item in [group,user,other]: service.record_recipient(item)
        payload = {'name':'选择通知','platform_id':'official','recipient_targets':[group['target'],user['target']]}
        channel = service.save_channel(payload)
        self.assertEqual(channel['targets'], payload['recipient_targets'])
        for targets in [[],[other['target']],['official:FriendMessage:unseen'],[group['target']]*31]:
            with self.subTest(targets=targets), self.assertRaises(ValueError):
                service.save_channel({**payload, 'recipient_targets':targets})
        service.db.close()

    def test_old_channel_and_api_survive_picker_edit_before_new_interaction(self):
        service = NotificationService(':memory:', None)
        old = service.save_channel({'name':'旧通道','targets':['official:GroupMessage:old-openid']})
        self.assertFalse(service.recipients()[0]['observed'])
        edited = service.save_channel({'id':old['id'],'name':'改名称','platform_id':'official','recipient_targets':old['targets']})
        self.assertEqual((old['id'],old['token'],old['targets']), (edited['id'],edited['token'],edited['targets']))
        with self.assertRaises(ValueError): service.rename_recipient(old['targets'][0], '备注')
        service.db.close()
