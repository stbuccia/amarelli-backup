# Amarelli Backup

This project turns a cute Amarelli liquorice tin (like [these](https://www.amarelli.it/categoria-prodotto/liquirizia/?jsf=jet-engine%3Amain-loop&tax=pa_confezione%3A595%3Bpa_peso%3A592%2C593)) into a small photo backup box.

You put your camera's micro sd card into the box and the box copies the photos and sends them to a place you pick: Webdav server, Nextcloud, Google Drive, Dropbox, and more. A small screen shows the progress, an LED strip shows the state by colour, and you can interact with buttons and scrren and changing options with menu. You could also configure wifi and some options via web page accessible from external device.

This guide takes you from zero to a working box. Read the chapters in order the first time.

## Chapters

1. [What you need](01-what-you-need.md) — the parts to buy
2. [Wiring and assembly](02-wiring-and-assembly.md) — how to connect the parts
3. [Prepare the SD card and OS](03-prepare-os.md) — set up Raspberry Pi OS
4. [Install the software](04-install-software.md) — run the installer
5. [Backup destination](05-backup-destination.md) — pick where photos go
6. [Daily use](06-daily-use.md) — screen, buttons, LED, web page
7. [Run as a service and troubleshooting](07-service-and-troubleshooting.md)

## How it works

- You insert the camera card into a small card reader on the box
- The box copies the photos to a local cache first, then uploads them
- For the caching internet connection is not needed, for the upload sd card is not needed
- A small database remembers what it already sent, so it never sends the same file twice
- You can check the box work watching the eink screen or the led colour
- To connect to an unkwown wifi net, you can start an access point from menu, and then connecting from an external device, then going to the web page at `http://<box-ip>:5000`, and setting wifi credentials

## Two ways to run it

- **On the Raspberry Pi** — the real box, with screen, buttons, LED and card reader
- **Mock mode on a normal PC** — no hardware. Good for trying the software and the web page. Chapters point this out where it helps
