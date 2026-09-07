#!/bin/bash
MNT="/mnt/sdcard"
case "${1:-help}" in
    mount)
        if mount | grep -q "$MNT"; then
            echo "SD già montata su $MNT"
            exit 0
        fi
        # Cerca partizioni mmcblk non montate
        part=$(lsblk -ln -o NAME,FSTYPE,MOUNTPOINT 2>/dev/null | \
               awk '/^mmcblk[0-9]+p[0-9]+/ && $2 != "" && $3 == "" {print "/dev/"$1; exit}')
        if [[ -n "$part" ]]; then
            echo "Trovata partizione già disponibile: $part"
            sudo mount -t ext4 "$part" "$MNT" && echo "SD montata su $MNT" || echo "ERRORE mount"
            exit $?
        fi
        # Nessuna partizione trovata, applica overlay
        echo "Nessuna partizione SD trovata. Applico dtoverlay..."
        sudo dtoverlay anyspi spi0-1 dev="mmc-spi-slot" speed=20000000
        for ((i=0; i<10; i++)); do
            part=$(lsblk -ln -o NAME,FSTYPE,MOUNTPOINT 2>/dev/null | \
                   awk '/^mmcblk[0-9]+p[0-9]+/ && $2 != "" && $3 == "" {print "/dev/"$1; exit}')
            [[ -n "$part" ]] && break
            sleep 1
        done
        if [[ -z "$part" ]]; then
            echo "ERRORE: nessuna partizione SD rilevata dopo overlay."
            exit 1
        fi
        sudo mount -t ext4 "$part" "$MNT" && echo "SD montata su $MNT" || echo "ERRORE mount"
        ;;
    umount)
        echo "Smonto $MNT..."
        sudo umount "$MNT" 2>/dev/null && echo "Smontata." || echo "$MNT non era montata"
        echo "Rimuovo overlay..."
        sudo dtoverlay -r anyspi 2>/dev/null || echo "Nessun overlay da rimuovere."
        ;;
    status)
        if mount | grep -q "$MNT"; then
            dev=$(mount | grep "$MNT" | awk '{print $1}')
            echo "SD MONTATA: $dev -> $MNT"
        else
            echo "SD NON montata"
            part=$(lsblk -ln -o NAME,FSTYPE,MOUNTPOINT 2>/dev/null | \
                   awk '/^mmcblk[0-9]+p[0-9]+/ && $2 != "" && $3 == "" {print "/dev/"$1; exit}')
            if [[ -n "$part" ]]; then
                echo "Tuttavia partizione rilevata (non montata): $part"
            fi
        fi
        ;;
    *)
        echo "Uso: $0 {mount|umount|status}"
        ;;
esac
