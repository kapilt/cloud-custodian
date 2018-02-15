import logging

from c7n.log import CloudWatchLogHandler

log = logging.getLogger('custodian.output')


class LogOutput(object):

    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

    def __init__(self, ctx):
        self.ctx = ctx

    def get_handler(self):
        raise NotImplementedError()

    def __enter__(self):
        log.debug("Storing output with %s" % repr(self))
        self.join_log()
        return self

    def __exit__(self, exc_type=None, exc_value=None, exc_traceback=None):
        self.leave_log()
        if exc_type is not None:
            log.exception("Error while executing policy")

    def join_log(self):
        self.handler = self.get_handler()
        self.handler.setLevel(logging.DEBUG)
        self.handler.setFormatter(logging.Formatter(self.log_format))
        mlog = logging.getLogger('custodian')
        mlog.addHandler(self.handler)

    def leave_log(self):
        mlog = logging.getLogger('custodian')
        mlog.removeHandler(self.handler)
        self.handler.flush()
        self.handler.close()


class CloudWatchLogOutput(LogOutput):

    log_format = '%(asctime)s - %(levelname)s - %(name)s - %(message)s'

    def get_handler(self):
        return CloudWatchLogHandler(
            log_group=self.ctx.options.log_group,
            log_stream=self.ctx.policy.name,
            session_factory=lambda x=None: self.ctx.session_factory(
                assume=False))

    def __repr__(self):
        return "<%s to group:%s stream:%s>" % (
            self.__class__.__name__,
            self.ctx.options.log_group,
            self.ctx.policy.name)

