"""Home Assistant E-Ink Display Server.

This module is the entry point for the TRMNL server application.
It sets up logging and starts the HTTP server.
"""

import signal
import socketserver
import time
from argparse import ArgumentParser, Namespace
from logging import getLogger, StreamHandler, Formatter, DEBUG
from logging.handlers import RotatingFileHandler
from os import makedirs, path, environ
from tempfile import gettempdir

from api import APICalls


from logging import Logger

def setup_logging() -> Logger:
    """Set up logging configuration.
    
    Returns:
        Configured logger instance
    """
    # Logging configuration
    log_dir: str = "/logs"
    try:
        makedirs(log_dir, exist_ok=True)
    except OSError:
        log_dir = gettempdir()

    log_file: str = path.join(log_dir, "log")
    logger = getLogger(__name__)
    logger.setLevel(DEBUG)

    stream_handler = StreamHandler()
    file_handler = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=3)
    formatter = Formatter(
        '%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
    )
    stream_handler.setFormatter(formatter)
    file_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    logger.addHandler(file_handler)
    
    return logger


def create_handler_class(logger):
    """Create a handler class with logger bound.
    
    Args:
        logger: Logger instance to use
        
    Returns:
        Handler class with logger bound
    """
    class Handler(APICalls):
        def __init__(self, *args, **kwargs):
            super().__init__(logger, *args, **kwargs)
    
    return Handler


def main() -> None:
    """Main entry point for the server."""
    logger = setup_logging()
    
    parser = ArgumentParser(description="Home Assistant Image Server")
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind the server to",
    )
    args: Namespace = parser.parse_args()
    port: int = args.port

    max_attempts: int = 8
    base_delay: int = 1
    httpd = None

    # Create handler class with logger
    Handler = create_handler_class(logger)

    for attempt in range(max_attempts):
        try:
            httpd = socketserver.TCPServer(("", port), Handler)
            break
        except OSError:
            if attempt < max_attempts - 1:
                delay: int = base_delay * (2 ** attempt)
                logger.warning(
                    f"Port {port} in use, retrying in {delay}s... ({attempt + 1}/{max_attempts})"
                )
                time.sleep(delay)
            else:
                logger.error(f"Failed to bind to port {port} after {max_attempts} attempts.")
                raise

    if not environ.get("SERVER_NAME"):
        logger.warning(
            "SERVER_NAME environment variable is not set. "
            "Image URLs in /api/display responses will use the default placeholder. "
            "Set SERVER_NAME to the externally reachable base URL of this server."
        )

    if httpd:
        def _shutdown(signum, frame):
            logger.info("Received signal %d, shutting down.", signum)
            httpd.shutdown()

        signal.signal(signal.SIGTERM, _shutdown)
        signal.signal(signal.SIGINT, _shutdown)

        try:
            logger.info(f"serving at port {port}")
            httpd.serve_forever()
        finally:
            httpd.server_close()


if __name__ == "__main__":
    main()
