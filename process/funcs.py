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

    logger = logging.getLogger(name)
    logger.setLevel(level)
    handler = logging.FileHandler(log_file, mode=filemode)
    handler.setLevel(level)
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    # Silence console logging
    # if no_console:
    #     console = logging.StreamHandler()
    #     console.setLevel(100)

    return logger


def get_silent_logger(name, level=logging.INFO, format_str: str = '%(asctime)s - %(name)s - %(levelname)s - %(message)s', silent: bool = True):
    logger = logging.getLogger(name)
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(format_str))
    logger.addHandler(console)
    if silent:
        logger.setLevel(100)
    else:
        logger.setLevel(level)
    return logger


def remove_duplicates_from_playlist(entries):
    videos = []
    s = set()
    for p, video in enumerate(entries):
        if video['id'] not in s:
            videos.append(video)
            s.add(video['id'])
    return videos
