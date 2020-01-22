## Background 

In order to enable consistent and better functional testing across
providers, we want to start using terraform to enable provisioning of
resources for functional tests. At least for the AWS provider
historically functionally testing has been via decorating tests with
the functional decorator, *when* the tests also encode the api calls
to setup their pre-conditions (infrastructure resources and
state). The AWS functional tests are not exercised regularly. The
Azure provider currently does this via a set of deployment manager
template that are provisioned pre test execution. The Azure provider
tests are now being run nightly in a azure DevOps pipeline. Neither
gcp nor k8s providers have functional tests atm.


### Goals 

High level goal is to allow for tests to specify their pre-conditions
in terraform modules.

specific goals

 - allow tests to specify independent terraform root modules
 - allow tests to specify shared terraform root modules
 - allow tests to layer a shared and independent terraform root
   modules (network, security groups)
 - allow for concurrent provisioning and execution of independent
   tests terraform root modules
 - tests should have access to the resources ids / types of the provisioned resources.
 - supports live/functional and replay tests
 - allow for streaming terraform provisioning output (helpful for
   debugging resources that take a long time to provision).
 - terraform test root modules should be able to references root
   modules provisioned at higher scopes.

### Challenges

pytest is our current testing tool of choice (and effectively the
defacto ecosystem testing tool), but we're looking at some mismatches
on feature sets to its builtin capabilities, which need to be worked
through.

 - pytest fixtures injection has poor compatibility with
   unittest.TestCase derived classes
 - pytest doesn't allow arguments to fixtures, fixture specification
   to a test is based solely on implicit name matching.
 - pytest has static scopes (function, module, package, session)
 - coordination of fixture creation has to be done on a global basis
   with barriers when running distributed / multi-process via
   pytest-xdist.

 - auto promote fixture referenced at multiple levels or err conflict


### Example usage

Putting out a straw example for iteration

```python

class SecurityGroupNetworkTest(unitest.TestCase):

     # terraform stack specific to this function
     @terraform_aws('tf_sg', scope='function')
     # terraform shared stack
     @terraform_aws('tf_vpc')
     def test_foobar(self, tf_vpc, tf_sg):
            # probably need to qualify with the name of the terraform resource, might be able to 
            # alias sans the common provider prefix to lesson the repetition.
            vpc_ids = tf_vpc.resources['aws_vpc'].values()
            sg_ids = tf_sg.resources['aws_security_group'].values()
```

underneath the hood the terraform_aws is actually generating and
caching fixtures, and ideally these decorators should also support
classes for declaring on a whole set of tests. ala


```python

@terraform_aws('tf_sqs', scope='class')
class SQSTest(unittest.TestCase):
     def test_xyz(self, tf_sqs):
           """ gets class scoped resources"""

     def test_abc(self, tf_sqs):
           """ gets class scoped resources"""

     @terraform_aws('tf_sqs_nmo', scope='function')
     def test_nmo(self, tf_sqs_nmo, tf_sqs):
          """gets function scoped resources and class resources"""
  
```

### Concurrent Provisioning

To enable concurrent provisioning of terraform modules, we'll need to
impose one restriction on test execution namely that its single host,
so removing support for fully distributed modes. In turn this allows
us to trade out a need for a remote network server for coordination,
and enables us to use 'simple' file locking.. except file locking
isn't particularly simple

http://0pointer.de/blog/projects/locking.html
https://gavv.github.io/articles/file-locks/
https://dmorgan.info/posts/linux-lock-files/

otoh we could also simply defer to sqlite which allows multi-reader /
single writer semantics. The other aspect to enabling test execution
concurrency, is generally that we want tests that are mutating
resources to get their own copy of the resource, which means we'll
have a general guidance against hardcoding resource ids (or using
unique ones), and instead introduce some randomness via builtin in
terraform capabilities to enable that. in many cases resource ids
returned for a resource are autogen'd (vpcs/instance ids/etc) thought
not in all, so we'll need to return the provisioned resources back to
the test via the fixture return value.

Concurrency also introduces some interesting complications for test
scheduling and scope, by using distributed locking the intent is that
we don't have to do any additional work/modifications to the builtin
scheduling and scope and existing parameters to the xdist scheduler
work ootb. this does require us to have a known path for coordination,
we'll likely need to use the pytest extension mechanism to hook the
initialization and cleanup, and that will need some ordering
guarantees around teardown for the lock file cleanup post terraform
fixtures teardown.

### Terraform init

all of the independent root modules will require terraform init, which
will download the requisite providers. to amortize the cost of that
across the root modules, we should do a one time init of all of them,
and then copy that directory as a working directory for future
terraform executions. we may need to have users specify the full
provider set in config else we'll need to do a complete scan of root
terraform modules to determine extant providers.

### Fixture Resources

the tests will need to access fixture provisioned resources, to do so
the fixture will return a terraform resources instance for each
terraform root module fixture which will have available a mapping of
terraform resource type names to terraform resource names to provider
ids, which will be inferred from the tfstate.json.

### Replay support

For tests executing with replay we'll need to store the fixture
resource id mapping and serialize them to disk from a live
provisioning run to enable a replay run. On replay we'll pick up the
serialized resource ids and return them as the fixture results. We'll
need to do this once per scope instantiation (session, module,
package, function). Note this will be effectively be an independent
mechanism from the existing one as it needs to handled pre test
execution, where as the current record/replay mechanism is done within
a test execution. Some of the DRY violation could be addressed by
refactoring the existing mechanisms to look at fixture decorated
attribute on the test instance.

Configuring record vs replay

--tf-record=false|no
--tf-replay=yes

### Root module references

`terraform_remote_state` can be used to introduce a dependency between
a scoped root modules on an individual test, note we are not
attempting to support same scope inter fixture dependencies as that
imposes additional scheduling constraints outside of pytest native
capabilities. The higher scoped root module will need to have output
variables to enable this consumption.



