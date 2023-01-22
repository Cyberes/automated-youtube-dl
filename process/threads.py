import math
import os
import time

import numpy as np
from tqdm.auto import tqdm

import ydl.yt_dlp as ydl
from process.funcs import setup_file_logger


class ytdl_logger(object):
    errors = []

    def __init__(self, logger):
        self.logger = logger

    def debug(self, msg):
        self.logger.info(msg)

    def info(self, msg):
        self.logger.info(msg)

    def warning(self, msg):
        self.logger.warning(msg)

    def error(self, msg):
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
        bar = tqdm(total=100, position=(offset if locked else None), desc=f"{video['id']} - {video['title']}".ljust(desc_with)[:desc_with], bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}{postfix}]', leave=False)

    ylogger = ytdl_logger(setup_file_logger(video['id'], kwargs['output_dir'] / f"[{video['id']}].log"))
    kwargs['ydl_opts']['logger'] = ylogger
    yt_dlp = ydl.YDL(kwargs['ydl_opts'])
    output_dict = {'downloaded_video_id': None, 'blacklist_video_id': None, 'video_error_logger_msg': [], 'status_msg': [], 'logger_msg': []}  # empty object
    start_time = time.time()

    try:
        error_code = yt_dlp(video['url'])  # Do the download
        if not error_code:
            elapsed = round(math.ceil(time.time() - start_time) / 60, 2)
            output_dict['logger_msg'].append(f"{video['id']} '{video['title']}' downloaded in {elapsed} min.")
            output_dict['downloaded_video_id'] = video['id']
        else:
            # m = f'{video["id"]} {video["title"]} -> Failed to download, error code: {error_code}'
            # output_dict['status_msg'].append(m)
            # output_dict['video_error_logger_msg'].append(m)
            output_dict['video_error_logger_msg'] = output_dict['video_error_logger_msg'] + ylogger.errors
    except Exception as e:
        output_dict['video_error_logger_msg'].append(f"EXCEPTION -> {e}")
    if locked:
        bar.close()
        bar_lock.release()
    return output_dict
