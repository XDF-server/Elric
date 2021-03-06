# -*- coding: utf-8 -*-
from __future__ import (absolute_import, unicode_literals)

import redis
from master.base import BaseMaster
from jobqueue.rqueue import RedisJobQueue
from core.exceptions import JobAlreadyExist, JobDoesNotExist, AlreadyRunningException
from jobstore.memory import MemoryJobStore
from datetime import datetime
from tzlocal import get_localzone
from core.job import Job
from core.utils import timedelta_seconds
from threading import Event, RLock
from xmlrpclib import Binary
from settings import REDIS_HOST, REDIS_PORT


class RQMaster(BaseMaster):

    MAX_WAIT_TIME = 4294967  # Maximum value accepted by Event.wait() on Windows

    def __init__(self, timezone=None):
        BaseMaster.__init__(self)
        self.queue_list = {}
        self.queue_lock = RLock()
        self.server = redis.Redis(host=REDIS_HOST, port=REDIS_PORT)
        self.timezone = timezone or get_localzone()
        self._event = Event()
        self._stopped = True
        self.jobstore = MemoryJobStore(self.log)
        self.jobstore_lock = RLock()

    def submit_job(self, serialized_job, job_key, job_id, replace_exist):
        """
            Receive submit_job rpc request from worker.
            :type serialized_job str or xmlrpclib.Binary
            :type job_key str
            :type job_id str
            :type replace_exist bool
        """
        self.log.debug('client call submit job, id=%s, key=%s' % (job_id, job_key))
        if isinstance(serialized_job, Binary):
            serialized_job = serialized_job.data
        job_in_dict = Job.deserialize_to_dict(serialized_job)
        # if job doesn't contains trigger, then enqueue it into job queue immediately
        if not job_in_dict['trigger']:
            self._enqueue_job(job_key, serialized_job)
        # else store job into job store first
        else:
            # should I need a lock here?
            with self.jobstore_lock:
                try:
                    self.jobstore.add_job(job_id, job_key, job_in_dict['next_run_time'], serialized_job)
                except JobAlreadyExist:
                    if replace_exist:
                        self.jobstore.update_job(job_id, job_key, job_in_dict['next_run_time'], serialized_job)
                    else:
                        self.log.warning('submit job error. job id%s already exist' % job_id)
            # wake up when new job has store into job store
            self.wake_up()

    def update_job(self, job_id, job_key, next_run_time, serialized_job):
        """
            Receive update_job rpc request from worker
            :type job_id: str
            :type job_key: str
            :type next_run_time datetime.datetime
            :type serialized_job str or xmlrpclib.Binary

        """
        if isinstance(serialized_job, Binary):
            serialized_job = serialized_job.data
        with self.jobstore_lock:
            try:
                self.jobstore.update_job(job_id, job_key=job_key, next_run_time=next_run_time,
                                     serialized_job=serialized_job)
            except JobDoesNotExist:
                self.log.error('update job error. job id %s does not exist' % job_id)

    def remove_job(self, job_id):
        """
            Receive remove_job rpc request from worker
            :type job_id: str
        """
        with self.jobstore_lock:
            try:
                self.jobstore.remove_job(job_id)
            except JobDoesNotExist:
                self.log.error('remove job error. job id %s does not exist' % job_id)

    def _enqueue_job(self, key, job):
        """
            enqueue job into redis queue
            :type key: str
            :type job: str or xmlrpc.Binary
        """
        with self.queue_lock:
            try:
                self.queue_list[key].enqueue(job)
            except KeyError:
                self.queue_list[key] = RedisJobQueue(self.server, key)
                self.queue_list[key].enqueue(job)

    def start(self):
        """
            Start elric master. Select all due jobs from jobstore and enqueue them into redis queue.
            Then update due jobs' information into jobstore.
        :return:
        """
        if self.running:
            raise AlreadyRunningException
        self._stopped = False
        self.log.debug('eric master start...')

        while True:
            now = datetime.now(self.timezone)
            wait_seconds = None
            with self.jobstore_lock:
                for job_id, job_key, serialized_job in self.jobstore.get_due_jobs(now):
                    # enqueue due job into redis queue
                    self._enqueue_job(job_key, serialized_job)
                    # update job's information, such as next_run_time
                    job_in_dict = Job.deserialize_to_dict(serialized_job)
                    last_run_time = Job.get_serial_run_times(job_in_dict, now)
                    if last_run_time:
                        next_run_time = Job.get_next_trigger_time(job_in_dict, last_run_time[-1])
                        if next_run_time:
                            job_in_dict['next_run_time'] = next_run_time
                            self.update_job(job_id, job_key, next_run_time, Job.dict_to_serialization(job_in_dict))
                        else:
                            # if job has no next run time, then remove it from jobstore
                            self.remove_job(job_id=job_id)

                # get next closet run time job from jobstore and set it to be wake up time
                closest_run_time = self.jobstore.get_closest_run_time()

            if closest_run_time is not None:
                wait_seconds = max(timedelta_seconds(closest_run_time - now), 0)
                self.log.debug('Next wakeup is due at %s (in %f seconds)' % (closest_run_time, wait_seconds))
            self._event.wait(wait_seconds if wait_seconds is not None else self.MAX_WAIT_TIME)
            self._event.clear()

    def wake_up(self):
        self._event.set()

    @property
    def running(self):
        return not self._stopped



