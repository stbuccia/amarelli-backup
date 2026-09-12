# 5. Backup destination

The box needs to know where to send your photos. There are two ways:

| Backend (`uploader`) | Where photos go |
|---|---|
| `webdav` | A WebDAV server (kDrive, Nextcloud, ownCloud, pCloud, and similar). |
| `rclone` | Anything rclone supports: Google Drive, Dropbox, OneDrive, S3, Backblaze... |

> This project has been tested with **kDrive** (over WebDAV) and **Dropbox**
> (over rclone). Other services should work, but those two are the known-good
> paths.

You pick the backend in `config.json`, or from the web page at `http://<box-ip>:5000/config` (the *Backup destination* section). A change takes effect on the next backup. The target folder is `cloud_dst` in both cases.

## The two settings files

- **`config.json`** (in the project root): general settings. The backend, the rclone remote, the cache paths, the file filter.
- **`.env`** (in the project root): your secrets. WebDAV and Wi-Fi logins. This file is not in git, so it stays private.

If you have not created `.env` yet, do it now:

```bash
cd ~/liquorice-backup
cat > .env <<'EOF'
WEBDAV_HOSTNAME=
WEBDAV_FOLDER=
WEBDAV_LOGIN=
WEBDAV_PASSWORD=
WIFI_AP_SSID=Liquorice
WIFI_AP_PASSWORD=change-me
WIFI_INTERFACE=wlan0
EOF
chmod 600 .env
```

## Option A: WebDAV

Put your server details in `.env`. Example for kDrive:

```dotenv
WEBDAV_HOSTNAME=https://YOUR-ID.connect.kdrive.infomaniak.com
WEBDAV_FOLDER=liquorice-backup
WEBDAV_LOGIN=you@example.com
WEBDAV_PASSWORD=your-password
```

For Nextcloud or ownCloud, `WEBDAV_HOSTNAME` looks more like `https://cloud.example.com/remote.php/dav/files/you`

Set the backend in `config.json`:

```json
"uploader": "webdav"
```

## Option B: rclone (good for cloud services)

The installer already put `rclone` on the Pi. Set up a remote once (on the Pi, or on your PC and copy it over):

```bash
rclone config          # make a remote, for example "dropbox"
rclone listremotes     # see what exists  ->  e.g. "dropbox:"
rclone ls dropbox:     # check you can reach it
```

Then tell the box to use rclone, in `config.json`:

```json
"uploader": "rclone",
"rclone_remote": "dropbox:liquorice-backup"
```

Or set the same remote from the web page (`/config`, field *rclone remote*), which lists the remotes it finds

### What `rclone_remote` accepts

- `dropbox:liquorice-backup`: a remote plus a subfolder
- `dropbox`: the root of the remote (you can avoid `:`)
- `/mnt/usb/backup`: a local folder (USB stick or disk); no remote needed
- empty: uses the first remote from `rclone listremotes`

More `config.json` keys you can set: `rclone_binary` (path to the program), `rclone_config` (a different config file), and `rclone_timeout` (seconds per command, default 300). The remote can also live in `.env` as `RCLONE_REMOTE`, used only when `rclone_remote` is empty.

### Copy an existing config to the Pi

If rclone is already set up on your PC, copy the config instead of doing it again:

```bash
scp ~/.config/rclone/rclone.conf <your-pi-user>@liquorice.local:~/.config/rclone/rclone.conf
```

## Retries and errors

The app calls rclone with `--retries 1` and handles retries itself. A short network error restarts the upload step. A login error, or an unrecoverable rclone exit code (1, 3, 4, 7), stops the backup and shows `Error` on the screen.

## Mock tip

To test on a laptop with `--mock`, use a local folder as the remote (for example `/tmp/fake-dropbox`); in mock mode any folder counts as the fake card

Once your destination is set, learn how to use the box: [Daily use](06-daily-use.md).
