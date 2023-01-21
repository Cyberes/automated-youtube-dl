import math
import os
import time

import numpy as np
from tqdm.auto import tqdm

import automated_youtube_dl.yt_dlp as ydl


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
        if d['status'] == 'downloading' and d.get('downloaded_bytes') and d.get('total_bytes'):
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
    bars = kwargs['bars']
    download_archive = kwargs['download_archive']

    ydl_opts = kwargs['ydl_opts']
    ydl_opts['progress_hooks'] = [progress_hook]
    yt_dlp = ydl.YDL(ydl_opts)

    locked = False
    # We're going to wait until a bar is available for us to use.
    while not locked:
        for item in bars:
            if not is_manager_lock_locked(item[1]):
                locked = item[1].acquire(timeout=0.1)  # get the lock ASAP and don't wait if we didn't get it.
                offset = item[0]
                bar_lock = item[1]
                break

    # with bar_lock:
    width, _ = os.get_terminal_size()
    desc_with = int(np.round(width * (1 / 4)))
    bar = tqdm(total=100, position=offset, desc=video['title'].ljust(desc_with)[:desc_with], bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}{postfix}]', leave=False)
    output_dict = {'downloaded_video_id': None, 'video_error_logger_msg': [], 'status_msg': [], 'logger_msg': []}
    start_time = time.time()

    # if video['id'] in download_archive:
    #     output_dict['logger_msg'].append(f"{video['id']} already downloaded.")
    # else:
    try:
        error_code = yt_dlp(video['url'])  # Do the download
        if not error_code:
            download_archive.append(video['id'])
            elapsed = round(math.ceil(time.time() - start_time) / 60, 2)
            output_dict['logger_msg'].append(f"{video['id']} downloaded in {elapsed} min.")
            output_dict['downloaded_video_id'] = video['id']
        else:
            m = f'Failed to download {video["id"]} {video["title"]}, error code: {error_code}'
            output_dict['status_msg'].append(m)
            output_dict['video_error_logger_msg'].append(m)
    except Exception as e:
        output_dict['video_error_logger_msg'].append(f"Error on video {video['id']} '{video['title']}' -> {e}")
    bar.close()
    bar_lock.release()
    return output_dict
