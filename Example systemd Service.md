# Example systemd Service

`/home/user/youtubedl-daemon.sh`
```bash
#!/bin/bash
SLEEP_TIME="60m"
while true; do
        /usr/bin/python3 /home/user/automated-youtube-dl/downloader.py --daemon "https://www.youtube.com/playlist?list=example12345" "/mnt/nfs/archive/YouTube/Example Playlist/"
        echo -e "\nSleeping for $SLEEP_TIME"
        sleep $SLEEP_TIME
        echo -e "\n"
done
```



`/lib/systemd/system/youtubedl.service`
```systemd
[Unit]
Description=Youtube-DL Daemon
After=network-online.target

[Service]
ExecStart=/home/user/youtubedl-daemon.sh
User=user
Group=user

[Install]
WantedBy=multi-user.target
```

Now start the service
```bash
chmod +x /home/user/youtubedl-daemon.sh
sudo systemctl daemon-reload
sudo systemctl enable --now youtubedl
```
