from pytest_terraform import tf


@tf.aws_terraform('tf_sqs', scope='session')
def test_tf_user_a(tf_sqs):
    print("test invoked a")
    print(tf_sqs)


@tf.aws_terraform('tf_sns', scope='function')
def test_tf_user_b(tf_sqs):
    print('test invoked b')


@tf.aws_terraform('tf_sqs', scope='function')
def test_tf_user_c(tf_sqs):
    print('test invoked c')
