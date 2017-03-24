"""
rq worker customizations
 - dont fork per job
 - use compressed msg pack messages
"""
import msgpack
#from lz4.frame import compress, decompress
from rq.worker import Worker
from rq import job

def dumps(o):
    #return compress(msgpack.packb(o))
    return msgpack.packb(o)

def loads(s):
    #return msgpack.unpackb(decompress(s))
    return msgpack.unpackb(s)

job.dumps = dumps
job.loads = loads


class SalactusWorker(Worker):
    """Get rid of process boundary, maintain worker status.

    We rely on supervisord for process supervision, and we want
    to be able to cache sts sessions per process to avoid role
    assume storms.
    """

    def execute_job(self, job, queue):
        self.set_state('busy')
        self.perform_job(job, queue)
        self.set_state('idle')
        

    
