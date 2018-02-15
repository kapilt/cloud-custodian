

Outputs


- Named Components

API

  attach
  detach

- context.outputs['metrics'].post()
- context.outputs['fs'].write_path()


components = Outputs.configure(options)
context.outputs = components


for f in policy.filters:
    with execution_context.outputs.element_context():
        f(resources)

config:
  outputs:
    fs:
      type: s3
      key_pattern: ""

    fs:
     type: kinesis

    logs:
      type: cloudwatch
      region: us-east-1
      group: {account_id}

    xray: enabled
    metrics: enabled
    api-stats: enabled
