
# Automated Setup for AWS Guard Duty

A cli tool for automating multi-account of aws guard duty. Given a
config file holding a set of account information, this cli will setup
one as a master account, and the remainder as member accounts.

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

```
policies:
  - name: ec2-port-scanner
    mode:
      type: guard-duty
    filters:
      - type: event
```      