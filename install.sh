#!/usr/bin/env bash
# Installs Amarelli Backup and configures the Raspberry Pi SPI peripherals.
set -Eeuo pipefail

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
VENV_DIR="$PROJECT_DIR/.venv"
BOOT_CONFIG=""
SPI_OVERLAY='dtoverlay=anyspi,spi0-1,dev=mmc-spi-slot,speed=10000000'

fail() {
    printf 'Error: %s\n' "$*" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

configure_boot() {
    local line=$1

    if ! sudo grep -Fqx -- "$line" "$BOOT_CONFIG"; then
        printf '\n# Amarelli Backup SPI configuration\n%s\n' "$line" |
            sudo tee -a "$BOOT_CONFIG" >/dev/null
        printf 'Added %s to %s\n' "$line" "$BOOT_CONFIG"
    else
        printf 'Already configured: %s\n' "$line"
    fi
}

configure_spi_overlay() {
    if sudo grep -q '^dtoverlay=anyspi,spi0-1,dev=mmc-spi-slot' "$BOOT_CONFIG"; then
        sudo sed -i "s|^dtoverlay=anyspi,spi0-1,dev=mmc-spi-slot.*|$SPI_OVERLAY|" "$BOOT_CONFIG"
        printf 'Configured SD-card SPI overlay: %s\n' "$SPI_OVERLAY"
    else
        configure_boot "$SPI_OVERLAY"
    fi
}

if [[ ${EUID} -eq 0 ]]; then
    fail "Run this script as the regular Raspberry Pi user, not as root."
fi

require_command sudo
require_command apt-get
require_command python3

if [[ -f /boot/firmware/config.txt ]]; then
    BOOT_CONFIG=/boot/firmware/config.txt
elif [[ -f /boot/config.txt ]]; then
    BOOT_CONFIG=/boot/config.txt
else
    fail "Raspberry Pi boot configuration file not found."
fi

printf 'Installing system dependencies...\n'
sudo apt-get update
sudo apt-get install -y \
    git \
    network-manager \
    python3-dev \
    python3-pip \
    python3-venv \
    libjpeg-dev \
    libfreetype6-dev \
    zlib1g-dev \
    rclone

printf 'Configuring SPI at boot...\n'
configure_boot 'dtparam=spi=on'
# The e-ink display uses SPI0 CE0; the SD-card reader is exposed on SPI0 CE1.
configure_spi_overlay

printf 'Preparing SD card mount point...\n'
sudo mkdir -p /mnt/amarelli-sd
sudo chown "$USER":"$USER" /mnt/amarelli-sd

printf 'Preparing persistent application data directory...\n'
mkdir -p "$HOME/amarelli/cache"
if [[ -f $PROJECT_DIR/files.db && ! -f $HOME/amarelli/files.db ]]; then
    cp "$PROJECT_DIR/files.db" "$HOME/amarelli/files.db"
    printf 'Migrated existing database to %s\n' "$HOME/amarelli/files.db"
fi

printf 'Installing Python dependencies in %s...\n' "$VENV_DIR"
if [[ ! -d $VENV_DIR ]]; then
    python3 -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install '.[raspberry-pi]'

if [[ ! -d $PROJECT_DIR/software/waveshare_epd ]]; then
    printf 'Installing Waveshare e-paper library...\n'
    temp_dir=$(mktemp -d)
    trap 'rm -rf "$temp_dir"' EXIT
    git clone --depth 1 https://github.com/waveshare/e-Paper.git "$temp_dir/e-Paper"
    cp -a "$temp_dir/e-Paper/RaspberryPi_JetsonNano/python/lib/waveshare_epd" \
        "$PROJECT_DIR/software/"
fi

# GPIO 17 is reserved by this project; the display reset line is BCM 27.
sed -i '0,/RST_PIN  = 17/s//RST_PIN  = 27/' \
    "$PROJECT_DIR/software/waveshare_epd/epdconfig.py"

printf 'Installing Waveshare e-paper library in the virtual environment...\n'
site_packages=$("$VENV_DIR/bin/python" -c 'import site; print(site.getsitepackages()[0])')
rm -rf "$site_packages/waveshare_epd"
cp -a "$PROJECT_DIR/software/waveshare_epd" "$site_packages/"

if command -v dtoverlay >/dev/null 2>&1; then
    printf 'Applying the SD-card SPI overlay for this session...\n'
    if ! sudo dtoverlay anyspi spi0-1 dev=mmc-spi-slot speed=10000000; then
        printf 'The overlay was saved for the next reboot but could not be applied now. Reboot the Raspberry Pi.\n' >&2
    fi
else
    printf 'dtoverlay is unavailable; the overlay will be loaded at the next reboot.\n' >&2
fi

printf 'Configuring GPIO permissions for LEDs (rpi_ws281x)...\n'
if id -nG "$USER" | tr ' ' '\n' | grep -qx gpio; then
    printf 'User %s already in gpio group.\n' "$USER"
else
    if sudo usermod -a -G gpio,kmem,spi "$USER" 2>/dev/null; then
        printf 'Added %s to gpio,kmem,spi groups (logout/login or reboot required).\n' "$USER"
    else
        printf 'Warning: could not add %s to gpio groups.\n' "$USER" >&2
    fi
fi
if [[ ! -f /etc/udev/rules.d/99-gpio.rules ]]; then
    printf 'Installing udev rule for gpiomem...\n'
    echo 'SUBSYSTEM=="bcm2835-gpiomem", GROUP="gpio", MODE="0660"' | sudo tee /etc/udev/rules.d/99-gpio.rules >/dev/null
    sudo udevadm control --reload-rules 2>/dev/null || true
fi

printf '\nInstallation complete. Reboot the Raspberry Pi to activate SPI and the SD-card reader.\n'
printf 'Run the application with: .venv/bin/python software/main.py\n'
printf 'Note: LED strip (rpi_ws281x on GPIO18/Pin12) needs /dev/mem access.\n'
printf '  - After first install: reboot or logout/login to apply gpio group.\n'
printf '  - Test LEDs with: sudo .venv/bin/python software/tests/hardware/test_led.py\n'
printf '    (sudo may still be required for PWM/DMA on some kernels).\n'
