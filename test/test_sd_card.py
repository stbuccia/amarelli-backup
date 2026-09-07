"""Diagnostica collegamento SD Card reader breakout via SPI.

Protocollo SD SPI: dopo aver inviato un comando (6 byte), la SD risponde
con R1 dopo alcuni cicli di clock — MAI durante il comando stesso.

Collegamenti attesi (SPI0, CE0):
  CS   → GPIO 8  (pin 24)
  MOSI → GPIO 10 (pin 19)
  MISO → GPIO 9  (pin 21)
  SCK  → GPIO 11 (pin 23)
  VCC  → 3.3V    (pin 1 o 17)
  GND  → GND     (pin 6, 14, ecc.)

Prima di eseguire:
  sudo modprobe spi_bcm2835
  ls /dev/spidev0.*

Dipendenze:
  sudo apt install python3-spidev python3-rpi.gpio

E poi:
  python3 test/test_sd_card.py
"""

import time
import sys
import spidev


# ── helpers SD SPI ──────────────────────────────────────────────────────────

SD_CMD0   = (0,  0x00000000, 0x95)   # GO_IDLE_STATE
SD_CMD8   = (8,  0x000001AA, 0x87)   # SEND_IF_COND (v2)
SD_CMD58  = (58, 0x00000000, 0xFD)   # READ_OCR
SD_CMD55  = (55, 0x00000000, 0x01)   # APP_CMD
SD_CMD41  = (41, 0x40000000, 0x77)   # SD_SEND_OP_COND + HCS
SD_CMD41v1 = (41, 0x00000000, 0x77)  # SD_SEND_OP_COND senza HCS
SD_CMD9   = (9,  0x00000000, 0xAF)   # SEND_CSD


def init_spi(bus=0, device=0, speed=400000):
    spi = spidev.SpiDev()
    spi.open(bus, device)
    spi.max_speed_hz = speed
    spi.mode = 0
    spi.lsbfirst = False
    return spi


def xfer(spi, data):
    return spi.xfer2(data)


def send_cmd_raw(spi, cmd, arg, crc):
    """Invia i 6 byte del comando, poi aspetta la risposta R1.

    La SD non risponde durante il comando ma dopo (da 1 a 8 cicli di clock).
    Legge byte finché MISO != 0xFF o scadono i tentativi.
    """
    frame = [0x40 | cmd] \
        + [(arg >> 24) & 0xFF, (arg >> 16) & 0xFF,
           (arg >> 8) & 0xFF, arg & 0xFF] \
        + [crc]
    xfer(spi, frame)

    for _ in range(64):
        b = xfer(spi, [0xFF])[0]
        if b != 0xFF:
            return b
    return 0xFF


def read_bytes(spi, n):
    return xfer(spi, [0xFF] * n)


# ── step diagnostici ────────────────────────────────────────────────────────

def test_spi_open():
    print("=== 1. Apertura device SPI ===")
    found = 0
    for bus, dev in [(0, 0), (0, 1), (1, 0)]:
        try:
            s = spidev.SpiDev()
            s.open(bus, dev)
            print(f"  /dev/spidev{bus}.{dev} — OK")
            s.close()
            found += 1
        except FileNotFoundError:
            print(f"  /dev/spidev{bus}.{dev} — non esiste")
        except PermissionError:
            print(f"  /dev/spidev{bus}.{dev} — permesso negato")
        except Exception as e:
            print(f"  /dev/spidev{bus}.{dev} — {e}")

    if found == 0:
        print("  Nessun device SPI trovato!")
        return None
    return init_spi(0, 0)


def test_loopback(spi):
    print("\n=== 2. Test MISO (invia 0xA5) ===")
    r = xfer(spi, [0xA5])[0]
    print(f"  -> 0x{r:02X}", end="")
    if r == 0xA5:
        print("  MOSI e MISO in corto o collegati insieme!")
    elif r == 0xFF:
        print("  MISO = 0xFF (pull-up, nessun device pilota la linea)")
    else:
        print()


def test_sd_on_ce0():
    """Testa CMD0 direttamente su CE0 (spidev0.0).

    Se la SD è collegata a CE0 con CS su GPIO 8, deve rispondere.
    Se il display Waveshare è su CE0, potrebbe dare conflitto.
    """
    print("\n=== 3. CMD0 su CE0 (GPIO 8) ===")
    spi = init_spi(0, 0)

    # clock iniziali con CS attivo
    xfer(spi, [0xFF] * 80)

    r1 = send_cmd_raw(spi, *SD_CMD0)
    print(f"  R1 = 0x{r1:02X}", end="")
    if r1 == 0x01:
        print("  IDLE  SD PRESENTE su CE0!")
    elif r1 == 0xFF:
        print("  nessuna risposta")
    elif r1 & 0x02:
        print(f"  errore CRC (bit 1 set)")
    else:
        print()

    if r1 == 0x01:
        print("\n  --> CMD8 (SEND_IF_COND):", end=" ")
        r1 = send_cmd_raw(spi, *SD_CMD8)
        print(f"R1 = 0x{r1:02X}", end="")
        if r1 == 0x01:
            r7 = read_bytes(spi, 4)
            print(f" + {' '.join(f'0x{b:02X}' for b in r7)}", end="")
            if r7[2] == 0x01 and r7[3] == 0xAA:
                print("  SD v2")
            else:
                print()
        elif r1 == 0x05:
            print("  SD v1 (CMD8 illegale)")
        else:
            print()

        print("  --> ACMD41 (inizializzazione):", end=" ")
        for _ in range(200):
            send_cmd_raw(spi, *SD_CMD55)
            r1 = send_cmd_raw(spi, *SD_CMD41)
            if r1 == 0x00:
                break
            time.sleep(0.01)
        if r1 == 0x00:
            print("OK  card ready!")
        else:
            print(f"R1 = 0x{r1:02X}  card non entra in ready")
    elif r1 == 0xFF:
        print("\n  --> La SD NON risponde su CE0.")
        print("      Possibile conflitto col display Waveshare.")
        print("      Disconnetti il display e riprova, oppure:")
        print("      collega CS del reader a CE1 (GPIO 7).")

    spi.close()
    return r1


def test_sd_on_ce1():
    """Testa CMD0 su CE1 (spidev0.1, GPIO 7)."""
    print("\n=== 4. CMD0 su CE1 (GPIO 7) ===")
    try:
        spi = init_spi(0, 1)
    except Exception:
        print("  /dev/spidev0.1 non disponibile")
        return 0xFF

    xfer(spi, [0xFF] * 80)
    r1 = send_cmd_raw(spi, *SD_CMD0)
    print(f"  R1 = 0x{r1:02X}", end="")
    if r1 == 0x01:
        print("  IDLE  SD PRESENTE su CE1!")
    else:
        print()

    spi.close()
    return r1


def test_sd_software_cs():
    """CS software su GPIO libero (NON CE0/CE1).

    Nota: spidev aziona SEMPRE il CE hardware durante xfer.
    Per CS software serve o un overlay custom o una libreria bit-bang.
    Usiamo un GPIO + spidev ma con CE0 non connesso a nulla.
    """
    print("\n=== 5. CS software su GPIO 18 (disconnetti CS del reader da CE0/CE1) ===")
    print("  ATTENZIONE: per questo test devi spostare il filo CS")
    print("  del reader da CE0/CE1 a GPIO 18 (pin 12).")
    print("  Poi premi INVIO per continuare o Ctrl+C per saltare.")
    try:
        input("  > ")
    except KeyboardInterrupt:
        print("  Saltato.")
        return 0xFF

    try:
        import RPi.GPIO as GPIO
    except ImportError:
        print("  RPi.GPIO non disponibile. sudo apt install python3-rpi.gpio")
        return 0xFF

    CS_PIN = 18
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(CS_PIN, GPIO.OUT)
    GPIO.output(CS_PIN, GPIO.HIGH)

    spi = init_spi(0, 0)

    # clock con CS alto
    GPIO.output(CS_PIN, GPIO.HIGH)
    xfer(spi, [0xFF] * 80)

    # CMD0: CS manually low, xfer, poi CS high
    GPIO.output(CS_PIN, GPIO.LOW)
    time.sleep(0.001)
    r1 = send_cmd_raw(spi, *SD_CMD0)
    GPIO.output(CS_PIN, GPIO.HIGH)

    print(f"  R1 = 0x{r1:02X}", end="")
    if r1 == 0x01:
        print("  IDLE  SD PRESENTE!")
    else:
        print()

    GPIO.cleanup()
    return r1


def test_pin_levels():
    print("\n=== 6. Livelli GPIO (dopo un ciclo di clock) ===")
    try:
        import RPi.GPIO as GPIO
    except ImportError:
        print("  RPi.GPIO non disponibile, salto")
        return

    pins = {"MOSI": 10, "MISO": 9, "SCLK": 11, "CE0": 8, "CE1": 7}
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    spi = init_spi(0, 0)
    xfer(spi, [0x00])

    for name, pin in pins.items():
        GPIO.setup(pin, GPIO.IN)
        val = GPIO.input(pin)
        print(f"  {name} (GPIO {pin:2d}): {'HIGH' if val else 'LOW'}")

    GPIO.cleanup()
    spi.close()


def main():
    print("=" * 50)
    print("  DIAGNOSTICA SD CARD READER BREAKOUT (SPI)")
    print("=" * 50)
    print("  La risposta R1 della SD arriva DOPO il comando,")
    print("  non durante. Lo script ora aspetta R1 correttamente.\n")

    spi = test_spi_open()
    if spi is None:
        sys.exit(1)
    spi.close()

    spi = init_spi(0, 0)
    test_loopback(spi)
    spi.close()

    r0_ce0 = test_sd_on_ce0()
    r0_ce1 = test_sd_on_ce1()

    print("\n" + "=" * 50)
    print("  DIAGNOSI")
    print("=" * 50)

    if r0_ce0 == 0x01 or r0_ce1 == 0x01:
        ok = 0
        if r0_ce0 == 0x01:
            print("  SD risponde su CE0  ok")
            ok += 1
        if r0_ce1 == 0x01:
            print("  SD risponde su CE1  ok")
            ok += 1
        print(f"\n  RISULTATO: SD card rilevata su {ok} canale/i!")
        print("  Per usarla nel progetto, basta configurare")
        print("  il CS corretto nel codice.")
    else:
        print("""
  NESSUNA RISPOSTA DA CE0 O CE1.

  Le cause piu probabili, in ordine:

  1) ALIMENTAZIONE (la piu frequente)
     I breakout generici hanno un regolatore 3.3V ma richiedono
     5V in ingresso! Prova a spostare VCC dal pin 3.3V al pin 5V.
     Misura con tester la tensione tra VCC e GND sul breakout.

  2) CABLAGGIO BREADBOARD
     I contatti sono inaffidabili. Prova fili dupont diretto.

  3) MOSI / MISO INVERTITI
     Su alcuni breakout la serigrafia e invertita. Prova a scambiarli.

  4) SD NON INSERITA o inserita al contrario.

  5) CONFLITTO CON DISPLAY WAVESHARE
     Se il display e connesso, usa /dev/spidev0.1 (CE1 = GPIO 7)
     e collega CS del reader a GPIO 7 invece di GPIO 8.

  6) RESISTENZA DI PULL-UP SU CS
     Alcuni breakout hanno bisogno di un pull-up a 3.3V su CS
     (resistenza da 10 kΩ tra CS e 3.3V).
""")


if __name__ == "__main__":
    main()
