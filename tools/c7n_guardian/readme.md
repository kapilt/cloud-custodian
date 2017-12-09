
# Automated Setup for AWS Guard Duty

Amazon Guard Duty provides for machine learning based threat
intelligence and detection on resources in your aws accounts. This
project provides a cli tool for automating multi-account of aws guard
duty. Given a config file holding a set of account information, this
cli will setup one as a master account, and the remainder as member
accounts.

ie. to enable 
```
 c7n-guardian enable --config accounts.json --master 120312301231 --tags dev
```

Running enable multiple times will idempotently converge.


# Accounts Credentials

The cli needs credentials access to assume the roles in the config
file for all accounts (master and members), the execution credentials
used can be sourced from a profile, or from role assumption in
addition to credential sourcing supported by the aws sdk.


# Using custodian policies for remediation


Here's some example policies that will provision a custodian lambda that
receives the guard duty notifications and performs some basic remediation
on the alerted resources, respectively stopping an ec2 instance, and removing
an access key. You have the full access to custodian's actions and filters
for doing additional activities in response to events.

```

policies:

 - name: ec2-guard-remediate
   resource: ec2
   mode:
     role: arn:aws:iam::{account_id}:role/CustodianPolicyExecution
     type: guard-duty
   actions:
     - stop

 - name: iam-guard-remediate
   resource: iam-user
   mode:
     role: arn:aws:iam::{account_id}:role/CustodianPolicyExecution
     type: guard-duty
   actions:
     - remove-keys
```