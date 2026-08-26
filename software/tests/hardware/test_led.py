import time
import rpi_ws281x as ws

# Configuration
LED_COUNT = 10      # Number of LEDs
LED_PIN = 18        # GPIO pin (18 is hardware PWM)
LED_FREQ_HZ = 800000
LED_DMA = 10
LED_BRIGHTNESS = 255
LED_INVERT = False

# Initialize strip
strip = ws.PixelStrip(LED_COUNT, LED_PIN, LED_FREQ_HZ, LED_DMA, LED_INVERT, LED_BRIGHTNESS)
strip.begin()

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
