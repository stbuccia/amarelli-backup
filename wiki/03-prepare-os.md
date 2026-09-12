# 3. Prepare the SD card and OS

Here you put a working Raspberry Pi OS on the Pi's own microSD card (not the camera card) and log in over the network

## 1. Write the operating system

1. Download and open **Raspberry Pi Imager** on your computer
2. Choose **Raspberry Pi OS Lite (32-bit)**. "Lite" has no desktop, which is what this project wants
3. Choose the Pi's microSD card as the target
4. Open the settings (the gear icon) before you write, and set:
   - **Hostname** -- for example `liquorice`. Then you can reach the box as `liquorice.local`.
   - **Username** -- pick any username you like, with your own password. The installer adapts the service to whatever user you choose
   - **Enable SSH** -- turn it on, with password login
   - **Wi-Fi** -- enter your network name, password, and country
5. Write the card and wait for it to finish.

> The examples below use the username `raspberry`: replace it with yours. Nothing
> in the project depends on it, the service is generated at install time from the
> user and the folder you install from.

## 2. First boot and login

1. Put the card in the Pi (the Pi's own slot, not the external reader)
2. Power the Pi on. Wait a minute or two for the first boot
3. From your computer, connect over SSH:

   ```bash
   ssh raspberry@liquorice.local
   ```

   Use your own username instead of `raspberry`. If `liquorice.local` does not work, find the Pi's IP address in your router and use it: `ssh <user>@<ip>`

## 3. Update the system

Once you are logged in:

```bash
sudo apt update && sudo apt full-upgrade -y
sudo reboot
```

Log back in after the reboot

## 4. Check Python

The software needs Python 3.10 or newer. Raspberry Pi OS Lite already has it.
Check:

```bash
python3 --version
```

## 5. Get the project

Clone the project into your home folder, so it ends up at `~/liquorice-backup`:

```bash
cd ~
git clone <repository-url> liquorice-backup
cd liquorice-backup
```

If `git` is missing, install it first with `sudo apt install -y git`

Now install the software: [Install the software](04-install-software.md).
