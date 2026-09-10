# 7. Run as a service and troubleshooting

## Auto-start service

The installer sets up a service called `liquorice` and turns it on, so the box starts on its own every time it powers up. You do not need to log in and launch anything.

The service runs `main.py` from the project folder as the `raspberry` user, and restarts it if it crashes.

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

### If you used a different username

The service expects the project at `/home/raspberry/liquorice-backup` and the user `raspberry`. If your username or path is different, edit `systemd/liquorice.service` (the `User=`, `WorkingDirectory=`, `Environment=` and `ExecStart=` lines), then reinstall it:

```bash
sudo install -m 0644 systemd/liquorice.service /etc/systemd/system/liquorice.service
sudo systemctl daemon-reload
sudo systemctl restart liquorice
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
  Up = BCM 13, Down = BCM 6, Left = BCM 5, Right = BCM 19, other side to ground
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
- On a network you do not control, use *WiFi > Start hotspot*, join the box's own network, then open the page

If you started at chapter 1 and worked through to here, you now have a working Liquorice Backup box.
