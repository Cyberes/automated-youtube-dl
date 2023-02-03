#!/usr/bin/env python3
import argparse
import logging.config
import math
import os
import re
import signal
import subprocess
import sys
import time
from multiprocessing import Manager, Pool, cpu_count
from pathlib import Path
from threading import Thread

import yaml
from appdirs import user_data_dir
from tqdm.auto import tqdm

import ydl.yt_dlp as ydl
from process.funcs import get_silent_logger, remove_duplicates_from_playlist, restart_program, setup_file_logger
from process.threads import bar_eraser, download_video
from ydl.files import create_directories, resolve_path


def signal_handler(sig, frame):
    # TODO: https://www.g-loaded.eu/2016/11/24/how-to-terminate-running-python-threads-using-signals/
    # raise ServiceExit
    sys.exit(0)


signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

urlRegex = re.compile(r'^(?:http|ftp)s?://'  # http:// or https://
                      r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|'  # domain...
                      r'localhost|'  # localhost...
                      r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # ...or ip
                      r'(?::\d+)?'  # optional port
                      r'(?:/?|[/?]\S+)$', re.IGNORECASE)

parser = argparse.ArgumentParser()
parser.add_argument('file', help='URL to download or path of a file containing the URLs of the videos to download.')
parser.add_argument('--output', required=False, help='Output directory. Ignored paths specified in a YAML file.')
parser.add_argument('--no-update', '-n', action='store_true', help='Don\'t update yt-dlp at launch.')
parser.add_argument('--max-size', type=int, default=1100, help='Max allowed size of a video in MB.')
parser.add_argument('--rm-cache', '-r', action='store_true', help='Delete the yt-dlp cache on start.')
parser.add_argument('--threads', type=int, default=cpu_count(), help='How many download processes to use.')
parser.add_argument('--daemon', '-d', action='store_true', help="Run in daemon mode. Disables progress bars sleeps for the amount of time specified in --sleep.")
parser.add_argument('--sleep', type=float, default=60, help='How many minutes to sleep when in daemon mode.')
parser.add_argument('--download-cache-file-directory', default=user_data_dir('automated-youtube-dl', 'cyberes'), help='The path to the directory to track downloaded videos. Defaults to your appdata path.')
parser.add_argument('--silence-errors', '-s', action='store_true', help="Don't print any error messages to the console.")
parser.add_argument('--ignore-downloaded', '-i', action='store_true', help='Ignore videos that have been already downloaded and let youtube-dl handle everything.')
parser.add_argument('--erase-downloaded-tracker', '-e', action='store_true', help='Erase the tracked video file.')
parser.add_argument('--ratelimit-sleep', type=int, default=5, help='How many seconds to sleep to prevent rate-limiting.')
parser.add_argument('--input-datatype', choices=['auto', 'txt', 'yaml'], default='auto', help='The datatype of the input file. If set to auto, the file will be scanned for a URL on the firstline.'
                                                                                              'If is a URL, the filetype will be set to txt. If it is a key: value pair then the filetype will be set to yaml.')
parser.add_argument('--log-dir', default=None, help='Where to store the logs. Must be set when --output is not.')
parser.add_argument('--verbose', '-v', action='store_true')
args = parser.parse_args()

if args.threads <= 0:
    print("Can't have 0 threads!")
    sys.exit(1)

if args.output:
    args.output = resolve_path(args.output)
if args.log_dir:
    args.log_dir = resolve_path(args.log_dir)
elif not args.output and not args.log_dir:
    print('Must set --log-dir when --output is not.')
    sys.exit(1)
else:
    args.log_dir = args.output / 'logs'

args.download_cache_file_directory = resolve_path(args.download_cache_file_directory)

# TODO: use logging for this
if args.verbose:
    print('Cache directory:', args.download_cache_file_directory)

log_time = time.time()

# Get the URLs of the videos to download. Is the input a URL or file?
url_list = {}
if not re.match(urlRegex, str(args.file)) or args.input_datatype in ('txt', 'yaml'):
    args.file = resolve_path(args.file)
    if not args.file.exists():
        print('Input file does not exist:', args.file)
        sys.exit(1)
    input_file = [x.strip().strip('\n') for x in list(args.file.open())]
    if args.input_datatype == 'yaml' or (re.match(r'^.*?:\w*', input_file[0]) and args.input_datatype == 'auto'):
        with open(args.file, 'r') as file:
            try:
                url_list = yaml.safe_load(file)
            except yaml.YAMLError as e:
                print('Failed to load config file, error:', e)
                sys.exit(1)
    elif args.input_datatype == 'txt' or (re.match(urlRegex, input_file[0]) and args.input_datatype == 'auto'):
        if not args.output:
            print('You must specify an output path with --output when the input datatype is a text file.')
            sys.exit(1)
        url_list[str(args.output)] = input_file
    else:
        print('Unknown file type:', args.input_datatype)
        print(input_file)
        sys.exit(1)
    del input_file  # release file object
    # Verify each line in the file is a valid URL.
    for directory, urls in url_list.items():
        for item in urls:
            if not re.match(urlRegex, str(item)):
                print(f'Not a url:', item)
                sys.exit(1)
else:
    if not args.output:
        print('You must specify an output path with --output when the input is a URL.')
        sys.exit(1)
    url_list[str(args.output)] = [args.file]

# Create directories AFTER loading the file
create_directories(*url_list.keys(), args.download_cache_file_directory)


def do_update():
    if not args.no_update:
        print('Checking if yt-dlp needs to be updated...')
        updated = ydl.update_ytdlp()
        if updated:
            print('Restarting program...')
            restart_program()
        else:
            print('Up to date.')


if args.rm_cache:
    subprocess.run('yt-dlp --rm-cache-dir', shell=True)

if args.daemon:
    print('Running in daemon mode.')

create_directories(args.log_dir)

# TODO: log file rotation https://www.blog.pythonlibrary.org/2014/02/11/python-how-to-create-rotating-logs/
# TODO: log to one file instead of one for each run
file_logger = setup_file_logger('youtube_dl', args.log_dir / f'{str(int(log_time))}.log', level=logging.INFO)
video_error_logger = setup_file_logger('youtube_dl_video_errors', args.log_dir / f'{int(log_time)}-errors.log', level=logging.INFO)
logger = get_silent_logger('yt-dl', silent=not args.daemon)


def log_info_twice(msg):
    logger.info(msg)
    file_logger.info(msg)


log_info_twice('Starting process.')
start_time = time.time()

manager = Manager()


def load_existing_videos():
    # Find existing videos.
    output = set()
    if not download_archive_file.exists():
        download_archive_file.touch()
    with open(download_archive_file, 'r') as file:
        output.update(([line.rstrip() for line in file]))
    return output


status_bar = tqdm(position=2, bar_format='{desc}', disable=args.daemon, leave=False)


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
base_outtempl = '[%(id)s] [%(title)s] [%(uploader)s] [%(uploader_id)s].%(ext)s'  # leading dash can cause issues due to bash args so we surround the variables in brackets
ydl_opts = {
    'format': f'(bestvideo[filesize<{args.max_size}M][vcodec^=av01][height>=1080][fps>30]/bestvideo[filesize<{args.max_size}M][vcodec=vp9.2][height>=1080][fps>30]/bestvideo[filesize<{args.max_size}M][vcodec=vp9][height>=1080][fps>30]/bestvideo[filesize<{args.max_size}M][vcodec^=av01][height>=1080]/bestvideo[filesize<{args.max_size}M][vcodec=vp9.2][height>=1080]/bestvideo[filesize<{args.max_size}M][vcodec=vp9][height>=1080]/bestvideo[filesize<{args.max_size}M][height>=1080]/bestvideo[filesize<{args.max_size}M][vcodec^=av01][height>=720][fps>30]/bestvideo[filesize<{args.max_size}M][vcodec=vp9.2][height>=720][fps>30]/bestvideo[filesize<{args.max_size}M][vcodec=vp9][height>=720][fps>30]/bestvideo[filesize<{args.max_size}M][vcodec^=av01][height>=720]/bestvideo[filesize<{args.max_size}M][vcodec=vp9.2][height>=720]/bestvideo[filesize<{args.max_size}M][vcodec=vp9][height>=720]/bestvideo[filesize<{args.max_size}M][height>=720]/bestvideo[filesize<{args.max_size}M])+(bestaudio[acodec=opus]/bestaudio)/best',
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
    'writedescription': True,
    'ignoreerrors': True,
    'continuedl': False,
    'addmetadata': True,
    'writeinfojson': True,
    'postprocessors': [
        {'key': 'FFmpegEmbedSubtitle'},
        {'key': 'FFmpegMetadata', 'add_metadata': True},
        {'key': 'EmbedThumbnail', 'already_have_thumbnail': True},
        {'key': 'FFmpegThumbnailsConvertor', 'format': 'jpg', 'when': 'before_dl'},
        # {'key': 'FFmpegSubtitlesConvertor', 'format': 'srt'}
    ],
    # 'external_downloader': 'aria2c',
    # 'external_downloader_args': ['-j 32', '-s 32', '-x 16', '--file-allocation=none', '--optimize-concurrent-downloads=true', '--http-accept-gzip=true', '--continue=true'],
}

yt_dlp = ydl.YDL(dict(ydl_opts, **{'logger': ytdl_logger()}))

url_count = 0
for k, v in url_list.items():
    for item in v:
        url_count += 1

# Init bars
video_bars = manager.list()
if not args.daemon:
    for i in range(args.threads):
        video_bars.append([3 + i, manager.Lock()])

encountered_errors = 0
errored_videos = 0

# The video progress bars have an issue where when a bar is closed it will shift its position back 1 then return to the correct position.
# This thread will clear empty spots.
if not args.daemon:
    eraser_exit = manager.Value(bool, False)
    Thread(target=bar_eraser, args=(video_bars, eraser_exit,)).start()

already_erased_downloaded_tracker = False

while True:
    do_update()
    progress_bar = tqdm(total=url_count, position=0, desc='Inputs', disable=args.daemon, bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt}')
    for output_path, urls in url_list.items():
        for target_url in urls:
            logger.info('Fetching playlist...')
            playlist = yt_dlp.playlist_contents(str(target_url))

            if not playlist:
                progress_bar.update()
                continue

            download_archive_file = args.download_cache_file_directory / (str(playlist['id']) + '.log')
            if args.erase_downloaded_tracker and not already_erased_downloaded_tracker:
                if download_archive_file.exists():
                    os.remove(download_archive_file)
                already_erased_downloaded_tracker = True
            downloaded_videos = load_existing_videos()

            msg = f'Found {len(downloaded_videos)} downloaded videos for playlist "{playlist["title"]}" ({playlist["id"]}). {"Ignoring." if args.ignore_downloaded else ""}'
            if args.daemon:
                print(msg)
            else:
                status_bar.write(msg)
            download_archive_logger = setup_file_logger('download_archive', download_archive_file, format_str='%(message)s')

            playlist['entries'] = remove_duplicates_from_playlist(playlist['entries'])

            log_info_twice(f'Downloading item: "{playlist["title"]}" ({playlist["id"]}) {target_url}')

            # Remove already downloaded files from the to-do list.
            download_queue = []
            for p, video in enumerate(playlist['entries']):
                if video['id'] not in download_queue:
                    if not args.ignore_downloaded and video['id'] not in downloaded_videos:
                        download_queue.append(video)
                        # downloaded_videos.add(video['id'])
                    elif args.ignore_downloaded:
                        download_queue.append(video)

            playlist_bar = tqdm(total=len(playlist['entries']), position=1, desc=f'"{playlist["title"]}" ({playlist["id"]})', disable=args.daemon, leave=False)
            if not args.ignore_downloaded:
                playlist_bar.update(len(downloaded_videos))

            playlist_ydl_opts = ydl_opts.copy()
            playlist_ydl_opts['outtmpl'] = f'{output_path}/{base_outtempl}'

            if len(download_queue):  # Don't mess with multiprocessing if all videos are already downloaded
                with Pool(processes=args.threads) as pool:
                    if sys.stdout.isatty():
                        # Doesn't work if not connected to a terminal:
                        # OSError: [Errno 25] Inappropriate ioctl for device
                        status_bar.set_description_str('=' * os.get_terminal_size()[0])
                    logger.info('Starting downloads...')
                    for result in pool.imap_unordered(download_video, ((video, {'bars': video_bars, 'ydl_opts': playlist_ydl_opts, 'output_dir': Path(output_path), }) for video in download_queue)):
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
                                    status_bar.write(line)

                        if len(result['video_error_logger_msg']):
                            errored_videos += 1
                            if args.silence_errors and args.daemon:
                                logger.error(f"{result['video_id']} failed due to error.")

                        # for line in result['status_msg']:
                        #     playlist_bar.write(line)
                        for line in result['logger_msg']:
                            log_info_twice(line)
                        playlist_bar.update()
            else:
                status_bar.write(f"All videos already downloaded for '{playlist['title']}'.")
            log_info_twice(f"Finished item: '{playlist['title']}' {target_url}")

            # Sleep a bit to prevent rate-limiting
            if progress_bar.n < len(url_list.keys()) - 1:
                status_bar.set_description_str(f'Sleeping {args.ratelimit_sleep}s...')
                time.sleep(args.ratelimit_sleep)

            progress_bar.update()
    error_msg = f'Encountered {encountered_errors} errors on {errored_videos} videos.'
    if args.daemon:
        logger.info(error_msg)
    else:
        status_bar.write(error_msg)
    log_info_twice(f"Finished process in {round(math.ceil(time.time() - start_time) / 60, 2)} min.")
    if not args.daemon:
        break
    else:
        logger.info(f'Sleeping for {args.sleep} min.')
        try:
            time.sleep(args.sleep * 60)
        except KeyboardInterrupt:
            sys.exit(0)
        # downloaded_videos = load_existing_videos()  # reload the videos that have already been downloaded

# Clean up the remaining bars. Have to close them in order.
eraser_exit.value = True
playlist_bar.close()
status_bar.close()
