from rq.worker import Worker


class SalactusWorker(Worker):
    """Get rid of process boundary, maintain worker status.
    """

    def execute_job(self, job, queue):
        self.set_state('busy')
        self.perform_job(job, queue)
        self.set_state('idle')
        

    
