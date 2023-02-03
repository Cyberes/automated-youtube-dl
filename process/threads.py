import math
import multiprocessing
import os
import sys
import time
from multiprocessing import Manager
from threading import Thread

import numpy as np
from tqdm.auto import tqdm

import ydl.yt_dlp as ydl
from process.funcs import setup_file_logger


class ytdl_logger(object):
    errors = []

    def __init__(self, logger=None):
        self.logger = logger

    def debug(self, msg):
        if self.logger:
            self.logger.info(msg)

    def info(self, msg):
        if self.logger:
            self.logger.info(msg)

    def warning(self, msg):
        if self.logger:
            self.logger.warning(msg)

    def error(self, msg):
        if self.logger:
            self.logger.error(msg)
            self.errors.append(msg)


def is_manager_lock_locked(lock) -> bool:
    """
    Manager().Lock().aquire() takes blocking, not block.
    """
    locked = lock.acquire(blocking=False)
    if not locked:
        return True
    else:
        lock.release()
        return False


def download_video(args) -> dict:
    # Sleep for a little bit to space out the rush of workers flooding the bar locks.
    # time.sleep(random.randint(1, 20) / 1000)

    def progress_hook(d):
        # downloaded_bytes and total_bytes can be None if the download hasn't started yet.
        if d['status'] == 'downloading':
            if d.get('downloaded_bytes') and d.get('total_bytes'):
                downloaded_bytes = int(d['downloaded_bytes'])
                total_bytes = int(d['total_bytes'])
                if total_bytes > 0:
                    percent = (downloaded_bytes / total_bytes) * 100
                    bar.update(int(np.round(percent - bar.n)))  # If the progress bar doesn't end at 100% then round to 1 decimal place
            bar.set_postfix({
                'speed': d['_speed_str'],
                'size': f"{d['_downloaded_bytes_str'].strip()}/{d['_total_bytes_str'].strip()}",
            })

    video = args[0]
    kwargs = args[1]

    # Get a bar
    locked = False
    if len(kwargs['bars']):
        # We're going to wait until a bar is available for us to use.
        while not locked:
            for item in kwargs['bars']:
                if not is_manager_lock_locked(item[1]):
                    locked = item[1].acquire(timeout=0.1)  # get the lock ASAP and don't wait if we didn't get it.
                    offset = item[0]
                    bar_lock = item[1]
                    break
        kwargs['ydl_opts']['progress_hooks'] = [progress_hook]
        desc_with = int(np.round(os.get_terminal_size()[0] * (1 / 4)))
        bar = tqdm(total=100, position=offset, desc=f"{video['id']} - {video['title']}".ljust(desc_with)[:desc_with], bar_format='{l_bar}{bar}| {elapsed}<{remaining}{postfix}', leave=False)

    output_dict = {'downloaded_video_id': None, 'video_id': video['id'], 'video_error_logger_msg': [], 'status_msg': [], 'logger_msg': []}  # empty object
    start_time = time.time()

    try:
        kwargs['ydl_opts']['logger'] = ytdl_logger()  # dummy silent logger
        yt_dlp = ydl.YDL(kwargs['ydl_opts'])
        try:
            base_path = os.path.splitext(yt_dlp.prepare_filename(yt_dlp.extract_info(video['url'], download=False)))[0]
        except AttributeError:
            # Sometimes we won't be able to pull the video info so just use the video's ID.
            base_path = kwargs['output_dir'] / video['id']
        ylogger = ytdl_logger(setup_file_logger(video['id'], str(base_path) + '.log'))
        kwargs['ydl_opts']['logger'] = ylogger
        yt_dlp = ydl.YDL(kwargs['ydl_opts'])  # recreate the object with the correct logging path
        error_code = yt_dlp(video['url'])  # Do the download
        if not error_code:
            elapsed = round(math.ceil(time.time() - start_time) / 60, 2)
            output_dict['logger_msg'].append(f"{video['id']} '{video['title']}' downloaded in {elapsed} min.")
            output_dict['downloaded_video_id'] = video['id']
        else:
            output_dict['video_error_logger_msg'] = output_dict['video_error_logger_msg'] + ylogger.errors
    except Exception as e:
        output_dict['video_error_logger_msg'].append(f"EXCEPTION -> {e}")
        bar.update(100 - bar.n)
    if locked:
        bar.close()
        bar_lock.release()
    return output_dict


def bar_eraser(video_bars, eraser_exit):
    manager = Manager()
    queue = manager.dict()
    queue_lock = manager.Lock()

    def eraser():
        nonlocal queue
        try:
            while not eraser_exit.value:
                for i in queue.keys():
                    if eraser_exit.value:
                        return
                    i = int(i)
                    lock = video_bars[i][1].acquire(timeout=0.1)
                    bar_lock = video_bars[i][1]
                    if lock:
                        bar = tqdm(position=video_bars[i][0], leave=False, bar_format='\x1b[2K')
                        bar.close()
                        with queue_lock:
                            del queue_dict[i]
                            queue = queue_dict
                        bar_lock.release()
        except KeyboardInterrupt:
            sys.exit(0)
        except multiprocessing.managers.RemoteError:
            sys.exit(0)
        except SystemExit:
            sys.exit(0)

    try:
        Thread(target=eraser).start()
        while not eraser_exit.value:
            for i, item in enumerate(video_bars):
                if eraser_exit.value:
                    return
                if is_manager_lock_locked(item[1]):
                    with queue_lock:
                        queue_dict = queue
                        queue_dict[i] = True
                        queue = queue_dict
    except KeyboardInterrupt:
        sys.exit(0)
    except multiprocessing.managers.RemoteError:
        sys.exit(0)
    except SystemExit:
        sys.exit(0)


class ServiceExit(Exception):
    """
    Custom exception which is used to trigger the clean exit
    of all running threads and the main program.
    """
    pass
