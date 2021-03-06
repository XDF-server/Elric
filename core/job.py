# -*- coding: utf-8 -*-
from __future__ import (absolute_import, unicode_literals)

from core.utils import ref_to_obj, obj_to_ref, check_callable_args, convert_to_datetime
from uuid import uuid4
from trigger.base import BaseTrigger
from core.exceptions import WrongType
import six
try:
    import cPickle as pickle
except ImportError:
    import pickle


class Job(object):

    def __init__(self, **job_in_dict):
        id = job_in_dict.get('id', None)
        func = job_in_dict.get('func', None)
        args = job_in_dict.get('args', None)
        kwargs = job_in_dict.get('kwargs', None)
        trigger = job_in_dict.get('trigger', None)
        next_run_time = job_in_dict.get('next_run_time', None)
        filter_key = job_in_dict.get('filter_key', None)
        filter_value = job_in_dict.get('filter_value', None)
        ref_to_func = None
        if isinstance(func, six.string_types):
            ref_to_func = func
            func = ref_to_obj(func)
        elif callable(func):
            ref_to_func = obj_to_ref(func)
        if trigger and not isinstance(trigger, BaseTrigger):
            raise WrongType
        if trigger:
            next_run_time = next_run_time or trigger.get_next_trigger_time(None)

        self.args = tuple(args) if args is not None else ()
        self.kwargs = dict(kwargs) if kwargs is not None else {}
        self.trigger = trigger
        self.next_run_time = next_run_time
        self.id = id or uuid4().hex
        self.func = func
        self.ref_to_func = ref_to_func
        self.filter_key = filter_key
        self.filter_value = filter_value

        check_callable_args(self.func, self.args, self.kwargs)

    def serialize(self):
        """
            dict representation of job
            :return:
        """
        job_in_dict = {
            'id': self.id,
            'func': self.ref_to_func,
            'trigger': self.trigger,
            'next_run_time': self.next_run_time,
            'args': self.args,
            'kwargs':self.kwargs,
            'filter_key': self.filter_key,
            'filter_value': self.filter_value
        }
        return pickle.dumps(job_in_dict, pickle.HIGHEST_PROTOCOL)

    @classmethod
    def deserialize(cls, serialization):
        job_in_dict = cls.deserialize_to_dict(serialization)
        return cls(**job_in_dict)

    @classmethod
    def deserialize_to_dict(cls, serialization):
        return pickle.loads(serialization)

    @classmethod
    def dict_to_serialization(cls, job_in_dict):
        return pickle.dumps(job_in_dict, pickle.HIGHEST_PROTOCOL)

    @classmethod
    def get_serial_run_times(cls, job_in_dict, now):
        run_times = []
        next_run_time = job_in_dict['next_run_time']
        while next_run_time and next_run_time <= now:
            run_times.append(next_run_time)
            next_run_time = job_in_dict['trigger'].get_next_trigger_time(next_run_time, now)

        return run_times

    @classmethod
    def get_next_trigger_time(cls, job_in_dict, run_time):
        return job_in_dict['trigger'].get_next_trigger_time(run_time)
