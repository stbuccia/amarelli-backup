

# Liquorice Backup

This project turns a cute Amarelli liquorice tin (like [these](https://www.amarelli.it/categoria-prodotto/liquirizia/?jsf=jet-engine%3Amain-loop&tax=pa_confezione%3A595%3Bpa_peso%3A592%2C593)) into a small photo backup box.

You put your camera's micro sd card into the box and the box copies the photos and sends them to a place you pick: Webdav server, Nextcloud, Google Drive, Dropbox, and more. A small screen shows the progress, an LED strip shows the state by colour, and you can interact with buttons and scrren and changing options with menu. You could also configure wifi and some options via web page accessible from external device.

## Demo

### 1. Caching, upload and pause: `demo.mp4`

Shows how the box copies photos to the local cache immediately (no internet needed), then uploads them in background when Wi-Fi is available, with the ability to pause/resume the upload from the buttons/menu.

https://github.com/user-attachments/assets/9cb672e0-f81e-46bb-84d8-f59a53d57a41


### 2. Closing the tin and screen lock: `cover.mp4`

Closing the lid triggers the screen lock / cover handling.

https://github.com/user-attachments/assets/318411bd-aac7-48a8-9b28-a56dbcda2e6b

### 3. Configuring another Wi-Fi: `wifi.mp4`

How to connect to a new Wi-Fi network from the box: start the access point from the menu, connect from phone/laptop and open `http://<box-ip>:5000` to enter the new credentials.

https://github.com/user-attachments/assets/718ee54f-ab58-4cac-961d-e77d3bd64055

This guide takes you from zero to a working box. Read the chapters in order the first time.

## Chapters

1. [What you need](01-what-you-need.md): the parts to buy, where do you find them and how much they cost
2. [Wiring and assembly](02-wiring-and-assembly.md): how to connect the parts in the board
3. [Prepare the SD card and OS](03-prepare-os.md): set up Raspberry Pi OS, user and service
4. [Install the software](04-install-software.md): run the installer
5. [Backup destination](05-backup-destination.md): configure cloud service where photos go
6. [Daily use](06-daily-use.md): User guide
7. [Run as a service and troubleshooting](07-service-and-troubleshooting.md): if you have a problem you should check here

## How it works

- You insert the camera card into a small card reader on the box
- The box copies the photos to a local cache first, then uploads them
- For the caching internet connection is not needed, for the upload sd card is not needed
- A small database remembers what it already sent, so it never sends the same file twice
- You can check the box work watching the eink screen or the led colour
- To connect to an unkwown wifi net, you can start an access point from menu, and then connecting from an external device, then going to the web page at `http://<box-ip>:5000`, and setting wifi credentials

## Two ways to run it

- **On the Raspberry Pi**: the real box, with screen, buttons, LED and card reader
- **Mock mode on a normal PC**: no hardware. Good for trying the software in your everyday PC
