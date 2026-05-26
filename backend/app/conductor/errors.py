class ConductorError(Exception):
    def __init__(self, message: str = ""):
        self.message = message
        super().__init__(message)


class NotFoundError(ConductorError):
    pass


class AlreadyExistsError(ConductorError):
    pass


class InvalidInputError(ConductorError):
    pass


class ConflictError(ConductorError):
    pass


class DatabaseError(ConductorError):
    pass


class RedisError(ConductorError):
    pass


class SandboxError(ConductorError):
    pass
