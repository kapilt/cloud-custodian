# Copyright 2017-2018 Capital One Services, LLC
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
"""Utility functions
"""
from datetime import datetime
from dateutil.parser import parse as date_parse
from dateutil.tz import tzutc
from dateutil import zoneinfo

import json
import functools
import humanize


def unwrap(msg):

    data = None
    if 'Body' in msg:
        data = json.loads(msg['Body'])
    elif 'Message' in msg:
        data = json.loads(msg['Message'])
    else:
        raise ValueError("unknown msg: %s" % msg)

    if 'Message' in data:
        data = json.loads(data['Message'])

    return data


def row_factory(cursor, row):
    """Returns a sqlite row factory that returns a dictionary"""
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d


human_size = functools.partial(humanize.naturalsize, gnu=True)


def get_dates(start, end, tz):
    mytz = tz and zoneinfo.gettz(tz) or tzutc()
    start = date_parse(start).replace(tzinfo=mytz)
    if end:
        end = date_parse(end).replace(tzinfo=mytz)
    else:
        end = datetime.now().replace(tzinfo=mytz)
    if tz:
        start = start.astimezone(tzutc())
        if end:
            end = end.astimezone(tzutc())
    if start > end:
        start, end = end, start
    return start, end


def get_queue(queue):
    if queue.startswith('https://queue.amazonaws.com'):
        region = 'us-east-1'
        queue_url = queue
    elif queue.startswith('https://sqs.'):
        region = queue.split('.', 2)[1]
        queue_url = queue
    elif queue.startswith('arn:sqs'):
        queue_arn_split = queue.split(':', 5)
        region = queue_arn_split[3]
        owner_id = queue_arn_split[4]
        queue_name = queue_arn_split[5]
        queue_url = "https://sqs.%s.amazonaws.com/%s/%s" % (
            region, owner_id, queue_name)
    return queue_url, region
