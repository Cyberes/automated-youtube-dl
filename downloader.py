#!/usr/bin/env python3
import argparse
import logging.config
import math
import os
import re
import subprocess
import sys
import time
from multiprocessing import Manager, Pool, cpu_count

from tqdm.auto import tqdm

import automated_youtube_dl.yt_dlp as ydl
from automated_youtube_dl.files import create_directories, resolve_path
from process.funcs import restart_program, setup_file_logger
from process.threads import download_video

urlRegex = re.compile(
    r'^(?:http|ftp)s?://'  # http:// or https://
    r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|'  # domain...
    r'localhost|'  # localhost...
    r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # ...or ip
    r'(?::\d+)?'  # optional port
    r'(?:/?|[/?]\S+)$', re.IGNORECASE)

parser = argparse.ArgumentParser()
parser.add_argument('file', help='URL to download or path of a file containing the URLs of the videos to download.')
parser.add_argument('output', help='Output directory.')
parser.add_argument('--no-update', '-n', action='store_true', help='Don\'t update yt-dlp at launch.')
parser.add_argument('--max-size', type=int, default=1100, help='Max allowed size of a video in MB.')
parser.add_argument('--rm-cache', '-r', action='store_true', help='Delete the yt-dlp cache on start.')
parser.add_argument('--backwards', '-b', action='store_true', help='Reverse all playlists and download in backwards order.')
parser.add_argument('--threads', type=int, default=cpu_count(), help='How many download processes to use.')
parser.add_argument('--daemon', '-d', action='store_true', help="Run in daemon mode. Disables progress bars and prints output that's good for journalctl.")
args = parser.parse_args()

if args.threads <= 0:
    print("Can't have 0 threads!")
    sys.exit(1)

args.output = resolve_path(args.output)
log_time = time.time()

# Get the URLs of the videos to download. Is the input a URL or file?
if not re.match(urlRegex, str(args.file)):
    args.file = resolve_path(args.file)
    if not args.file.exists():
        print('Input file does not exist:', args.file)
        sys.exit(1)
    url_list = [x.strip().strip('\n') for x in list(args.file.open())]
    # Verify each line in the file is a valid URL.
    for i, line in enumerate(url_list):
        if not re.match(urlRegex, line):
            print(f'Line {i} not a url:', line)
            sys.exit(1)
else:
    url_list = [args.file]

if not args.no_update:
    print('Checking if yt-dlp needs to be updated...')
    updated = ydl.update_ytdlp()
    if updated:
        print('Restarting program...')
        restart_program()

if args.rm_cache:
    subprocess.run('yt-dlp --rm-cache-dir', shell=True)

log_dir = args.output / 'logs'
create_directories(args.output, log_dir)

logger = setup_file_logger('youtube_dl', log_dir / f'youtube_dl-{str(int(log_time))}.log', level=logging.INFO)
video_error_logger = setup_file_logger('youtube_dl_video_errors', log_dir / f'youtube_dl-errors-{int(log_time)}.log', level=logging.INFO)

logger.info(f'Starting process.')
start_time = time.time()

manager = Manager()

# Find existing videos to skip.
download_archive_file = args.output / 'download-archive.log'
if not download_archive_file.exists():
    download_archive_file.touch()
with open(download_archive_file, 'r') as file:
    download_archive = manager.list([line.rstrip() for line in file])
print('Found', len(download_archive), 'downloaded videos.')

# Create this object AFTER reading in the download_archive.
download_archive_logger = setup_file_logger('download_archive', download_archive_file, format_str='%(message)s')

status_bar = tqdm(position=2, bar_format='{desc}')


def log_bar(msg, level):
    status_bar.write(f'[{level}] {msg}')


def print_without_paths(msg):
    """
    Remove any filepaths or other stuff we don't want in the message.
    """
    m = re.match(r'(^[^\/]+(?:\\.[^\/]*)*)', msg)
    if m:
        msg = m.group(1)
        m1 = re.match(r'^(.*?): ', msg)
    status_bar.set_description_str(msg.strip('to "').strip('to: ').strip())


class ytdl_logger(object):
    def debug(self, msg):
        logger.debug(msg)
        # if msg.startswith('[debug] '):
        #     pass
        if '[download]' not in msg:
            print_without_paths(msg)

    def info(self, msg):
        logger.info(msg)
        print_without_paths(msg)

    def warning(self, msg):
        logger.warning(msg)
        log_bar(msg, 'warning')

    def error(self, msg):
        logger.error(msg)
        log_bar(msg, 'error')


class ytdl_no_logger(object):
    def debug(self, msg):
        return

    def info(self, msg):
        return

    def warning(self, msg):
        return

    def error(self, msg):
        return


# https://github.com/yt-dlp/yt-dlp#embedding-examples
ydl_opts = {
    'format': f'(bestvideo[filesize<{args.max_size}M][vcodec^=av01][height>=1080][fps>30]/bestvideo[filesize<{args.max_size}M][vcodec=vp9.2][height>=1080][fps>30]/bestvideo[filesize<{args.max_size}M][vcodec=vp9][height>=1080][fps>30]/bestvideo[filesize<{args.max_size}M][vcodec^=av01][height>=1080]/bestvideo[filesize<{args.max_size}M][vcodec=vp9.2][height>=1080]/bestvideo[filesize<{args.max_size}M][vcodec=vp9][height>=1080]/bestvideo[filesize<{args.max_size}M][height>=1080]/bestvideo[filesize<{args.max_size}M][vcodec^=av01][height>=720][fps>30]/bestvideo[filesize<{args.max_size}M][vcodec=vp9.2][height>=720][fps>30]/bestvideo[filesize<{args.max_size}M][vcodec=vp9][height>=720][fps>30]/bestvideo[filesize<{args.max_size}M][vcodec^=av01][height>=720]/bestvideo[filesize<{args.max_size}M][vcodec=vp9.2][height>=720]/bestvideo[filesize<{args.max_size}M][vcodec=vp9][height>=720]/bestvideo[filesize<{args.max_size}M][height>=720]/bestvideo[filesize<{args.max_size}M])+(bestaudio[acodec=opus]/bestaudio)/best',
    'outtmpl': f'{args.output}/%(title)s --- %(uploader)s --- %(uploader_id)s --- %(id)s',
    'merge_output_format': 'mkv',
    'logtostderr': True,
    'embedchapters': True,
    # 'writethumbnail': True, # Save the thumbnail to a file. Embedding seems to be broken right now so this is an alternative.
    'embedthumbnail': True,
    'writesubtitles': True,
    # 'allsubtitles': True, # Download every language.
    'subtitlesformat': 'vtt',
    'subtitleslangs': ['en'],
    'writeautomaticsub': True,
    'postprocessors': [
        {'key': 'FFmpegEmbedSubtitle'},
        {'key': 'FFmpegMetadata', 'add_metadata': True},
        {'key': 'EmbedThumbnail', 'already_have_thumbnail': True},
    ],

}

main_opts = dict(ydl_opts, **{'logger': ytdl_logger()})
thread_opts = dict(ydl_opts, **{'logger': ytdl_no_logger()})
yt_dlp = ydl.YDL(main_opts)

# Init bars
playlist_bar = tqdm(position=1, desc='Playlist')
video_bars = manager.list()
for i in range(args.threads):
    video_bars.append([
        3 + i,
        manager.Lock()
    ])

for i, target_url in tqdm(enumerate(url_list), total=len(url_list), position=0, desc='Inputs'):
    playlist = yt_dlp.playlist_contents(target_url)
    logger.info(f"Downloading item: '{playlist['title']}' {target_url}")
    playlist_bar.total = len(playlist['entries'])
    playlist_bar.set_description(playlist['title'])

    # Remove already downloaded files from the to-do list.
    download_queue = []
    for video in playlist['entries']:
        if video['id'] not in download_archive:
            download_queue.append(video)
        else:
            logger.info(f"{video['id']} already downloaded.")
    playlist_bar.update(len(playlist['entries']) - len(download_queue))

    if args.backwards:
        download_queue.reverse()

    if len(download_queue):  # Don't mess with multiprocessing if the list is empty
        with Pool(processes=args.threads) as pool:
            status_bar.set_description_str('=' * os.get_terminal_size()[0])
            for result in pool.imap_unordered(download_video,
                                              ((video, {
                                                  'bars': video_bars,
                                                  'download_archive': download_archive,
                                                  'ydl_opts': thread_opts,
                                              }) for video in download_queue)):
                if result['downloaded_video_id']:
                    download_archive_logger.info(result['downloaded_video_id'])
                if len(result['video_error_logger_msg']):
                    for line in result['video_error_logger_msg']:
                        video_error_logger.info(line)
                if len(result['status_msg']):
                    for line in result['status_msg']:
                        playlist_bar.write(f"{result['downloaded_video_id']}: {line}")
                if len(result['logger_msg']):
                    for line in result['logger_msg']:
                        logger.info(line)
                playlist_bar.update()
    else:
        playlist_bar.write(f"All videos already downloaded for '{playlist['title']}'")
        # playlist_bar.update(playlist_bar.total - playlist_bar.n)
    logger.info(f"Finished item: '{playlist['title']}' {target_url}")
logger.info(f"Finished process in {round(math.ceil(time.time() - start_time) / 60, 2)} min.")

# Clean up the remaining bars. Have to close them in order.
status_bar.set_description_str('\x1b[2KDone!')  # erase the status bar
status_bar.refresh()
playlist_bar.close()
status_bar.close()
