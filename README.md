# automated-youtube-dl

_Automated YouTube Archival._

A wrapper for youtube-dl used for keeping very large amounts of data from YouTube in sync. It's designed to be simple and easy to use.

I have a single, very large playlist that I add any videos I like to. On my NAS is a service uses this program to download new videos (see [Example systemd Service.md]).

### Features

- Uses yt-dlp instead of youtube-dl.
- Skip videos that are already downloaded which makes checking a playlist for new videos quick because youtube-dl doesn't have to fetch the entire playlist.
- Automatically update yt-dlp on launch.
- Download the videos in a format suitable for archiving:
    - Complex `format` that balances video quality and file size.
    - Embedding of metadata: chapters, thumbnail, english subtitles (automatic too), and YouTube metadata.
- Log progress to a file.
- Simple display using `tqdm`.
- Limit the size of the downloaded videos.
- Parallel downloads.

### Installation

```bash
sudo apt update && sudo apt install ffmpeg atomicparsley
pip install -r requirements.txt
```

### Usage

`./downloader.py <URL to download or path of a file containing the URLs of the videos to download> <output directory>`

#### Folder Structure

```
Output Directory/
├─ logs/
│  ├─ youtube_dl-<UNIX timestamp>.log
│  ├─ youtube_dl-errors-<UNIX timestamp>.log
├─ download-archive.txt
├─ Example Video.mkv
```

`download-archive.txt` contains the videos that have already been downloaded. You can import videos you've already downloaded by adding their ID to this file.

Videos will be saved using this name format:

```
%(title)s --- %(uploader)s --- %(uploader_id)s --- %(id)s
```

#### Arguments

| Argument      | Flag | Help                                                                                                                                                            |
|---------------|------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `--no-update` | `-n` | Don\'t update yt-dlp at launch.                                                                                                                                 |
| `--max-size`  |      | Max allowed size of a video in MB. Default: 1100.                                                                                                               |
| `--rm-cache`  | `-r` | Delete the yt-dlp cache on start.                                                                                                                               |
| `--backwards` | `-b` | Reverse all playlists and download in backwards order.                                                                                                          |
| `--threads`   |      | How many download processes to use (threads). Default is how many CPU cores you have. You will want to find a good value that doesn't overload your connection. |
| `--daemon`    | `-d` | Run in daemon mode. Disables progress bars. Daemon mode isn't implemented yet.                                                                        |
 
