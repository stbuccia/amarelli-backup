#!/bin/bash
# Monta/smonta la SD collegata allo slot SPI (mmc_spi su spi0.1).
# Il mount point coincide con "sd_src" di config.json.
MNT="${LIQUORICE_SD_MNT:-/mnt/liquorice-sd}"
SPI_SPEED="${LIQUORICE_SPI_SPEED:-10000000}"
# ro per default: la SD e' la sorgente del backup, non va scritta.
MOUNT_OPTS="${LIQUORICE_MOUNT_OPTS:-ro}"

# Prima partizione non montata su un mmcblk diverso da mmcblk0 (la card di
# sistema). Il tipo di filesystem NON viene forzato: lo rileva il kernel.
find_sd_partition() {
    lsblk -ln -o NAME,FSTYPE,MOUNTPOINT 2>/dev/null |
        awk '/^mmcblk[1-9][0-9]*p[0-9]+/ && $2 != "" && $3 == "" {print "/dev/"$1; exit}'
}

overlay_loaded() {
    [[ -e /sys/bus/spi/devices/spi0.1 ]]
}

do_mount() {
    if findmnt -rn "$MNT" >/dev/null 2>&1; then
        echo "SD gia' montata su $MNT"
        return 0
    fi

    local part
    part=$(find_sd_partition)

    if [[ -z "$part" ]]; then
        if overlay_loaded; then
            echo "ERRORE: overlay gia' caricato ma nessuna partizione rilevata." >&2
            echo "La card non risponde: controlla MISO (pin 21), CS su CE1 (pin 26) e il pull-up." >&2
            return 1
        fi
        echo "Nessuna partizione SD trovata. Applico dtoverlay..."
        if ! sudo dtoverlay anyspi spi0-1 dev="mmc-spi-slot" speed="$SPI_SPEED"; then
            echo "ERRORE: impossibile applicare l'overlay anyspi." >&2
            return 1
        fi
        local i
        for ((i = 0; i < 10; i++)); do
            part=$(find_sd_partition)
            [[ -n "$part" ]] && break
            sleep 1
        done
    fi

    if [[ -z "$part" ]]; then
        echo "ERRORE: nessuna partizione SD rilevata dopo l'overlay." >&2
        return 1
    fi

    echo "Partizione trovata: $part"
    sudo mkdir -p "$MNT" || return 1
    if sudo mount -o "$MOUNT_OPTS" "$part" "$MNT"; then
        echo "SD montata su $MNT ($(findmnt -rn -o FSTYPE "$MNT"), $MOUNT_OPTS)"
        return 0
    fi
    echo "ERRORE mount di $part su $MNT" >&2
    return 1
}

do_umount() {
    if findmnt -rn "$MNT" >/dev/null 2>&1; then
        echo "Smonto $MNT..."
        sudo umount "$MNT" && echo "Smontata." || {
            echo "ERRORE: $MNT occupata." >&2
            return 1
        }
    else
        echo "$MNT non era montata"
    fi
    if overlay_loaded; then
        echo "Rimuovo overlay..."
        sudo dtoverlay -r anyspi 2>/dev/null || echo "Nessun overlay da rimuovere."
    fi
    return 0
}

do_status() {
    if findmnt -rn "$MNT" >/dev/null 2>&1; then
        echo "SD MONTATA: $(findmnt -rn -o SOURCE,FSTYPE,OPTIONS "$MNT") -> $MNT"
    else
        echo "SD NON montata"
        local part
        part=$(find_sd_partition)
        if [[ -n "$part" ]]; then
            echo "Tuttavia partizione rilevata (non montata): $part"
        elif overlay_loaded; then
            echo "Overlay caricato (spi0.1) ma nessuna card rilevata."
        else
            echo "Overlay non caricato."
        fi
    fi
}

case "${1:-help}" in
    mount) do_mount ;;
    umount) do_umount ;;
    status) do_status ;;
    *) echo "Uso: $0 {mount|umount|status}" ;;
esac
