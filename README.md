# Liquorice Backup

Liquorice Backup is a liquorice tin backup box. 

## Why

As a photographer travelling without a laptop, you need a safe way to free your camera SD card anywhere. This project was born for that:

* Insert the camera SD into the box: it copies every new photo to a local cache immediately, so you can remove the card right away and keep shooting
* No internet needed for caching; no SD needed for uploading. The box uploads in background to your cloud when Wi-Fi is available
* A small database avoids re-uploading the same file twice

It is a low-cost, open-source alternative to commercial backup devices, built inside an Amarelli liquorice tin.

This project was made for the [Laboratorio di Making](https://www.unibo.it/it/studiare/insegnamenti-competenze-trasversali-moocs/insegnamenti/insegnamento/2025/545359) exam at the University of Bologna.

## How it works

You put your camera microSD card in the box and it backups your photo copying them locally, and then uploading in your favorite cloud storage (WebDav Server ory any place with rclone supports like Dropbox, Google Drive and over 70 more cloud storages). E-ink screen show you the progress, four buttons allow you to interact and a LED show the status with the colour. This device is mostly inteded for travels, since usually you don't have a device with you to use for backup 

You can check bu yourself in this demo video:

...

## Documentation

The full step-by-step guide is in the [wiki](wiki/Home.md). Follow the chapters in order the first time:

1. [What you need](wiki/01-what-you-need.md) - parts lists, where to buy and the prices
2. [Wiring and assembly](wiki/02-wiring-and-assembly.md) - how to connect everything
3. [Prepare the SD card and OS](wiki/03-prepare-os.md) - Raspberry Pi OS, SSH and Wi-Fi
4. [Install the software](wiki/04-install-software.md) - The process of installing the project
5. [Backup destination](wiki/05-backup-destination.md) - WebDAV or rclone
6. [Daily use](wiki/06-daily-use.md) - screen, buttons, LED and web page
7. [Run as a service and troubleshooting](wiki/07-service-and-troubleshooting.md) - if you come in to errors check this page for a solution

## Quick start

On the Raspberry Pi, after cloning the repository:

```bash
./install.sh          # installs everything and enables the service
sudo reboot
```

The box starts on its own through the `liquorice` service. To try the software on a PC with no hardware:

```bash
./install.sh --mock
.venv/bin/python software/main.py --mock
```

More in [Install the software](wiki/04-install-software.md).

## Repository layout

+ `software/`: the Python app
+ `config.json`: app settings
+ `.env`: secrets (WebDAV, Wi-Fi). You create this yourself; keep it private and out of git
+ `software/tests/hardware/`: small scripts to test each part
+ `hardware/`: wiring, schematic and electronics notes
+ `systemd/`: the service unit and system rules
+ `wiki/`: the step-by-step guide

## Credits

- [Amarelli Fabbrica di Liquirizia SRL](https://www.amarelli.it/) a company which produces delicious liquorice and very nice tin boxes (that i collect)
- [rclone project](https://rclone.org/) , that make my project more universal allowing to backup photos to every possible (virtual) place
- [@sudomod_wermy](https://linktr.ee/sudomod_wermy) which inspires me with him with his [MintyPi](). Sadly the project page is actually down.
- Luca Jacopo, a friend which lent me his 3d printer
