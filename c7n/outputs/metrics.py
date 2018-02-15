# Copyright 2017 Capital One Services, LLC
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
import datetime
import logging

from c7n.utils import get_retry, local_session

log = logging.getLogger('custodian.output')

DEFAULT_NAMESPACE = "CloudMaid"


class MetricsOutput(object):
    """Send metrics data to cloudwatch
    """

    permissions = ("cloudWatch:PutMetricData",)

    retry = staticmethod(get_retry(('Throttling',)))

    @staticmethod
    def select(metrics_enabled):
        if metrics_enabled:
            return MetricsOutput
        return NullMetricsOutput

    def __init__(self, ctx, namespace=DEFAULT_NAMESPACE):
        self.ctx = ctx
        self.namespace = namespace
        self.buf = []

    def flush(self):
        if self.buf:
            self._put_metrics(self.namespace, self.buf)
            self.buf = []

    def put_metric(self, key, value, unit, buffer=False, **dimensions):
        d = {
            "MetricName": key,
            "Timestamp": datetime.datetime.now(),
            "Value": value,
            "Unit": unit}
        d["Dimensions"] = [
            {"Name": "Policy", "Value": self.ctx.policy.name},
            {"Name": "ResType", "Value": self.ctx.policy.resource_type}]
        for k, v in dimensions.items():
            d['Dimensions'].append({"Name": k, "Value": v})

        if buffer:
            self.buf.append(d)
            # Max metrics in a single request
            if len(self.buf) == 20:
                self.flush()
        else:
            self._put_metrics(self.namespace, [d])

    def _put_metrics(self, ns, metrics):
        watch = local_session(self.ctx.session_factory).client('cloudwatch')
        return self.retry(
            watch.put_metric_data, Namespace=ns, MetricData=metrics)


class NullMetricsOutput(MetricsOutput):

    permissions = ()

    def __init__(self, ctx, namespace=DEFAULT_NAMESPACE):
        super(NullMetricsOutput, self).__init__(ctx, namespace)
        self.data = []

    def _put_metrics(self, ns, metrics):
        self.data.append({'Namespace': ns, 'MetricData': metrics})
        for m in metrics:
            if m['MetricName'] not in ('ActionTime', 'ResourceTime'):
                log.debug(self.format_metric(m))

    def format_metric(self, m):
        label = "metric:%s %s:%s" % (m['MetricName'], m['Unit'], m['Value'])
        for d in m['Dimensions']:
            label += " %s:%s" % (d['Name'].lower(), d['Value'].lower())
        return label
