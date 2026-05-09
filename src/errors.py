class DocumentFetchError(Exception):
    pass


class DocumentParseError(Exception):
    pass


class LLMTimeoutError(Exception):
    pass


class LLMRateLimitError(Exception):
    pass


class TokenBudgetExceeded(Exception):
    pass


class OutputValidationError(Exception):
    pass


class JobNotFoundError(Exception):
    pass
