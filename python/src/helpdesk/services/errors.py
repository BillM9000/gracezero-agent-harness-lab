"""Errors a service can raise. The API layer turns each kind into one HTTP status."""


class ServiceError(Exception):
    """Base class. The message is written for whoever called the service, person or agent."""


class NotFound(ServiceError):
    pass


class Invalid(ServiceError):
    pass


class Conflict(ServiceError):
    pass
