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

import ydl.yt_dlp as ydl
from process.funcs import get_silent_logger, remove_duplicates_from_playlist, restart_program, setup_file_logger
from process.threads import download_video
from ydl.files import create_directories, resolve_path

# logging.basicConfig(level=1000)
# logging.getLogger().setLevel(1000)

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
parser.add_argument('--threads', type=int, default=cpu_count(), help='How many download processes to use.')
parser.add_argument('--daemon', '-d', action='store_true', help="Run in daemon mode. Disables progress bars sleeps for the amount of time specified in --sleep.")
parser.add_argument('--sleep', type=float, default=60, help='How many minutes to sleep when in daemon mode.')
parser.add_argument('--silence-errors', '-s', action='store_true', help="Don't print any error messages to the console.")
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

if args.daemon:
    print('Running in daemon mode.')

log_dir = args.output / 'logs'
create_directories(args.output, log_dir)

file_logger = setup_file_logger('youtube_dl', log_dir / f'youtube_dl-{str(int(log_time))}.log', level=logging.INFO)
video_error_logger = setup_file_logger('youtube_dl_video_errors', log_dir / f'youtube_dl-errors-{int(log_time)}.log', level=logging.INFO)
logger = get_silent_logger('yt-dl', silent=not args.daemon)


def log_info_twice(msg):
    logger.info(msg)
    file_logger.info(msg)


log_info_twice('Starting process.')
start_time = time.time()

manager = Manager()

download_archive_file = args.output / 'download-archive.log'


def load_existing_videos():
    # Find existing videos.
    output = set()
    if not download_archive_file.exists():
        download_archive_file.touch()
    with open(download_archive_file, 'r') as file:
        output.update(([line.rstrip() for line in file]))
    return output


downloaded_videos = load_existing_videos()
print('Found', len(downloaded_videos), 'downloaded videos.')

# Create this object AFTER reading in the download_archive.
download_archive_logger = setup_file_logger('download_archive', download_archive_file, format_str='%(message)s')

status_bar = tqdm(position=2, bar_format='{desc}', disable=args.daemon)


def log_bar(msg, level):
    status_bar.write(f'[{level}] {msg}')
    if level == 'warning':
        logger.warning(msg)
    elif level == 'error':
        logger.error(msg)
    else:
        logger.info(msg)


def print_without_paths(msg):
    """
    Remove any filepaths or other stuff we don't want in the message.
    """
    m = re.match(r'(^[^\/]+(?:\\.[^\/]*)*)', msg)
    if m:
        msg = m.group(1)
        m1 = re.match(r'^(.*?): ', msg)
    msg = msg.strip('to "').strip('to: ').strip()
    if args.daemon:
        log_info_twice(msg)
    else:
        status_bar.set_description_str(msg)


class ytdl_logger(object):
    def debug(self, msg):
        file_logger.debug(msg)
        # if msg.startswith('[debug] '):
        #     pass
        if '[download]' not in msg:
            print_without_paths(msg)

    def info(self, msg):
        file_logger.info(msg)
        print_without_paths(msg)

    def warning(self, msg):
        file_logger.warning(msg)
        log_bar(msg, 'warning')

    def error(self, msg):
        file_logger.error(msg)
        log_bar(msg, 'error')


# https://github.com/yt-dlp/yt-dlp#embedding-examples
ydl_opts = {
    'format': f'(bestvideo[filesize<{args.max_size}M][vcodec^=av01][height>=1080][fps>30]/bestvideo[filesize<{args.max_size}M][vcodec=vp9.2][height>=1080][fps>30]/bestvideo[filesize<{args.max_size}M][vcodec=vp9][height>=1080][fps>30]/bestvideo[filesize<{args.max_size}M][vcodec^=av01][height>=1080]/bestvideo[filesize<{args.max_size}M][vcodec=vp9.2][height>=1080]/bestvideo[filesize<{args.max_size}M][vcodec=vp9][height>=1080]/bestvideo[filesize<{args.max_size}M][height>=1080]/bestvideo[filesize<{args.max_size}M][vcodec^=av01][height>=720][fps>30]/bestvideo[filesize<{args.max_size}M][vcodec=vp9.2][height>=720][fps>30]/bestvideo[filesize<{args.max_size}M][vcodec=vp9][height>=720][fps>30]/bestvideo[filesize<{args.max_size}M][vcodec^=av01][height>=720]/bestvideo[filesize<{args.max_size}M][vcodec=vp9.2][height>=720]/bestvideo[filesize<{args.max_size}M][vcodec=vp9][height>=720]/bestvideo[filesize<{args.max_size}M][height>=720]/bestvideo[filesize<{args.max_size}M])+(bestaudio[acodec=opus]/bestaudio)/best',
    'outtmpl': f'{args.output}/[%(id)s] [%(title)s] [%(uploader)s] [%(uploader_id)s].%(ext)s',  # leading dash can cause issues due to bash args so we surround the variables in brackets
    'merge_output_format': 'mkv',
    'logtostderr': True,
    'embedchapters': True,
    'writethumbnail': True,  # Save the thumbnail to a file. Embedding seems to be broken right now so this is an alternative.
    'embedthumbnail': True,
    'embeddescription': True,
    'writesubtitles': True,
    # 'allsubtitles': True, # Download every language.
    'subtitlesformat': 'vtt',
    'subtitleslangs': ['en'],
    'writeautomaticsub': True,
    # 'writedescription': True,
    'ignoreerrors': True,
    'continuedl': False,
    'addmetadata': True,
    'writeinfojson': True,
    'postprocessors': [
        {'key': 'FFmpegEmbedSubtitle'},
        {'key': 'FFmpegMetadata', 'add_metadata': True},
        {'key': 'EmbedThumbnail', 'already_have_thumbnail': True},
        # {'key': 'FFmpegSubtitlesConvertor', 'format': 'srt'}
    ],
}

main_opts = dict(ydl_opts, **{'logger': ytdl_logger()})
# thread_opts = dict(ydl_opts, **{'logger': ydl.ytdl_no_logger()})
yt_dlp = ydl.YDL(main_opts)

# Init bars
playlist_bar = tqdm(position=1, desc='Playlist', disable=args.daemon)
video_bars = manager.list()
if not args.daemon:
    for i in range(args.threads):
        video_bars.append([
            3 + i,
            manager.Lock()
        ])

while True:
    for i, target_url in tqdm(enumerate(url_list), total=len(url_list), position=0, desc='Inputs', disable=args.daemon):
        logger.info('Fetching playlist...')
        playlist = yt_dlp.playlist_contents(target_url)
        playlist['entries'] = remove_duplicates_from_playlist(playlist['entries'])
        encountered_errors = 0
        errored_videos = 0

        log_info_twice(f"Downloading item: '{playlist['title']}' {target_url}")

        playlist_bar.total = len(playlist['entries'])
        playlist_bar.set_description(playlist['title'])

        # print(playlist['entries'][0])
        # sys.exit()

        # Remove already downloaded files from the to-do list.
        download_queue = []
        s = set()
        for p, video in enumerate(playlist['entries']):
            if video['id'] not in downloaded_videos and video['id'] not in s:
                download_queue.append(video)
                s.add(video['id'])
        playlist_bar.update(len(downloaded_videos))

        if len(download_queue):  # Don't mess with multiprocessing if all videos are already downloaded
            with Pool(processes=args.threads) as pool:
                status_bar.set_description_str('=' * os.get_terminal_size()[0])
                logger.info('Starting downloads...')
                for result in pool.imap_unordered(download_video,
                                                  ((video, {
                                                      'bars': video_bars,
                                                      'ydl_opts': ydl_opts,
                                                      'output_dir': args.output,
                                                  }) for video in download_queue)):
                    # Save the video ID to the file
                    if result['downloaded_video_id']:
                        download_archive_logger.info(result['downloaded_video_id'])

                    # Print stuff
                    for line in result['video_error_logger_msg']:
                        video_error_logger.info(line)
                        file_logger.error(line)
                        encountered_errors += 1
                        if not args.silence_errors:
                            if args.daemon:
                                logger.error(line)
                            else:
                                playlist_bar.write(line)
                    if len(result['video_error_logger_msg']):
                        errored_videos += 1

                    # for line in result['status_msg']:
                    #     playlist_bar.write(line)
                    for line in result['logger_msg']:
                        log_info_twice(line)
                    playlist_bar.update()
        else:
            playlist_bar.write(f"All videos already downloaded for '{playlist['title']}'.")

        error_msg = f'Encountered {encountered_errors} errors on {errored_videos} videos.'
        if args.daemon:
            logger.info(error_msg)
        else:
            playlist_bar.write(error_msg)

        log_info_twice(f"Finished item: '{playlist['title']}' {target_url}")
    log_info_twice(f"Finished process in {round(math.ceil(time.time() - start_time) / 60, 2)} min.")
    if not args.daemon:
        break
    else:
        logger.info(f'Sleeping for {args.sleep} min.')
        try:
            time.sleep(args.sleep * 60)
        except KeyboardInterrupt:
            sys.exit()
        downloaded_videos = load_existing_videos()  # reload the videos that have already been downloaded

# Erase the status bar.
status_bar.set_description_str('\x1b[2KDone!')
status_bar.refresh()

# Clean up the remaining bars. Have to close them in order.
playlist_bar.close()
status_bar.close()
