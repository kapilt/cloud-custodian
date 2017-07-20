import json
import boto3
import functools
import os

from c7n.utils import dumps


LAMBDA_FUNCS = {}


class Events:
    Kinesis = "kinesis"
    S3 = "s3"
    SNS = "sns"
    Trail = "trail"
    Periodic = "periodic"
    Rpc = 'rpc'
    Unknown = 'unknown'


def classify(event):
    if 'detail-type' in event:
        cwe_type = event['detail-type']
        if cwe_type == 'Scheduled Event' and event['source'] == 'aws.events':
            return event, Events.Periodic
    if 'Payload' in event:
        payload = json.loads(event['Payload'])
        if payload.get('kind') == 'rpc':
            return payload, Events.Rpc
    return event, Events.Unknown


def dispatch(event, context):
    """Dispatch

    perodic and rpc support atm
    """

    event, event_type = classify(event)
    funcs = LAMBDA_FUNCS.get(event_type)
    if event_type == "rpc":
        found = None
        for f in funcs:
            if f.__name__ == event['function']:
                found = f
        if found is None:
            raise ValueError("rpc unknown function %s" % event['function'])
        return found(*event['args'], **event['kwargs'])
    elif event_type == 'perodic':
        for f in funcs:
            f(event, context)
    else:
        raise ValueError("unhandled event %s" % (str(event)))


def lambdafunc(subscribes=(Events.Rpc,)):
    """simple decorator that will auto fan out async style in lambda.

    outside of lambda, this will invoke synchrously.
    """

    def decorator(func):

        if 'AWS_LAMBDA_FUNCTION_NAME' not in os.environ:
            return func

        LAMBDA_FUNCS[func.name] = subscribes

        @functools.wraps(func)
        def scaleout(*args, **kw):
            client = boto3.client('lambda')
            client.invoke(
                FunctionName=os.environ['AWS_LAMBDA_FUNCTION_NAME'],
                InvocationType='Event',
                Payload=dumps({
                    'kind': 'rpc',
                    'function': func.__name__,
                    'args': args,
                    'kwargs': kw}),
                Qualifier=os.environ['AWS_LAMBDA_FUNCTION_VERSION'])
        return scaleout
