__author__ = 'Masutangu'


class StopRequested(Exception):
    pass


class AlreadyRunningException(Exception):
    pass


class AddQueueFailed(Exception):
    pass