"""Manual test for the Waveshare 2.13-inch V4 e-paper display."""

import sys
import time

from PIL import Image, ImageDraw, ImageFont

try:
    from waveshare_epd import epd2in13_V4, epdconfig
except ImportError as error:
    sys.exit(
        f"waveshare_epd non installato: {error}\n"
        "Esegui ./install.sh dalla root del progetto."
    )


def main():
    print(f"Driver: {epd2in13_V4.__file__}")
    print(
        "Pin BCM: "
        f"RST={epdconfig.RST_PIN} DC={epdconfig.DC_PIN} "
        f"BUSY={epdconfig.BUSY_PIN} CS={epdconfig.CS_PIN}"
    )
    if epdconfig.RST_PIN != 27:
        sys.exit("RST deve essere BCM 27. Esegui nuovamente ./install.sh.")

    epd = epd2in13_V4.EPD()
    try:
        epd.init()
        epd.Clear(0xFF)
        epd.init()

        image = Image.new("1", (epd.height, epd.width), 255)
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, epd.height - 1, epd.width - 1), outline=0)
        draw.rectangle((8, 8, epd.height - 9, epd.width - 9), outline=0)
        font = ImageFont.load_default()
        draw.text((18, 42), "Amarelli", font=font, fill=0)
        draw.text((18, 62), "E-Ink OK", font=font, fill=0)
        draw.text((18, 82), "RST: BCM 27", font=font, fill=0)
        epd.display(epd.getbuffer(image))
        print("Test visualizzato per 5 secondi.")
        time.sleep(5)
    finally:
        epd.init()
        epd.Clear(0xFF)
        epd.sleep()


if __name__ == "__main__":
    main()
