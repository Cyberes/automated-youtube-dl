import logging
import os
import sys

import psutil


def restart_program():
    """
    Restarts the current program, with file objects and descriptors cleanup.
    https://stackoverflow.com/a/33334183
    """
    try:
        p = psutil.Process(os.getpid())
        for handler in p.open_files() + p.connections():
            os.close(handler.fd)
    except Exception as e:
        print('Could not restart Automated FBI Reporter after update.')
        print(e)
        sys.exit(1)
    python = sys.executable
    os.execl(python, python, *sys.argv)


def setup_file_logger(name, log_file, level=logging.INFO, format_str: str = '%(asctime)s - %(name)s - %(levelname)s - %(message)s', filemode='a'):
    formatter = logging.Formatter(format_str)
    handler = logging.FileHandler(log_file, mode=filemode)
    handler.setFormatter(formatter)

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.addHandler(handler)

    # Silence console logging
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(100)

    return logger
