from rq.worker import Worker


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
        

    
