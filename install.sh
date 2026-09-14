#!/usr/bin/env bash
# Installs Liquorice Backup and configures the Raspberry Pi SPI peripherals.
set -Eeuo pipefail

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# LIQUORICE_VENV permette di tenere un venv separato da quello del progetto:
# serve per provare la modalita' mock su un PC leggendo la card del Raspberry,
# senza toccare il venv che appartiene al Pi.
VENV_DIR="${LIQUORICE_VENV:-$PROJECT_DIR/.venv}"
BOOT_CONFIG=""
SPI_OVERLAY='dtoverlay=anyspi,spi0-1,dev=mmc-spi-slot,speed=10000000'
SYSTEMD_DIR=/etc/systemd/system
SUDOERS_DIR=/etc/sudoers.d

fail() {
    printf 'Error: %s\n' "$*" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

# Un venv appartiene all'interprete che l'ha creato. Riusarne uno costruito da
# un altro Python (tipico: il venv del Raspberry, python3.11, riletto da un PC
# con python3.14 montando la sua SD) non da' errore subito: pip ci installa
# pacchetti della macchina sbagliata e il venv del Pi resta rotto in silenzio,
# mentre l'app fallisce con "ModuleNotFoundError: No module named 'PIL'"
# perche' cerca in lib/python3.14/ invece di lib/python3.11/.
ensure_venv() {
    local cfg="$VENV_DIR/pyvenv.cfg"
    local local_version
    local_version=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
    if [[ -d $VENV_DIR ]]; then
        local venv_version=""
        [[ -f $cfg ]] && venv_version=$(sed -n 's/^version[^=]*= *//p' "$cfg" | cut -d. -f1,2)
        if [[ -z $venv_version ]]; then
            fail "$VENV_DIR exists but is not a virtualenv. Remove it or set LIQUORICE_VENV to another path."
        fi
        if [[ $venv_version != "$local_version" ]]; then
            fail "$VENV_DIR was created by Python $venv_version but this machine has $local_version.
       This usually means you are running the installer on the Raspberry Pi card from
       another computer: installing here would overwrite the Pi's environment.
       Use a separate one instead, for example:
           LIQUORICE_VENV=\"\$HOME/liquorice-mock-venv\" $0 --mock"
        fi
        return 0
    fi
    python3 -m venv "$VENV_DIR"
}

configure_boot() {
    local line=$1

    if ! sudo grep -Fqx -- "$line" "$BOOT_CONFIG"; then
        printf '\n# Liquorice Backup SPI configuration\n%s\n' "$line" |
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

usage() {
    cat <<'EOF'
Uso: ./install.sh [--mock]

  (nessuna opzione)  Installazione completa sulla Raspberry Pi: SPI, overlay del
                     lettore SD, libreria Waveshare, permessi GPIO, servizio systemd.
  --mock             Installazione per sviluppo su un PC: solo virtualenv,
                     dipendenze e cartella dati. Nessun accesso all'hardware.
EOF
}

MOCK=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --mock) MOCK=true ;;
        -h | --help)
            usage
            exit 0
            ;;
        *) fail "Opzione sconosciuta: $1 (usa --help)" ;;
    esac
    shift
done

if [[ ${EUID} -eq 0 ]]; then
    fail "Run this script as the regular user, not as root."
fi

require_command python3

# ---------------------------------------------------------------------------
# Installazione di sviluppo (--mock): niente hardware, niente sudo, niente apt.
# Serve solo per `python software/main.py --mock`.
# ---------------------------------------------------------------------------
if [[ $MOCK == true ]]; then
    printf 'Mock install (nessun hardware Raspberry Pi).\n\n'

    printf 'Installing Python dependencies in %s...\n' "$VENV_DIR"
    ensure_venv
    "$VENV_DIR/bin/python" -m pip install --upgrade pip
    # Senza l'extra raspberry-pi: spidev, lgpio, RPi.GPIO e rpi_ws281x non
    # servono in mock e su un PC non compilano.
    "$VENV_DIR/bin/python" -m pip install -e "$PROJECT_DIR"

    printf 'Preparing application data directory in %s...\n' "$HOME/liquorice"
    mkdir -p "$HOME/liquorice/cache" "$HOME/liquorice/fake-sd"

    if ! command -v rclone >/dev/null 2>&1; then
        printf '\nNota: rclone non risulta installato. Serve solo per provare upload reali\n'
        printf '      in mock; installalo dal gestore pacchetti della tua distribuzione.\n'
    fi

    cat <<EOF

Installazione mock completata.

Avvia con:  .venv/bin/python software/main.py --mock

I percorsi dati di config.json usano ~ , quindi puntano a $HOME/liquorice.
Per simulare la scheda SD imposta in config.json (o da http://localhost:5000/config):

  "sd_src": "$HOME/liquorice/fake-sd",
  "sd_mount": false

e copia qualche jpg in $HOME/liquorice/fake-sd.
EOF
    exit 0
fi

require_command sudo
require_command apt-get

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
sudo mkdir -p /mnt/liquorice-sd
sudo chown "$USER":"$USER" /mnt/liquorice-sd

printf 'Preparing persistent application data directory...\n'
mkdir -p "$HOME/liquorice/cache"

printf 'Installing Python dependencies in %s...\n' "$VENV_DIR"
ensure_venv
"$VENV_DIR/bin/python" -m pip install --upgrade pip
# Editable install: le dipendenze finiscono nel virtualenv ma il codice resta
# quello di software/, senza copie duplicate in site-packages ne' cartella build/.
"$VENV_DIR/bin/python" -m pip install -e "$PROJECT_DIR[raspberry-pi]"

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
missing_groups=""
for grp in gpio kmem spi; do
    if ! id -nG "$USER" | tr ' ' '\n' | grep -qx "$grp"; then
        missing_groups="$missing_groups $grp"
    fi
done
if [ -z "$missing_groups" ]; then
    printf 'User %s already in gpio,kmem,spi groups.\n' "$USER"
else
    if sudo usermod -a -G gpio,kmem,spi "$USER" 2>/dev/null; then
        printf 'Added %s to groups:%s (logout/login or reboot required).\n' "$USER" "$missing_groups"
    else
        printf 'Warning: could not add %s to gpio groups.\n' "$USER" >&2
    fi
fi
if [[ ! -f /etc/udev/rules.d/99-gpio.rules ]]; then
    printf 'Installing udev rule for gpiomem...\n'
    echo 'SUBSYSTEM=="bcm2835-gpiomem", GROUP="gpio", MODE="0660"' | sudo tee /etc/udev/rules.d/99-gpio.rules >/dev/null
    sudo udevadm control --reload-rules 2>/dev/null || true
fi

printf 'Installing Liquorice startup service...\n'
# Il unit file nel repository usa /home/raspberry/liquorice-backup come esempio:
# qui viene riscritto con l'utente e il percorso reali, cosi' il servizio parte
# anche se il progetto e' stato clonato in una cartella con un altro nome.
# User= NON viene riscritto: il servizio deve girare come root (PWM/DMA della
# striscia LED su /dev/mem, profilo AP via nmcli, mount della SD). HOME invece
# punta alla home dell'utente, perche' i path con "~" di config.json (db, cache,
# log) devono restare dove sono i dati e non finire in /root.
unit_file=$(mktemp)
sed -e "s|^Environment=HOME=.*|Environment=HOME=$HOME|" \
    -e "s|^WorkingDirectory=.*|WorkingDirectory=$PROJECT_DIR|" \
    -e "s|^Environment=PYTHONPATH=.*|Environment=PYTHONPATH=$PROJECT_DIR/software|" \
    -e "s|^ExecStart=.*|ExecStart=$VENV_DIR/bin/python $PROJECT_DIR/software/main.py|" \
    "$PROJECT_DIR/systemd/liquorice.service" >"$unit_file"
sudo install -m 0644 "$unit_file" "$SYSTEMD_DIR/liquorice.service"
rm -f "$unit_file"
printf 'Service configured as root, HOME=%s, project in %s\n' "$HOME" "$PROJECT_DIR"
# Regola sudoers per il mount della card, limitata a mkdir/mount/umount, al solo
# /mnt/liquorice-sd e al mount in sola lettura. Il glob parte da mmcblk1 come
# _find_device(): mmcblk0 e' la SD di sistema.
sudoers_file=$(mktemp)
cat >"$sudoers_file" <<EOF
$USER ALL=(root) NOPASSWD: /usr/bin/mkdir -p /mnt/liquorice-sd, /usr/bin/mount -o ro /dev/mmcblk[1-9]* /mnt/liquorice-sd, /usr/bin/umount /mnt/liquorice-sd
EOF
sudo install -m 0440 "$sudoers_file" "$SUDOERS_DIR/liquorice-sdcard"
rm -f "$sudoers_file"
sudo visudo -cf "$SUDOERS_DIR/liquorice-sdcard"
sudo udevadm control --reload-rules
sudo systemctl daemon-reload
sudo systemctl enable liquorice.service

printf '\nInstallation complete. Reboot the Raspberry Pi to activate SPI and the SD-card reader.\n'
printf 'Run the application with: .venv/bin/python software/main.py\n'
printf 'Note: LED strip (rpi_ws281x on GPIO18/Pin12) needs /dev/mem access.\n'
printf '  - After first install: reboot or logout/login to apply gpio group.\n'
printf '  - Test LEDs with: sudo .venv/bin/python software/tests/hardware/test_led.py\n'
printf '    (sudo may still be required for PWM/DMA on some kernels).\n'
