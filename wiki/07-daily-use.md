# 6. Daily use

Day to day, you use three things: the screen, the four buttons, and the LED strip. There is also a web page for settings.

## Making a backup

1. Take the microSD card out of your camera
2. Put it in the box's card reader
3. The box finds the card and mounts it at `/mnt/liquorice-sd`. The screen shows `Ready`
4. Start the backup (press the confirm button, or let it run on its own in automatic mode, see below)
5. The box copies the photos to a local cache, then uploads them. The screen shows the progress
6. When the LED turns green and the screen says it is done, take the card out

If there is no card and nothing waiting in the cache, the screen shows `Waiting for SD card`.

## The buttons

There are four buttons, from left to right they are: **Back/Left**, **Down**, **Up**, **Confirm/Right**.

In the menu:

- **Up / Down**: move between items
- **Confirm**: open a submenu or choose a value
- **Left**: go back, or close the menu at the top level

During a backup:

- Any button **pauses** the backup. This is on purpose, so it works no matter how your buttons are wired
- While paused: **Confirm** resumes, **Back** opens the menu

## The menu on the box

Press Left from the main screen to open the menu:

- **WiFi**
  - *Start hotspot* : the box makes its own Wi-Fi network, so you can reach the web page when there is no other network
  - *Start web server*: start the settings web page
  - *Show IP* : show the box's IP address
  - *Reset WiFi* : stop the hotspot / clear the Wi-Fi setup
- **Mode**
  - *Upload only* : copy photos up; never delete on the remote
  - *Mirroring* : make the remote match the source (can delete remote files)
- **Cache** : how long to keep the local copies after upload
  - *Delete now*, *After 7 days*, *After 30 days*, *Keep forever*
- **File type** : what to back up
  - *All files*, *Photos only (JPG+RAW)*, *JPG only*
- **Operation**
  - *Manual*: you confirm each backup
  - *Automatic (LED)*: the box mounts, caches and uploads on its own; you can keep the box closed and follow it by the LED colour
- **Debug**
  - *Fake SD*: `Off (real SD)` reads from the SPI card reader, `On (fake-sd dir)` reads the photos from the local folder `~/liquorice/fake-sd` instead (the folder is created if missing). Handy to try a full backup with no card inserted; the switch takes effect right away, no restart needed.

The menu saves your choices to `config.json`.

## What the box is doing during a backup

The screen and the LED both tell you which step the box is on. There are only a handful of steps, and they mostly follow one another in order.

When you start a backup, the box first **caches** the photos: it copies them off the card onto its own storage. Then it **uploads** them to wherever you pointed it. That is the whole job in *Upload only* mode. Afterwards it may do a  **pruning**: old cached copies you asked it not to keep forever.

*Mirroring* mode is slightly different. Instead of pruning, it does a **remote cleanup**: if you deleted photos on the card (also from the camera), it removes them from the remote too, so the two match. You never see both cleanup and pruning in the same run, which one happens depends on the mode you chose.

When everything goes through, the box lands on **completed** and waits. Press the confirm button and it drops back to idle, ready for the next card.

A few things can interrupt that straight line:

- **You press a button mid-backup.** The box pauses. It remembers exactly where it was, so pressing Right picks up from that step; pressing Left opens the menu instead.
- **The network hiccups.** The box doesn't give up: it waits a moment and tries the same step again. On the screen and LED this shows as *retrying*. If it keeps failing after a few tries, it stops.
- **Something it can't fix, like a wrong password.** The box stops on **error** and shows a short message. Fix the cause, press confirm to clear it, and start again.

So the happy path is just *idle → caching → uploading → completed*, with pruning or remote cleanup slipped in near the end depending on the mode, and pause, retry and error branching off only when they need to.

## LED colours

The LED strip tells you the state at a glance:

| Colour | Meaning |
|---|---|
| White | Booting |
| Green | Ready, or done |
| Yellow | Waiting for a card |
| Blue | Copying files to the cache |
| Cyan | Uploading |
| Magenta | Cleaning up the remote / pruning old cache |
| Orange | Paused, or retrying |
| Red | Error |

During long steps (caching, uploading, cleanup, pruning, retrying) the LED blinks.

## The lid (reed switch)

When you shut the lid, the magnet trips the reed switch and the screen sleeps to save power. Open the lid to wake it. Backups keep running with the lid shut.

## The web page

The box runs a small web page. From a phone or computer on the same network: **`http://<box-ip>:5000`**

Find the box's IP with *WiFi > Show IP*. If you are away from your usual network, use *WiFi > Start hotspot* to make the box create its own network, connect to it, then open the page, and also from the web page you can set the wifi network.

Next: [Run as a service and troubleshooting](07-service-and-troubleshooting.md).
