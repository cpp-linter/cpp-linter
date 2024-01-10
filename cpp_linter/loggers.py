import logging

from requests import Response

FOUND_RICH_LIB = False
try:  # pragma: no cover
    from rich.logging import RichHandler  # type: ignore

    FOUND_RICH_LIB = True

    logging.basicConfig(
        format="%(name)s: %(message)s",
        handlers=[RichHandler(show_time=False)],
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
    """Begin a collapsable group of log statements.

    :param name: The name of the collapsable group
    """
    log_commander.fatal("::group::%s", name)


def end_log_group() -> None:
    """End a collapsable group of log statements."""
    log_commander.fatal("::endgroup::")


def log_response_msg(response_buffer: Response) -> bool:
    """Output the response buffer's message on a failed request.

    :returns:
        A bool describing if response's status code was less than 400.
    """
    if response_buffer.status_code >= 400:
        logger.error(
            "response returned %d from %s with message: %s",
            response_buffer.status_code,
            response_buffer.url,
            response_buffer.text,
        )
        return False
    return True
