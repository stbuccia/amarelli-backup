# 4. Install the software

The project has an installer script. It does the hard work: system packages, SPI setup, the Python environment, the display driver, GPIO permissions, and the auto-start service.

Run it from inside the project folder, as your normal user. Do not use `sudo`; the script asks for `sudo` itself when it needs it.

```bash
cd ~/liquorice-backup
./install.sh
```

## What the installer does

- Installs system packages: `git`, `network-manager`, Python build tools, image libraries, and `rclone`.
- Turns on SPI and adds the setting for the card reader (at 10 MHz), so both chip-selects show up.
- Creates the mount point `/mnt/liquorice-sd` and the data folder `~/liquorice/cache`
- Creates a Python environment in `.venv` and installs the app into it
- Downloads the Waveshare screen driver, fixes the reset pin to BCM 27, and copies it into the environment
- Adds your user to the `gpio`, `kmem` and `spi` groups, so the LED strip and GPIO work
- Installs and enables the `liquorice` service, so the box starts on its own

## Reboot

Reboot so the SPI setting and the new group memberships take effect:

```bash
sudo reboot
```

## Create the .env file

Your secrets do not live in the code. You must create a file called `.env` in the project folder yourself. It holds your backup login and your Wi-Fi hotspot settings. It is kept out of git on purpose, so it is never shared.

Create it now with the keys below (fill in your own values later, in chapter 5):

```bash
cd ~/liquorice-backup
cat > .env <<'EOF'
# WebDAV backup (fill these in only if you use WebDAV)
WEBDAV_HOSTNAME=
WEBDAV_FOLDER=
WEBDAV_LOGIN=
WEBDAV_PASSWORD=

# Wi-Fi hotspot the box can start on its own
WIFI_AP_SSID=Liquorice
WIFI_AP_PASSWORD=change-me
WIFI_INTERFACE=wlan0
EOF
chmod 600 .env
```

Chapter 5 explains what to put in each key. If you use rclone (Google Drive, Dropbox, and so on), you can leave the WebDAV keys empty

## Check that it worked

After the reboot, log back in and run a few checks

**Both SPI devices are there** (display on `0.0`, card reader on `0.1`):

```bash
ls -l /dev/spidev*
```

You should see `/dev/spidev0.0` and `/dev/spidev0.1`

**The screen driver uses the right reset pin (BCM 27):**

```bash
cd ~/liquorice-backup
.venv/bin/python -c "import waveshare_epd.epdconfig as e; print(e.__file__); print('RST:', e.RST_PIN)"
```

The output must show `RST: 27`

**Test each part of the hardware** with the small scripts in `software/tests/hardware/`. Run these now, right after wiring and installing, so you catch any wiring mistake early:

```bash
.venv/bin/python software/tests/hardware/test_display.py        # writes "Hello world" on the screen
.venv/bin/python software/tests/hardware/test_buttons.py        # prints which button you press
.venv/bin/python software/tests/hardware/test_reed_switch.py    # shows lid open/closed
sudo .venv/bin/python software/tests/hardware/test_led.py       # lights up the LED strip
software/tests/hardware/mount-sdcard.sh status                  # shows the card reader state
```

The LED test may need `sudo`, because the LED strip uses PWM/DMA, which some systems only allow as root.

## Trying it without a Raspberry Pi (mock mode)

You can run the software on a normal PC to explore the app and the web page, with no hardware. Use the `--mock` flag:

```bash
./install.sh --mock
.venv/bin/python software/main.py --mock
```

Mock mode only creates the environment, installs the dependencies, and prepares `~/liquorice`. It does not touch SPI, GPIO, the service, or the screen driver. To fake a card, point `sd_src` at a local folder (mock install makes `~/liquorice/fake-sd`), set `sd_mount` to `false`, and drop a few `.jpg` files in there. See chapter 5 for the config file. Next, pick where your photos should go: [Backup destination](05-backup-destination.md).
