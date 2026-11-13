import asyncio
import importlib
import json
import secrets
import sqlite3
import time
try:
    from .targets import resolve_targets
except ImportError:  # Standalone unit tests.
    from targets import resolve_targets


class NotificationService:
    """Durable per-recipient outbox and independent module workers."""
    def __init__(self, path, send, send_timeout=8):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS channels(id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(channel TEXT, event TEXT, created REAL, PRIMARY KEY(channel,event));
            CREATE TABLE IF NOT EXISTS recipients(target TEXT PRIMARY KEY, platform_id TEXT NOT NULL,
                kind TEXT NOT NULL, name TEXT NOT NULL DEFAULT '', alias TEXT NOT NULL DEFAULT '', last_seen REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS deliveries(id INTEGER PRIMARY KEY, module TEXT, channel TEXT,
                event TEXT, target TEXT, message TEXT, attempts INTEGER DEFAULT 0,
                due REAL DEFAULT 0, state TEXT DEFAULT 'pending');
            UPDATE deliveries SET state='pending' WHERE state='sending';
            CREATE INDEX IF NOT EXISTS pending_deliveries ON deliveries(module,state,due,id);
        ''')
        self._last_cleanup = 0
        self.cleanup()
        self.send, self.send_timeout = send, send_timeout
        self.workers, self.modules, self.errors = [], {}, {}
        for name in ('checkin', 'course', 'venue'):
            try:
                prefix = f'{__package__}.' if __package__ else ''
                self.modules[name] = importlib.import_module(prefix + 'modules.' + name).format_event
            except Exception:
                self.errors[name] = '模块加载失败'

    def channels(self):
        return [json.loads(row['data']) for row in self.db.execute('SELECT data FROM channels')]

    def get(self, channel_id):
        row = self.db.execute('SELECT data FROM channels WHERE id=?', (channel_id,)).fetchone()
        return json.loads(row['data']) if row else None

    def record_recipient(self, recipient):
        with self.db:
            self.db.execute('''INSERT INTO recipients(target,platform_id,kind,name,last_seen) VALUES (?,?,?,?,?)
                ON CONFLICT(target) DO UPDATE SET
                name=CASE WHEN excluded.name!='' THEN excluded.name ELSE recipients.name END,
                last_seen=excluded.last_seen''',
                (recipient['target'], recipient['platform_id'], recipient['kind'], recipient['name'], time.time()))

    def recipients(self):
        result = {row['target']: {**dict(row), 'observed': True} for row in
                  self.db.execute('SELECT * FROM recipients ORDER BY last_seen DESC')}
        # Old channels remain editable even before their next interaction.
        for channel in self.channels():
            for target in channel['targets']:
                parts = target.split(':', 2)
                if target not in result and len(parts) == 3 and parts[1] in ('GroupMessage', 'FriendMessage'):
                    result[target] = {'target': target, 'platform_id': parts[0],
                                      'kind': 'group' if parts[1] == 'GroupMessage' else 'user',
                                      'name': '', 'alias': '', 'last_seen': None, 'observed': False}
        return list(result.values())

    def rename_recipient(self, target, alias):
        if not isinstance(alias, str) or len(alias) > 80 or any(ord(char) < 32 or ord(char) == 127 for char in alias):
            raise ValueError('备注请填写不超过 80 个字符的单行文本')
        with self.db:
            changed = self.db.execute('UPDATE recipients SET alias=? WHERE target=?', (alias.strip(), target)).rowcount
        if not changed:
            raise ValueError('这个目标尚未自动记录，请先在群里 @机器人或私聊一次')

    def selected_targets(self, value):
        targets = value.get('recipient_targets')
        if not isinstance(targets, list) or not 1 <= len(targets) <= 30 or any(not isinstance(x, str) for x in targets):
            raise ValueError('请勾选 1–30 个接收目标')
        known = {r['target'] for r in self.recipients()}
        platform_id = value.get('platform_id')
        if not isinstance(platform_id, str) or not platform_id:
            raise ValueError('请选择发送消息的机器人')
        if any(target not in known or target.split(':', 1)[0] != platform_id for target in targets):
            raise ValueError('接收目标已变化或不属于所选机器人，请刷新列表后重选')
        return list(dict.fromkeys(targets))

    def save_channel(self, value, id_format='qq_number'):
        if not isinstance(value, dict):
            raise ValueError('配置格式不正确')
        name, module = str(value.get('name', '')).strip(), value.get('module', 'checkin')
        targets = self.selected_targets(value) if 'recipient_targets' in value else resolve_targets(value, id_format)
        if not name or len(name) > 80 or module not in ('checkin', 'course', 'venue'):
            raise ValueError('请填写通道名称并选择有效业务')
        if not isinstance(targets, list) or not 1 <= len(targets) <= 30 or any(
            not isinstance(x, str) or not 1 <= len(x) <= 512 or
            (':GroupMessage:' not in x and ':FriendMessage:' not in x) for x in targets
        ):
            raise ValueError('每个通道请设置 1–30 个有效接收人或群聊')
        enabled = value.get('enabled', module == 'checkin')
        if not isinstance(enabled, bool):
            raise ValueError('enabled 必须为布尔值')
        old = self.get(str(value.get('id', '')))
        if value.get('id') and not old:
            raise ValueError('通道不存在，请刷新后重试')
        if old and old['module'] != module:
            raise ValueError('已有通道不可更换业务，请新建通道')
        if not old and len(self.channels()) >= 100:
            raise ValueError('最多创建 100 个通道')
        channel = dict(id=old['id'] if old else secrets.token_hex(8), name=name, module=module,
                       targets=list(dict.fromkeys(x.strip() for x in targets)), enabled=enabled,
                       token=old['token'] if old else secrets.token_urlsafe(32))
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO channels VALUES (?,?)', (channel['id'], json.dumps(channel)))
        return channel

    def delete_channel(self, channel_id):
        with self.db:
            for table in ('channels', 'deliveries', 'events'):
                self.db.execute(f'DELETE FROM {table} WHERE {"id" if table == "channels" else "channel"}=?', (channel_id,))

    def rotate(self, channel_id):
        channel = self.get(channel_id)
        if not channel:
            raise ValueError('通道不存在')
        channel['token'] = secrets.token_urlsafe(32)
        with self.db:
            self.db.execute('UPDATE channels SET data=? WHERE id=?', (json.dumps(channel), channel_id))
        return channel

    def accept(self, module, channel_id, token, event):
        self.cleanup()
        channel = self.get(channel_id)
        if not channel or channel['module'] != module or not secrets.compare_digest(channel['token'], token):
            return 401, {'error': '通知地址无效或已撤销'}
        if not channel['enabled']:
            return 403, {'error': '通道已关闭'}
        if module not in self.modules:
            return 503, {'error': '业务模块暂不可用'}
        try:
            message = self.modules[module](event)
        except NotImplementedError:
            return 501, {'error': '此业务尚未开放'}
        except (TypeError, ValueError) as error:
            return 400, {'error': str(error)}
        except Exception:
            self.errors[module] = '通知解析失败'
            return 500, {'error': '业务通知处理失败'}
        event_id = event['event_id']
        if self.db.execute('SELECT 1 FROM events WHERE channel=? AND event=?', (channel_id, event_id)).fetchone():
            return 200, {'accepted': True, 'duplicate': True}
        queued = self.db.execute("SELECT count(*) FROM deliveries WHERE module=? AND state='pending'", (module,)).fetchone()[0]
        if queued + len(channel['targets']) > 3000:
            return 429, {'error': '当前业务通知队列已满，请稍后重试'}
        with self.db:
            self.db.execute('INSERT INTO events VALUES (?,?,?)', (channel_id, event_id, time.time()))
            self.db.executemany('INSERT INTO deliveries(module,channel,event,target,message) VALUES (?,?,?,?,?)',
                                [(module, channel_id, event_id, target, message) for target in channel['targets']])
        return 202, {'accepted': True, 'event_id': event_id}

    def cleanup(self):
        now = time.time()
        if now - self._last_cleanup < 3600:
            return
        with self.db:
            self.db.execute('DELETE FROM deliveries WHERE EXISTS (SELECT 1 FROM events e WHERE e.channel=deliveries.channel AND e.event=deliveries.event AND e.created<?)', (now - 7 * 86400,))
            self.db.execute('DELETE FROM events WHERE created<?', (now - 7 * 86400,))
        self._last_cleanup = now

    def start(self):
        for module in self.modules:
            self.workers.extend(asyncio.create_task(self._run(module)) for _ in range(2))

    async def _run(self, module):
        while True:
            try:
                await self.deliver_one(module)
                await asyncio.sleep(0.2)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.errors[module] = '发送异常，正在重试'
                await asyncio.sleep(1)

    async def deliver_one(self, module):
        row = self.db.execute("SELECT * FROM deliveries WHERE module=? AND state='pending' AND due<=? ORDER BY id LIMIT 1", (module, time.time())).fetchone()
        if not row:
            return
        channel = self.get(row['channel'])
        if not channel or row['target'] not in channel['targets']:
            with self.db:
                self.db.execute('DELETE FROM deliveries WHERE id=?', (row['id'],))
            return
        if not channel['enabled']:
            with self.db:
                self.db.execute('UPDATE deliveries SET due=? WHERE id=?', (time.time() + 10, row['id']))
            return
        with self.db:
            self.db.execute("UPDATE deliveries SET state='sending' WHERE id=?", (row['id'],))
        attempts = row['attempts'] + 1
        try:
            await asyncio.wait_for(self.send(row['target'], row['message']), self.send_timeout)
        except asyncio.CancelledError:
            with self.db:
                self.db.execute("UPDATE deliveries SET state='pending' WHERE id=?", (row['id'],))
            raise
        except Exception:
            self.errors[module] = '部分接收会话发送失败，请检查机器人权限及平台限制'
            with self.db:
                self.db.execute('UPDATE deliveries SET state=?,attempts=?,due=? WHERE id=?',
                                ('failed' if attempts >= 3 else 'pending', attempts, time.time() + 10 * attempts, row['id']))
        else:
            with self.db:
                self.db.execute("UPDATE deliveries SET state='sent',attempts=?,message='' WHERE id=?", (attempts, row['id']))

    def status(self):
        return {name: {'available': name in self.modules, 'implemented': name == 'checkin', 'error': self.errors.get(name, ''),
                       'pending': self.db.execute("SELECT count(*) FROM deliveries WHERE module=? AND state IN ('pending','sending')", (name,)).fetchone()[0],
                       'failed': self.db.execute("SELECT count(*) FROM deliveries WHERE module=? AND state='failed'", (name,)).fetchone()[0]}
                for name in ('checkin', 'course', 'venue')}

    async def close(self):
        for task in self.workers:
            task.cancel()
        await asyncio.gather(*self.workers, return_exceptions=True)
        self.db.close()
