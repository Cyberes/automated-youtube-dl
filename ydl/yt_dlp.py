import subprocess
from pathlib import Path
from typing import Union

import yt_dlp
from mergedeep import merge


class YDL:
    def __init__(self, ydl_opts):
        self.ydl_opts = ydl_opts
        self.yt_dlp = yt_dlp.YoutubeDL(ydl_opts)

    def get_formats(self, url: Union[str, Path]) -> tuple:
        """
        Not used since we're letting youtube-dl manage filesize filters for us.
        """
        sizes = []
        with self.yt_dlp as ydl:
            for video in ydl.extract_info(url, download=False)['formats']:
                d = {
                    'format_id': video['format_id'],
                    'format_note': video['format_note'],
                }
                if video.get('filesize'):
                    d['filesize'] = round(video['filesize'] / 1e+6, 1)  # MB
                else:
                    d['filesize'] = -1
                sizes.append(d)
        return tuple(sizes)

    def playlist_contents(self, url: str) -> dict:
        ydl_opts = merge({
            'extract_flat': True,
            'skip_download': True
        }, self.ydl_opts)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.sanitize_info(ydl.extract_info(url, download=False))
            entries = []
            if info['_type'] == 'playlist':
                if 'entries' in info.keys():
                    entries = [x for x in info['entries']]
            elif info['_type'] == 'video':
                # `info` doesn't seem to contain the `url` key so we'll add it manually.
                # If any issues arise in the future make sure to double check there isn't any weirdness going on here.
                entries.append(info)
                entries[0]['url'] = f"https://www.youtube.com/watch?v={info['id']}"
            else:
                raise ValueError(f"Unknown media type: {info['_type']}")
            return {
                'title': info['title'],
                'id': info['id'],
                'entries': entries,
            }

    def __call__(self, *args, **kwargs):
        return self.yt_dlp.download(*args, **kwargs)

    # def filter_filesize(self, info, *, incomplete):
    #     duration = info.get('duration')
    #     if duration and duration < 60:
    #         return 'The video is too short'


def update_ytdlp():
    old = subprocess.check_output('pip freeze | grep yt-dlp', shell=True).decode().strip('\n')
    subprocess.run('if pip list --outdated | grep -q yt-dlp; then pip install --upgrade yt-dlp; fi', shell=True)
    new = subprocess.check_output('pip freeze | grep yt-dlp', shell=True).decode().strip('\n')
    return old != new


class ytdl_no_logger(object):
    def debug(self, msg):
        return

    def info(self, msg):
        return

    def warning(self, msg):
        return

    def error(self, msg):
        return
