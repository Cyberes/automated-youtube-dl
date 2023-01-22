# Example systemd Service

`/etc/systemd/system/youtube-dl.service`

```systemd
[Unit]
Description=Youtube-DL Daemon
After=network-online.target

[Service]
ExecStart=/usr/bin/python3 /home/user/automated-youtube-dl/downloader.py --daemon --silence-errors --sleep 60 "https://www.youtube.com/playlist?list=example12345" "/mnt/nfs/archive/YouTube/Example Playlist/"
User=user
Group=user

[Install]
WantedBy=multi-user.target
```

Now start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now youtube-dl
```



You can watch the process with:

```bash
sudo journalctl -b -u youtube-dl.service
```

