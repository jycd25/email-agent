class EmailAgentError(Exception):
    """Base class for errors raised by this package."""


class ConfigurationError(EmailAgentError):
    pass


class SourceError(EmailAgentError):
    """A mail source (Gmail, Outlook, SMTP) failed."""


class AnalysisError(EmailAgentError):
    """An analyzer could not produce a result."""
