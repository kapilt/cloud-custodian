import json
import sqlite3
import sys
import time


_marker = object()


class KvState:

    Success = 0
    Conflict = 1
    PreConditionFail = 2
    Error = 3


class SqliteKv(object):

    def __init__(self, path, worker='master'):
        self.path = path
        self.db = sqlite3.connect(self.path, isolation_level='DEFERRED')
        self.cursor = self.db.cursor()
        self._closed = False
        self._worker = worker
        self.initialize()

    def initialize(self):
        self.cursor.execute('pragma journal_mode = WAL')
        self.cursor.execute(
            '''
            create table if not exists kv (
            key text,
            worker text,
            data text,
            primary key (key)
            )''')

    def close(self):
        if self._closed:
            return
        self.flush(False)
        self.cursor.close()
        self.conn.close()
        self._closed = True

    def flush(self, save=True):
        if save:
            self.conn.commit()
        elif self._closed:
            return
        else:
            self.conn.rollback()

    def get(self, key):
        try:
            self.cursor.execute(
                'select key, value from kv where key = ?', [key])
            for k, v in self.cursor.fetchall():
                return v
        except Exception as e:
            print('Get Exception: %s' % e, file=sys.stderr)

    def set(self, key, value, expected=_marker):
        if not isinstance(value, str):
            value = json.dumps(value)
        if expected is not _marker and not isinstance(expected, str):
            expected = json.dumps(expected)
        try:
            # self.cursor.execute('begin transaction')
            self.cursor.execute(
                'select key, data from kv where key = ?', [key])
            result = self.cursor.fetchall()
            print('Set Key=%s Val=%s Previous %s' % (
                key, value, result), file=sys.stderr)
            for k, v in result:
                if expected is not _marker and v != expected:
                    return KvState.PreConditionFail

            if not result:
                self.cursor.execute(
                    'insert into kv values (?, ?, ?)',
                    [key, self._worker, value])
            else:
                self.cursor.execute(
                    'update kv set data = ? and worker = ?  where key = ?',
                    [value, self._worker, value])
        except sqlite3.OperationalError as e:
            print(
                "Write Locked %s: %s..." % (self._worker, e), file=sys.stderr)
            self.db.rollback()
            time.sleep(0.01)
            # Retry if db locked
            return self.set(key, value, expected)
        except Exception as e:
            print("Write Exception: '%s' '%s'" % (e, repr(e)), file=sys.stderr)
            self.db.rollback()
            raise ValueError(KvState.Error)
        else:
            print("Write Success %s=%s" % (key, value), file=sys.stderr)
            self.db.execute('commit')
            return KvState.Success


def state_lock(db, worker_id, scope, workload_id):
    db.set('%s-%s' % (scope, workload_id), json.dumps(
        ))


def wait(db, scope, workload_id, poll=5, timeout=120):
    start = time.time()
    while True:
        result = db.get('%s-%s' % (scope, workload_id))
        if result['status'] == 'in-progress':
            time.sleep(poll)
            if time.time() - start > timeout:
                raise RuntimeError(
                    'timeout exceed on scope:%s workload:%s' % (
                        scope, workload_id))
        return result
