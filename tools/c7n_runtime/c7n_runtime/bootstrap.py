#!/usr/bin/python3
# Copyright 2019 Amazon.com, Inc. or its affiliates.
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

import json
import os
import site
import sys
import urllib.request as request
import time

if "LAMBDA_TASK_ROOT" in os.environ:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'python'))
    site.addsitedir(os.path.join(os.path.dirname(__file__), 'python'))

from c7n.exceptions import PolicyValidationError  # noqa: 402
from c7n.config import Config  # noqa: 402
from c7n.policy import load  # noqa: 402
from c7n.utils import dumps  # noqa: 402

HANDLER = os.getenv("_HANDLER")
RUNTIME_API = os.getenv("AWS_LAMBDA_RUNTIME_API")


class LambdaContext(object):
    def __init__(self, request_id, invoked_function_arn, deadline_ms, trace_id):
        self.aws_request_id = request_id
        self.deadline_ms = deadline_ms
        self.invoked_function_arn = invoked_function_arn
        self.trace_id = trace_id

        self.function_name = os.getenv("AWS_LAMBDA_FUNCTION_NAME")
        self.function_version = os.getenv("AWS_LAMBDA_FUNCTION_VERSION")
        self.log_group_name = os.getenv("AWS_LAMBDA_LOG_GROUP_NAME")
        self.log_stream_name = os.getenv("AWS_LAMBDA_LOG_STREAM_NAME")
        self.memory_limit_in_mb = os.getenv("AWS_LAMBDA_FUNCTION_MEMORY_SIZE")

        if self.trace_id is not None:
            os.environ["_X_AMZN_TRACE_ID"] = self.trace_id

    def get_remaining_time_in_millis(self):
        if self.deadline_ms is not None:
            return time.time() * 1000 - int(self.deadline_ms)


# Runtime API
def init_error(message, type):
    details = {"errorMessage": message, "errorType": type}
    details = json.dumps(details).encode("utf-8")
    req = request.Request(
        "http://%s/2018-06-01/runtime/init/error" % RUNTIME_API,
        details, {"Content-Type": "application/json"})
    with request.urlopen(req) as res:
        res.read()


def invocation_error(request_id, error):
    details = {"errorMessage": str(error), "errorType": type(error).__name__}
    details = json.dumps(details).encode("utf-8")
    req = request.Request(
        "http://%s/2018-06-01/runtime/invocation/%s/error" % (
            RUNTIME_API, request_id),
        details, {"Content-Type": "application/json"})
    with request.urlopen(req) as res:
        res.read()


def next_invocation():
    with request.urlopen(
        "http://%s/2018-06-01/runtime/invocation/next" % RUNTIME_API
    ) as res:
        request_id = res.getheader("lambda-runtime-aws-request-id")
        invoked_function_arn = res.getheader(
            "lambda-runtime-invoked-function-arn")
        deadline_ms = res.getheader("lambda-runtime-deadline-ms")
        trace_id = res.getheader("lambda-runtime-trace-id")
        event_payload = res.read()
    event = json.loads(event_payload.decode("utf-8"))
    context = LambdaContext(
        request_id, invoked_function_arn, deadline_ms, trace_id)
    return request_id, event, context


def invocation_response(request_id, handler_response):
    if not isinstance(handler_response, (bytes, str)):
        handler_response = dumps(handler_response)
    if not isinstance(handler_response, bytes):
        handler_response = handler_response.encode("utf-8")
    req = request.Request(
        "http://%s/2018-06-01/runtime/invocation/%s/response"
        % (RUNTIME_API, request_id),
        handler_response, {"Content-Type": "application/json"})
    with request.urlopen(req) as res:
        res.read()


# Runloop
def main():
    for runtime_var in ["AWS_LAMBDA_RUNTIME_API", "_HANDLER"]:
        if runtime_var not in os.environ:
            init_error(
                "%s environment variable not set" % runtime_var,
                "RuntimeError")
            sys.exit(1)

    policy_path = os.path.join(os.environ['LAMBDA_TASK_ROOT'], HANDLER)
    if not os.path.exists(policy_path):
        init_error(
            "Bad handler value error: invalid policy file", "ValueError")
        sys.exit(1)

    try:
        policies = load(Config.empty(output_dir='/tmp'), policy_path)
    except PolicyValidationError as e:
        init_error("Invalid policy file error: %s" % (str(e)),
                   "ValueError")
        sys.exit(1)

    while True:
        request_id, event, context = next_invocation()
        try:
            for p in policies:
                handler_response = p.push(event, context)
        except Exception as e:
            invocation_error(request_id, e)
        else:
            invocation_response(request_id, handler_response)


if __name__ == '__main__':
    main()
