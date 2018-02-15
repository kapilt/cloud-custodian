import datetime
import gzip
import logging
import shutil
import tempfile
import os

from boto3.s3.transfer import S3Transfer
from c7n.utils import parse_s3

from .log import LogOutput, log


class FSOutput(LogOutput):

    @staticmethod
    def select(path):
        if path.startswith('s3://'):
            return S3Output
        else:
            return DirectoryOutput

    @staticmethod
    def join(*parts):
        return os.path.join(*parts)

    def __init__(self, ctx):
        super(FSOutput, self).__init__(ctx)
        self.root_dir = self.ctx.output_path or tempfile.mkdtemp()

    def get_handler(self):
        return logging.FileHandler(
            os.path.join(self.root_dir, 'custodian-run.log'))

    def compress(self):
        # Compress files individually so thats easy to walk them, without
        # downloading tar and extracting.
        for root, dirs, files in os.walk(self.root_dir):
            for f in files:
                fp = os.path.join(root, f)
                with gzip.open(fp + ".gz", "wb", compresslevel=7) as zfh:
                    with open(fp, "rb") as sfh:
                        shutil.copyfileobj(sfh, zfh, length=2**15)
                    os.remove(fp)

    def use_s3(self):
        raise NotImplementedError()  # pragma: no cover


class DirectoryOutput(FSOutput):

    permissions = ()

    def __init__(self, ctx):
        super(DirectoryOutput, self).__init__(ctx)
        if self.ctx.output_path is not None:
            if not os.path.exists(self.ctx.output_path):
                os.makedirs(self.ctx.output_path)

    def __repr__(self):
        return "<%s to dir:%s>" % (self.__class__.__name__, self.root_dir)

    def use_s3(self):
        return False


class S3Output(FSOutput):
    """
    Usage:

    .. code-block:: python

       with S3Output(session_factory, 's3://bucket/prefix'):
           log.info('xyz')  # -> log messages sent to custodian-run.log.gz

    """

    permissions = ('S3:PutObject',)

    def __init__(self, ctx):
        super(S3Output, self).__init__(ctx)
        self.date_path = datetime.datetime.now().strftime('%Y/%m/%d/%H')
        self.s3_path, self.bucket, self.key_prefix = parse_s3(
            self.ctx.output_path)
        self.root_dir = tempfile.mkdtemp()
        self.transfer = None

    def __repr__(self):
        return "<%s to bucket:%s prefix:%s>" % (
            self.__class__.__name__,
            self.bucket,
            "%s/%s" % (self.key_prefix, self.date_path))

    @staticmethod
    def join(*parts):
        return "/".join([s.strip('/') for s in parts])

    def __exit__(self, exc_type=None, exc_value=None, exc_traceback=None):
        if exc_type is not None:
            log.exception("Error while executing policy")
        log.debug("Uploading policy logs")
        self.leave_log()
        self.compress()
        self.transfer = S3Transfer(
            self.ctx.session_factory(assume=False).client('s3'))
        self.upload()
        shutil.rmtree(self.root_dir)
        log.debug("Policy Logs uploaded")

    def upload(self):
        for root, dirs, files in os.walk(self.root_dir):
            for f in files:
                key = "%s/%s%s" % (
                    self.key_prefix,
                    self.date_path,
                    "%s/%s" % (
                        root[len(self.root_dir):], f))
                key = key.strip('/')
                self.transfer.upload_file(
                    os.path.join(root, f), self.bucket, key,
                    extra_args={
                        'ServerSideEncryption': 'AES256'})

    def use_s3(self):
        return True
