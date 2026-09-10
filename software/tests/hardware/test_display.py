"""Manual test del display e-paper: scrive "Hello world" sul pannello 2.13" V4.

Verifica driver e pin (RST deve essere BCM 27) e disegna passando dallo stack UI
dell'applicazione (Display, StatusBar, Legend, font), cosi' da controllare anche
font e composizione dell'immagine.

Uso: .venv/bin/python software/tests/hardware/test_display.py
"""

import sys
import time
from pathlib import Path

SOFTWARE_DIR = Path(__file__).resolve().parents[2]
if str(SOFTWARE_DIR) not in sys.path:
    sys.path.insert(0, str(SOFTWARE_DIR))

from display import Display, Legend, StatusBar, load_font  # noqa: E402

try:
    from waveshare_epd import epd2in13_V4, epdconfig
except ImportError as error:
    sys.exit(
        f"waveshare_epd non installato: {error}\n"
        "Esegui ./install.sh dalla root del progetto."
    )

TEXT = "Hello world"


class HelloView:
    """Vista minimale con il testo centrato nell'area di contenuto."""

    def render(self, draw, font, width, height, y_offset=0, bottom_margin=0):
        draw.rectangle([(0, y_offset), (width, height)], fill=255)
        left, top, right, bottom = draw.textbbox((0, 0), TEXT, font=font)
        x = (width - (right - left)) // 2
        y = y_offset + (height - y_offset - bottom_margin - (bottom - top)) // 2
        draw.text((x, y), TEXT, font=font, fill=0)


def main():
    print(f"Driver: {epd2in13_V4.__file__}")
    print(f"Config: {epdconfig.__file__}")
    print(
        "Pin BCM: "
        f"RST={epdconfig.RST_PIN} DC={epdconfig.DC_PIN} "
        f"BUSY={epdconfig.BUSY_PIN} CS={epdconfig.CS_PIN}"
    )
    if epdconfig.RST_PIN != 27:
        sys.exit("RST deve essere BCM 27. Esegui nuovamente ./install.sh.")

    display = Display(epd2in13_V4.EPD(), load_font())
    try:
        display.init()
        display.render_full(HelloView(), StatusBar("Liquorice"), Legend("test display"))
        print(f'"{TEXT}" visualizzato per 5 secondi.')
        time.sleep(5)
    finally:
        display.init_full()
        display.sleep()


if __name__ == "__main__":
    main()
