import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from service import NotificationService


class ServiceTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.received = []
        async def send(target, text):
            if 'bad' in target:
                raise RuntimeError('test failure')
            self.received.append((target, text))
        self.service = NotificationService(Path(self.tmp.name) / 'data.sqlite', send)
        self.channel = self.service.save_channel({'name': '签到', 'targets': ['qq:GroupMessage:bad', 'qq:FriendMessage:123']})
        self.event = {'version': 1, 'event_id': 'event-1', 'results': [{'name': '甲', 'ok': True}]}

    async def asyncTearDown(self):
        await self.service.close()
        self.tmp.cleanup()

    def accept(self, event=None, token=None, module='checkin'):
        return self.service.accept(module, self.channel['id'], token or self.channel['token'], event or self.event)

    async def test_allowlist_failure_isolation_and_deduplication(self):
        self.assertEqual(self.accept()[0], 202)
        self.assertEqual(self.accept()[0], 200)
        await self.service.deliver_one('checkin')
        await self.service.deliver_one('checkin')
        self.assertEqual([x[0] for x in self.received], ['qq:FriendMessage:123'])
        self.assertEqual(self.service.status()['checkin']['pending'], 1)

    async def test_channel_token_module_and_disabled_boundaries(self):
        self.assertEqual(self.accept(token='wrong')[0], 401)
        self.assertEqual(self.accept(module='course')[0], 401)
        rotated = self.service.rotate(self.channel['id'])
        self.assertEqual(self.accept()[0], 401)
        rotated['enabled'] = False
        self.service.save_channel(rotated)
        self.assertEqual(self.accept(token=rotated['token'])[0], 403)

    async def test_broken_module_does_not_disable_checkin(self):
        course = self.service.save_channel({'name': '抢课', 'module': 'course', 'enabled': True, 'targets': ['qq:GroupMessage:456']})
        def broken(_): raise RuntimeError('broken extension')
        self.service.modules['course'] = broken
        self.assertEqual(self.service.accept('course', course['id'], course['token'], self.event)[0], 500)
        self.assertEqual(self.accept()[0], 202)
        await self.service.deliver_one('checkin')
        await self.service.deliver_one('checkin')
        self.assertEqual(len(self.received), 1)

    async def test_module_import_failure_is_isolated(self):
        import importlib
        original = importlib.import_module
        def load(name):
            if name.endswith('.course'): raise ImportError('broken module')
            return original(name)
        with patch('service.importlib.import_module', side_effect=load):
            other = NotificationService(':memory:', self.service.send)
        self.assertIn('checkin', other.modules)
        self.assertNotIn('course', other.modules)
        await other.close()

    async def test_timeout_does_not_block_other_module_worker(self):
        async def slow(target, text):
            if target.endswith('slow'): await asyncio.sleep(60)
            else: self.received.append((target, text))
        self.service.send, self.service.send_timeout = slow, .01
        self.channel = self.service.save_channel({**self.channel, 'targets': ['qq:GroupMessage:slow', 'qq:FriendMessage:123']})
        self.accept()
        await asyncio.gather(self.service.deliver_one('checkin'), self.service.deliver_one('checkin'))
        self.assertEqual(len(self.received), 1)

    async def test_outbox_and_dedup_survive_restart(self):
        self.accept()
        await self.service.close()
        self.service = NotificationService(Path(self.tmp.name) / 'data.sqlite', lambda *_: None)
        self.assertEqual(self.accept()[1]['duplicate'], True)
        self.assertEqual(self.service.status()['checkin']['pending'], 2)

    async def test_notification_never_contains_arbitrary_payload(self):
        self.event.update(password='secret', cookie='cookie', url='secret-url')
        self.event['results'][0].update(error='secret cookie', password='secret')
        self.accept()
        await self.service.deliver_one('checkin')
        await self.service.deliver_one('checkin')
        self.assertNotIn('secret', self.received[0][1])

if __name__ == '__main__': unittest.main()
