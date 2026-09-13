import logging
import os
import io

from requests import Response

FOUND_RICH_LIB = False
try:  # pragma: no cover
    from rich.logging import RichHandler, get_console  # type: ignore

    FOUND_RICH_LIB = True

    logging.basicConfig(
        format="%(name)s: %(message)s",
        handlers=[RichHandler(show_time=False, show_path=False)],
    )

except ImportError:  # pragma: no cover
    logging.basicConfig()

#: The :py:class:`logging.Logger` object used for outputting data.
logger = logging.getLogger("CPP Linter")
if not FOUND_RICH_LIB:
    logger.debug("rich module not found")

# setup a separate logger for using github log commands
log_commander = logging.getLogger("LOG COMMANDER")  # create a child of our logger obj
log_commander.setLevel(logging.DEBUG)  # be sure that log commands are output
console_handler = logging.StreamHandler()  # Create special stdout stream handler
console_handler.setFormatter(logging.Formatter("%(message)s"))  # no formatted log cmds
log_commander.addHandler(console_handler)  # Use special handler for log_commander
log_commander.propagate = False


def start_log_group(name: str) -> None:
    """Begin a collapsible group of log statements.

    :param name: The name of the collapsible group
    """
    log_commander.fatal("::group::%s", name)


def end_log_group() -> None:
    """End a collapsible group of log statements."""
    log_commander.fatal("::endgroup::")


def log_response_msg(response: Response):
    """Output the response buffer's message on a failed request."""
    if response.status_code >= 400:
        logger.error(
            "response returned %d from %s %s with message: %s",
            response.status_code,
            response.request.method,
            response.request.url,
            response.text,
        )


def should_use_rich() -> bool:
    """Decide whether log output should be rendered with ``rich``.

    Call this in the parent process and hand the result to worker processes.
    With the ``forkserver`` start method (the default on Linux since Python 3.14)
    workers inherit the environment of the long-lived forkserver, not the parent's
    current environment, so a check of ``os.environ`` inside the worker can be stale.
    """
    return FOUND_RICH_LIB and "CPP_LINTER_PYTEST_NO_RICH" not in os.environ


def worker_log_init(log_lvl: int, use_rich: bool | None = None):
    """Set up logging inside a worker process.

    :param log_lvl: The log level to apply; passed in because Windows does not
        copy the parent's log level to subprocesses.
    :param use_rich: Whether to render logs with ``rich``. Compute this in the
        parent with :func:`should_use_rich` and pass it in; ``None`` falls back to
        evaluating it in the current process.
    """
    log_stream = io.StringIO()

    logger.handlers.clear()
    logger.propagate = False

    if use_rich is None:
        use_rich = should_use_rich()

    handler: logging.Handler
    if use_rich:  # pragma: no cover
        console = get_console()
        console.file = log_stream
        handler = RichHandler(show_time=False, console=console)
        handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
    else:
        handler = logging.StreamHandler(log_stream)
        handler.setFormatter(logging.Formatter(logging.BASIC_FORMAT))
    logger.addHandler(handler)
    # Windows does not copy log level to subprocess.
    # https://github.com/cpp-linter/cpp-linter/actions/runs/8355193931
    logger.setLevel(log_lvl)

    ## uncomment the following if log_commander is needed in isolated threads
    # log_commander.handlers.clear()
    # log_commander.propagate = False
    # console_handler = logging.StreamHandler(log_stream)
    # console_handler.setFormatter(logging.Formatter("%(message)s"))
    # log_commander.addHandler(console_handler)

    return log_stream
