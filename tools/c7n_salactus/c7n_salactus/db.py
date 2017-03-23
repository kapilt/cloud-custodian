import json
import os
from collections import Counter

from dateutil.parser import parse

from c7n_salactus.worker import connection as conn


class Database(object):

    def __init__(self, path=None):
        if path:
            with open(os.path.expanduser(path)) as fh:
                self.data = json.load(fh)
        else:
            self.data = get_data()

    def accounts(self, accounts=()):
        accounts = {}
        for k in self.data['bucket-size'].keys():
            a, b = k.split(':')
            accounts.setdefault(a, []).append(k)
        return [Account(a, [Bucket(b, self.data) for b in buckets])
                for a, buckets in accounts.items()]

    def buckets(self, accounts=()):
        if accounts:
            return [
                Bucket(k, self.data) for k in self.data['bucket-size'].keys()
                if k.split(":")[0] in accounts]
        return [Bucket(k, self.data) for k in self.data['keys-scanned'].keys()]

    def save(self, path):
        with open(os.path.expanduser(path), 'w') as fh:
            json.dump(self.data, fh, indent=2)

    def reset_stats(self):
        conn.delete('keys-time')
        conn.delete('keys-count')
        conn.delete('bucket-pages')
        conn.delete('bucket-pages-time')


def db(dbpath=None):
    return Database(dbpath)


class Account(object):

    __slots__ = ('name', 'buckets')

    def __init__(self, name, buckets):
        self.name = name
        self.buckets = buckets

    @property
    def size(self):
        return sum([b.size for b in self.buckets])

    @property
    def matched(self):
        return sum([b.matched for b in self.buckets])

    @property
    def keys_denied(self):
        return sum([b.keys_denied for b in self.buckets])

    @property
    def scanned(self):
        return sum([b.scanned for b in self.buckets])

    @property
    def percent_scanned(self):
        if self.size == 0:
            return 100.0
        size = self.size - sum([b.size for b in self.buckets if b.denied])
        return min(float(self.scanned) / size * 100.0, 100.0)


class Bucket(object):

    __slots__ = ('bucket_id', 'data')

    def __init__(self, bucket_id, data):
        self.bucket_id = bucket_id
        self.data = data

    def __repr__(self):
        return ("<bucket:%s size:%s percent:%s scanned:%s matched:%s "
                "partitions:%d psize:%d denied:%s error:%d>") % (
                    self.bucket_id, self.size, self.percent_scanned,
                    self.scanned, self.matched, self.partitions,
                    self.partition_size, str(self.denied).lower(), self.error_count)

    @property
    def account(self):
        return self.bucket_id.split(':')[0]

    @property
    def name(self):
        return self.bucket_id.split(":")[1]

    @property
    def size(self):
        return int(self.data['bucket-size'].get(self.bucket_id, 0.0))

    @property
    def created(self):
        if 'bucket-age' in self.data:
            return parse(self.data['bucket-age'][self.bucket_id]).strftime("%Y-%m-%d")
        return ''

    @property
    def matched(self):
        return int(self.data['keys-matched'].get(self.bucket_id, 0.0))

    @property
    def scanned(self):
        return int(self.data['keys-scanned'].get(self.bucket_id, 0.0))

    @property
    def partition_size(self):
        return self.size / (self.partitions or 1)

    @property
    def percent_scanned(self):
        if self.size == 0:
            return 100.0
        return min(float(self.scanned) / self.size * 100.0, 100.0)

    @property
    def started(self):
        return self.data['bucket-start'].get(self.bucket_id, 0.0)

    @property
    def partitions(self):
        return int(self.data['bucket-partitions'].get(self.bucket_id, 0.0))

    @property
    def keys_denied(self):
        return int(self.data['keys-denied'].get(self.bucket_id, 0))

    @property
    def denied(self):
        return self.bucket_id in self.data['buckets-denied']

    @property
    def error_count(self):
        return len(self.data['buckets-error'].get(self.bucket_id, ()))

    @property
    def lrate(self):
        return int(
            float(self.data['bucket-pages'].get(self.bucket_id, 0)) /
            float(self.data['bucket-pages-time'].get(self.bucket_id, 1)))

    @property
    def krate(self):
        return int(
            float(self.data['keys-count'].get(self.bucket_id, 0)) /
            float(self.data['keys-time'].get(self.bucket_id, 1)))


def get_data():
    data = {}
    data['bucket-age'] = conn.hgetall('bucket-age')
    data['buckets-denied'] = list(
        conn.smembers('buckets-denied'))
    data['buckets-complete'] = list(
        conn.smembers('buckets-complete'))
    data['buckets-start'] = conn.hgetall('buckets-start')
    data['bucket-partitions'] = {
        k: int(v) for k, v in conn.hgetall('bucket-partition').items()}
    data['buckets-error'] = conn.hgetall(
        'buckets-unknown-errors')
    data['bucket-size'] = {
        k: float(v) for k, v in conn.hgetall('bucket-size').items()}
    data['keys-scanned'] = {
        k: float(v) for k, v in conn.hgetall('keys-scanned').items()}
    data['keys-matched'] = {
        k: float(v) for k, v in conn.hgetall('keys-matched').items()}
    data['keys-denied'] = {
        k: float(v) for k, v in conn.hgetall('keys-denied').items()}
    data['keys-throttled'] = {
        k: float(v) for k, v in conn.hgetall('keys-throttled').items()}
    data['keys-missing'] = {
        k: float(v) for k, v in conn.hgetall('keys-missing').items()}

    # metric/rate stats per period
    data['keys-count'] = {
        k: float(v) for k, v in conn.hgetall('keys-count').items()}
    data['keys-time'] = {
        k: float(v) for k, v in conn.hgetall('keys-time').items()}

    data['bucket-pages'] = {
        k: float(v) for k, v in conn.hgetall('bucket-pages').items()}
    data['bucket-pages-time'] = {
        k: float(v) for k, v in conn.hgetall('bucket-pages-time').items()}

    return data


def agg(d):
    m = Counter()
    if isinstance(d, (set, list)):
        for v in d:
            l, _ = v.split(":", 1)
            m[l] += 1
        return m
    for k, v in d.items():
        l, _ = k.split(":")
        m[l] += int(v)
        return m
