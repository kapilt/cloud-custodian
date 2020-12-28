# Copyright The Cloud Custodian Authors.
# SPDX-License-Identifier: Apache-2.0
import jmespath
from pytest_terraform import terraform
from unittest import TestCase

from .common import event_data, BaseTest

from c7n.cwe import CloudWatchEvents


@terraform('event_bridge_bus')
def test_event_bus_describe(test, event_bridge_bus):
    factory = test.replay_flight_data('test_cwe_bus_xaccount')
    p = test.load_policy({
        'name': 'bus-xaccount',
        'resource': 'aws.event-bus',
        'filters': [
            {'tag:Env': 'Sandbox'},
            'cross-account',],
        }, session_factory=factory)
    resources = p.run()
    assert len(resources) == 1
    resources[0]['Name'] == event_bridge_bus[
        'aws_cloudwatch_event_bus.messenger.name']
    assert 'CrossAccountViolations' in resources[0]


class CloudWatchEventTest(BaseTest):

    def test_event_rule_tags(self):
        factory = self.replay_flight_data('test_cwe_rule_tags')
        client = factory().client('events')
        policy = self.load_policy(
            {
                'name': 'cwe-rule',
                'resource': 'aws.event-rule',
                'filters': [
                    {'tag:App': 'absent'},
                    {'Name': 'cloud-custodian-mailer'}],
                'actions': [
                    {'type': 'tag', 'tags': {'App': 'Custodian'}}]
            }, session_factory=factory, config={'region': 'us-west-2'})
        resources = policy.run()
        self.assertEqual(len(resources), 1)
        tags = {t['Key']: t['Value'] for t in
                client.list_tags_for_resource(
                    ResourceARN=policy.resource_manager.get_arns(resources)[0]).get(
                        'Tags')}
        self.assertEqual(tags, {'App': 'Custodian'})

    def test_target_cross_account_remove(self):
        session_factory = self.replay_flight_data("test_cwe_rule_target_cross")
        client = session_factory().client("events")
        policy = self.load_policy(
            {
                "name": "cwe-cross-account",
                "resource": "event-rule-target",
                "filters": [{"type": "cross-account"}],
                "actions": ["delete"],
            },
            session_factory=session_factory,
        )
        resources = policy.run()
        self.assertEqual(len(resources), 1)
        targets = client.list_targets_by_rule(Rule=resources[0]["c7n:parent-id"]).get(
            "Targets"
        )
        self.assertEqual(targets, [])


class CloudWatchEventsFacadeTest(TestCase):

    def test_get_ids(self):
        self.assertEqual(
            CloudWatchEvents.get_ids(
                {"detail": event_data("event-cloud-trail-run-instances.json")},
                {"type": "cloudtrail", "events": ["RunInstances"]},
            ),
            ["i-784cdacd", "i-7b4cdace"],
        )

    def test_get_ids_sans_with_details_expr(self):
        self.assertEqual(
            CloudWatchEvents.get_ids(
                {'detail': event_data('event-cloud-trail-run-instances.json')},
                {'type': 'cloudtrail', 'events': [
                    {'ids': 'detail.responseElements.instancesSet.items[].instanceId',
                     'source': 'ec2.amazonaws.com',
                     'event': 'RunInstances'}]}),
            ["i-784cdacd", "i-7b4cdace"],
        )

    def test_get_ids_sans_without_details_expr(self):
        self.assertEqual(
            sorted(CloudWatchEvents.get_ids(
                {'detail': event_data('event-cloud-trail-run-instances.json')},
                {'type': 'cloudtrail', 'events': [
                    {'ids': 'responseElements.instancesSet.items[].instanceId',
                     'source': 'ec2.amazonaws.com',
                     'event': 'RunInstances'}
                ]})),
            ["i-784cdacd", "i-7b4cdace"],
        )

    def test_get_ids_multiple_events(self):
        d = event_data("event-cloud-trail-run-instances.json")
        d["eventName"] = "StartInstances"

        self.assertEqual(
            CloudWatchEvents.get_ids(
                {"detail": d},
                {
                    "type": "cloudtrail",
                    "events": [
                        # wrong event name
                        {
                            "source": "ec2.amazonaws.com",
                            "event": "CreateTags",
                            "ids": "requestParameters.resourcesSet.items[].resourceId",
                        },
                        # wrong event source
                        {
                            "source": "ecs.amazonaws.com",
                            "event": "StartInstances",
                            "ids": "responseElements.instancesSet.items",
                        },
                        # matches no resource ids
                        {
                            "source": "ec2.amazonaws.com",
                            "event": "StartInstances",
                            "ids": "responseElements.instancesSet2.items[].instanceId",
                        },
                        # correct
                        {
                            "source": "ec2.amazonaws.com",
                            "event": "StartInstances",
                            "ids": "responseElements.instancesSet.items[].instanceId",
                        },
                        # we don't fall off the end
                        {
                            "source": "ec2.amazonaws.com",
                            "event": "StartInstances",
                            "ids": "responseElements.instancesSet.items[]",
                        },
                    ],
                },
            ),
            ["i-784cdacd", u"i-7b4cdace"],
        )

    def test_ec2_state(self):
        self.assertEqual(
            CloudWatchEvents.get_ids(
                event_data("event-instance-state.json"), {"type": "ec2-instance-state"}
            ),
            ["i-a2d74f12"],
        )

    def test_asg_state(self):
        self.assertEqual(
            CloudWatchEvents.get_ids(
                event_data("event-asg-instance-failed.json"),
                {
                    "type": "asg-instance-state",
                    "events": ["EC2 Instance Launch Unsuccessful"],
                },
            ),
            ["CustodianTest"],
        )

    def test_custom_event(self):
        d = {"detail": event_data("event-cloud-trail-run-instances.json")}
        d["detail"]["eventName"] = "StartInstances"
        self.assertEqual(
            CloudWatchEvents.get_ids(
                d,
                {
                    "type": "cloudtrail",
                    "events": [
                        {
                            "event": "StartInstances",
                            "ids": "responseElements.instancesSet.items[].instanceId",
                            "source": "ec2.amazonaws.com",
                        }
                    ],
                },
            ),
            ["i-784cdacd", u"i-7b4cdace"],
        )

    def test_non_cloud_trail_event(self):
        for event in ["event-instance-state.json", "event-scheduled.json"]:
            self.assertFalse(CloudWatchEvents.match(event_data(event)))

    def test_cloud_trail_resource(self):
        self.assertEqual(
            CloudWatchEvents.match(event_data("event-cloud-trail-s3.json")),
            {
                "source": "s3.amazonaws.com",
                "ids": jmespath.compile("detail.requestParameters.bucketName"),
            },
        )
