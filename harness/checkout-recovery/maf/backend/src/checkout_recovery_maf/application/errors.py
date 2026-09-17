class CaseNotFoundError(LookupError):
    pass


class FixtureNotFoundError(KeyError):
    pass


class InvalidCaseCommandError(ValueError):
    pass
