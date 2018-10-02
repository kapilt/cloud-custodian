# Copyright 2018 Capital One Services, LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import base64
import hashlib
import json
import zlib

from c7n.registry import PluginRegistry
from c7n.utils import dumps, get_retry


streams = PluginRegistry('c7n.streams')


class StreamTransport(object):

    BUF_SIZE = 1

    def __init__(self, session, info):
        self.session = session
        self.info = info

    def send(self, message):
        self.buf.append(message)
        if len(self.buf) % self.BUF_SIZE == 0:
            self.flush()

    def flush(self):
        """flush any buffered messages"""
        buf = self.buf
        if not self.buf:
            return
        self.buf = []
        self._flush(buf)

    def close(self):
        self.flush()

    def pack(self, message):
        dumped = dumps(message)
        compressed = zlib.compress(dumped.encode('utf8'))
        b64encoded = base64.b64encode(compressed)
        return b64encoded.decode('ascii')


class KinesisTransport(StreamTransport):

    BUF_SIZE = 50

    retry = staticmethod(get_retry((
        'ProvisionedThroughputExceededException',)))

    def __init__(self, session, info):
        super(KinesisTransport, self).__init__(session, info)
        self.client = self.session.client(
            'kinesis', region_name=info['region'])

    def _flush(self, buf):
        self.retry(
            self.client.put_records,
            StreamName=self.info['resource'],
            Records=[
                {'Data': json.dumps(buf)}])


class SNSTransport(StreamTransport):

    def __init__(self, session, info):
        super(SNSTransport, self).__init__(session, info)
        self.topic_arn, region = self.parse_arn(self.info)
        self.client = self.session.client('sns', region_name=region)

    def parse_arn(self, info):
        topic = info['transport']['topic']
        if topic.startswith('arn:aws:sns'):
            region = topic.split(':', 5)[3]
            topic_arn = topic
        else:
            region = info['region']
            topic_arn = "arn:aws:sns:%s:%s:%s" % (
                region, info['account_id'], topic)
        return topic_arn, region

    def _flush(self, buf):
        message = self.pack(buf)
        self.client.publish(
            TopicArn=self.topic_arn, Message=message)


class SQSTransport(StreamTransport):

    BUF_SIZE = 10

    def __init__(self, session, info):
        super(SQSTransport, self).__init__(session, info)
        self.queue_url, region = self.parse_queue_url(info)
        self.client = self.session.client('sqs', region_name=region)

    def parse_queue_url(self, info):
        queue = self.info['queue']
        if queue.startswith('https://queue.amazonaws.com'):
            region = 'us-east-1'
            queue_url = queue
        elif 'queue.amazonaws.com' in queue:
            region = queue[len('https://'):].split('.', 1)[0]
            queue_url = queue
        elif queue.startswith('https://sqs.'):
            region = queue.split('.', 2)[1]
            queue_url = queue
        elif queue.startswith('arn:aws:sqs'):
            queue_arn_split = queue.split(':', 5)
            region = queue_arn_split[3]
            owner_id = queue_arn_split[4]
            queue_name = queue_arn_split[5]
            queue_url = "https://sqs.%s.amazonaws.com/%s/%s" % (
                region, owner_id, queue_name)
        else:
            region = self.manager.config.region
            owner_id = self.manager.config.account_id
            queue_name = queue
            queue_url = "https://sqs.%s.amazonaws.com/%s/%s" % (
                region, owner_id, queue_name)
        return queue_url, region

    def _flush(self, buf):
        data = self.pack(buf)
        checksum = hashlib.md5(data).hexdigest()
        self.client.send_message_batch(
            QueueUrl=self.queue_url,
            Entries=[{
                'Id': checksum,
                'MessageBody': data}])


class OutputTransport(StreamTransport):

    def send(self, change):
        if self.info.get('format', '') == 'json':
            print(json.dumps(change.data(), indent=2))
        else:
            print(change)
