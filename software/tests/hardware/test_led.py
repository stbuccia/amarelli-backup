import sys
import time

try:
    import rpi_ws281x as ws
except ImportError as e:
    sys.exit(f"rpi_ws281x non installato: {e}\nInstalla con: .venv/bin/pip install '.[raspberry-pi]'")

# Configuration
LED_COUNT = 10      # Number of LEDs
LED_PIN = 12        # BCM 12 / Pin fisico 32, hardware PWM0 (cfr. hardware/wiring.md)
LED_FREQ_HZ = 800000
LED_DMA = 10
LED_BRIGHTNESS = 255
LED_INVERT = False

# Initialize strip
strip = ws.PixelStrip(LED_COUNT, LED_PIN, LED_FREQ_HZ, LED_DMA, LED_INVERT, LED_BRIGHTNESS)
try:
    strip.begin()
except RuntimeError as e:
    msg = str(e)
    if "-5" in msg or "mmap" in msg or "Permission denied" in msg:
        sys.exit(
            "ws2811_init fallita (mmap/Permission denied).\n"
            "La libreria rpi_ws281x richiede accesso a /dev/mem.\n"
            "Riprova con: sudo .venv/bin/python software/tests/hardware/test_led.py\n"
            "Oppure aggiungi l'utente ai gruppi e riavvia: sudo usermod -a -G gpio,kmem,spi $USER && sudo reboot"
        )
    raise

print("Testing WS2812B...")

# Cycle through Red, Green, Blue, and Off
colors = [
    (255, 0, 0),  # Red
    (0, 255, 0),  # Green
    (0, 0, 255),  # Blue
    (0, 0, 0)     # Off
]

for color in colors:
    for i in range(LED_COUNT):
        strip.setPixelColor(i, ws.Color(*color))
    strip.show()
    time.sleep(1)

print("Test complete.")   
