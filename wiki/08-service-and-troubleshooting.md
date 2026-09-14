# 7. Run as a service and troubleshooting

## Auto-start service

The installer sets up a service called `liquorice` and turns it on, so the box starts on its own every time it powers up. You do not need to log in and launch anything.

The service runs `main.py` from the project folder as the user who ran the installer, and restarts it if it crashes.

### Managing the service

```bash
sudo systemctl status liquorice     # check the status
sudo systemctl restart liquorice    # restart after a config or code change
sudo systemctl stop liquorice       # stop it
sudo systemctl start liquorice      # start it again
```

### Watching the logs

```bash
journalctl -u liquorice -f          # live service output
```

The app also writes its own log to `~/liquorice/liquorice.log`, you can set also log location in `config.json` setting `log_path`

### Manual running

To run it yourself (for example while testing), stop the service first, so two copies do not fight over the hardware:

```bash
sudo systemctl stop liquorice
cd ~/liquorice-backup
sudo .venv/bin/python software/main.py
```

### If you move or rename things

The service file is installed from `systemd/liquorice.service`: the installer rewrites the user, the working directory, the Python path and the command with the ones it finds when you run it. So any username and any project path work. If you move the project, or want to run it as another user, just run the installer again from the new location, as that user:

```bash
./install.sh
sudo systemctl restart liquorice
```

To see what was generated:

```bash
systemctl cat liquorice
```

## Troubleshooting

### The screen stays blank

- Check the reset pin. The driver must use BCM 27:

  ```bash
  .venv/bin/python -c "import waveshare_epd.epdconfig as e; print('RST:', e.RST_PIN)"
  ```

  It must print `RST: 27`. If not, run `./install.sh` again.

- Check both SPI devices are there:

  ```bash
  ls -l /dev/spidev*
  ```

  You need `/dev/spidev0.0` (display) and `/dev/spidev0.1` (card reader). If they are missing, SPI is off run the installer again and reboot. Make sure you have the **V4** panel; other versions need a different driver. Remember the lid: if the reed switch reads "closed", the screen sleeps. Open the lid, or move the magnet away.

### The LED strip does nothing

- The LED needs GPIO access. The installer adds your user to the `gpio` group, but that only takes effect after a reboot or a fresh login.
- Under the `liquorice` service the strip also needs to write to `/dev/mem` (the WS2812B driver drives PWM through DMA). The unit file grants it with

  ```
  AmbientCapabilities=CAP_SYS_RAWIO CAP_DAC_OVERRIDE
  ```

  Both are required: with only one of them the library crashes with a segmentation fault. If the line is missing you get this in the log, and the box works but stays dark:

  ```
  LED disabilitato: permessi /dev/mem insufficienti (ws2811_init failed with code -5 (mmap() failed))
  ```

  After editing the unit, run `sudo systemctl daemon-reload && sudo systemctl restart liquorice`.
- Test it directly (may need `sudo`):

  ```bash
  sudo .venv/bin/python software/tests/hardware/test_led.py
  ```

- Check the data wire is on BCM 12 (physical pin 32).

### The card is not found

- Check the reader and mount state:

  ```bash
  software/tests/hardware/mount-sdcard.sh status
  ```

  The same script also does `mount` and `umount`.
- In `config.json`, `sd_mount` should be `true` for a real reader. Set it to `false` only when you fake the card with a local folder.
- The card is expected at `/mnt/liquorice-sd` (the `sd_src` setting in `config.json`)

### The buttons do the wrong thing

- Check the wiring against [Wiring and assembly](02-wiring-and-assembly.md):
  Up = BCM 5, Down = BCM 6, Confirm/Right = BCM 13, Back/Left = BCM 19, other side to ground
- Test which button is which:

  ```bash
  .venv/bin/python software/tests/hardware/test_buttons.py
  ```

### Uploads fail

- Check the destination is reachable from the Pi:

  ```bash
  rclone listremotes
  rclone ls <your-remote>:
  ```

- A login error, or an unrecoverable rclone exit code (1, 3, 4, 7), stops the backup and shows `Error` on the screen. Fix the remote or the login, then start the backup again
- Read `~/liquorice/liquorice.log` and `journalctl -u liquorice -f` for the exact message

### Cannot reach the web page

- Get the IP from *WiFi > Show IP*, then open `http://<box-ip>:5000`.
- The web page only runs while the box's hotspot is on. Use *WiFi > Start AP + Web server*, join the box's own network, then open the page

### "AP error!" on the screen when starting the hotspot

- Read the log: `journalctl -u liquorice -e`. A generic `Error starting AP: Connection activation failed` almost always means the AP profile was built for an interface that does not exist. NetworkManager says it plainly:

  ```bash
  journalctl -u NetworkManager -e | grep "Liquorice AP"
  # ... result="fail" reason="No suitable device found for this connection
  # (device wlan0 not available because profile is not compatible with device
  # (mismatching interface name))."
  ```

- The cause is `WIFI_INTERFACE` in `.env`. On the Raspberry Pi the Wi-Fi device is `wlan0`, not the `wlp0s...`/`wlx...` name a desktop Linux gives it. Check the real name and fix the file:

  ```bash
  nmcli -t -f DEVICE,TYPE device status | grep ':wifi$'
  ```

  The app now falls back to the first real Wi-Fi device and logs a warning (`Wi-Fi interface '...' not found ... using 'wlan0' instead`), but it is better to correct `.env` and restart the service.
- The AP password must be at least 8 characters, otherwise WPA2 refuses it. A shorter one is rejected up front and the screen shows `AP PASSWORD < 8 CHAR!`.
- `Error starting AP: [Errno 2] No such file or directory: 'iptables'` was a different case: the hotspot was really up (you could see the SSID) but the captive portal setup failed, so the screen said `AP error!` and the web server never started. Recent Raspberry Pi OS images only ship `nft`, not `iptables`. The app now uses whichever of the two is installed, and a failure here no longer stops the AP or the web page: it only logs `Captive portal redirect not active: open http://192.168.4.1:5000 by hand`.
- Whenever the AP fails to start, the log also gets a diagnostic block written on purpose for the case where the box is unreachable and you can only read the card afterwards:

  ```
  AP diagnostics: interface=wlan0 (configured=wlan0, available=wlan0) firewall=nft(/usr/sbin/nft) openssl=/usr/bin/openssl
  AP diagnostics [nmcli -f]: DEVICE  TYPE  STATE  CONNECTION | wlan0  wifi  disconnected  --
  AP diagnostics [nmcli -f]: RUNNING  STATE  WIFI  WIFI-HW | running  connected  enabled  enabled
  AP diagnostics [rfkill list]: ...
  ```

  `WIFI: disabled` or a soft-blocked radio in `rfkill` explains an activation failure that otherwise looks generic.

### The hotspot is on but you are not sure about the web page

The legend at the bottom of the screen always reports it after *Start AP + Web server*:

- `web 192.168.4.1:5000` : hotspot and web page both up, open that address
- `AP ok - WEB ERROR!` : hotspot up, web server failed to start (usually port 5000 already in use). The reason is in `~/liquorice/liquorice.log` as `Error starting Flask on ...`
- `AP error!` / `AP PASSWORD < 8 CHAR!` / `NO AP PASSWORD!` : the hotspot itself did not start, see above

### The screen freezes and the buttons do nothing after Start/Stop AP

This was a real bug, fixed: the nmcli calls ran inside the button handler, so the main loop stopped reading buttons and stopped refreshing the e-ink until NetworkManager was done, which with several saved networks could take minutes. Now both entries work in a background thread: the screen shows `Starting AP...` / `Stopping AP...` immediately and the menu stays usable, and a second request while one is running is refused with `WiFi busy...`.

If it still happens, the block is elsewhere. Check the log for the last line before the silence (`~/liquorice/liquorice.log`) and look for a slow SD mount or a stuck e-ink refresh (`journalctl -u liquorice -e`).

### `ModuleNotFoundError: No module named 'PIL'` in mock mode

You are running the Pi's `.venv` from another computer (typically with the card mounted under `/run/media/...`). That environment was built by the Pi's Python and its packages are in `lib/python3.11/`, invisible to a different Python version. Use a separate environment, as described in [Install the software](04-install-software.md#running-mock-mode-on-the-pis-card-from-a-pc), and do not run `./install.sh --mock` from the card: it would replace the Pi's packages with your PC's. The installer refuses this on purpose now.

### "Connect" on the web page just kills the hotspot

Fixed. The list used to send *Connect* with no password, so on a secured network NetworkManager answered `Secrets were required, but not provided` — but by then the hotspot was already down, and the restore failed too (`Disconnecting device failed`), leaving the box with neither the hotspot nor a network. Now a secured network that is not saved yet asks for its password in the list, the request is refused before the radio is touched if the password is missing, and `nmcli device disconnect` failing no longer stops the hotspot from coming back.

### The screen freezes and the box gets slow, and the log says BUSY

```
display - ERROR :: e-Paper BUSY alto da oltre 20s: frame non confermato, a schermo resta l'immagine vecchia...
```

The e-ink controller is not releasing its BUSY line, so the panel never confirms the refresh. The app gives up on that wait after 20 seconds, but always lets the driver finish its command sequence: it never interrupts it mid-way, because aborting leaves the panel with half a frame and the screen fills with black and white dots, which is worse than a stale image. The wait is abandoned once per frame, not once per command, so a failed redraw costs 20 seconds and not four times that.

What you see: the image stays as it was, while backup, LED and the web page keep working. Each redraw still pays those 20 seconds, so button presses feel like they hang until the panel recovers on its own.

If it does not come back, it is hardware side:

- check the CS, DC, RST and BUSY wiring against [Wiring](02-wiring.md), BUSY is BCM 24
- power-cycle the box completely (the panel keeps its state across a reboot of the Pi, so a `systemctl restart` is not enough)
- suspect the supply: Wi-Fi transmit peaks plus the LED strip can brown out a weak one, and the panel is the first thing to wedge

A different symptom, with the same wiring causes, is a panel that never raises BUSY at all: nothing appears on screen but the box stays perfectly responsive. That one the app detects separately, with `Il display non ha eseguito il refresh (BUSY mai attivo)` in the log, and it tries a hardware reset on the RST line before giving up.

### The box has no network after "Stop AP"

*Stop AP* tries the network that was active before the hotspot, then lets NetworkManager pick the best saved one, then tries every other saved profile (the ones the scan can see first). The screen shows the result: `WiFi: <network name>`, and the status screen reads `WiFi: Connected (<network name>)`. If none of them works you get the plain `◀ menu ▶ backup` legend, `WiFi: Disconnected`, and `Could not reconnect to any known Wi-Fi network` in the log. Check what the Pi has saved with:

```bash
nmcli -t -f TYPE,TIMESTAMP,NAME connection show | grep 802-11-wireless
```

If the network you expect is not there, add it from the web page while the hotspot is on.

If you started at chapter 1 and worked through to here, you now have a working Liquorice Backup box.
