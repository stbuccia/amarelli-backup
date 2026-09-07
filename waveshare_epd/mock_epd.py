import time
from PIL import Image


EPD_WIDTH = 122
EPD_HEIGHT = 250


class MockEPD:
    _counter = 0

    def __init__(self):
        self.width = EPD_WIDTH
        self.height = EPD_HEIGHT

    def init(self):
        print("[MOCK EPD] init")
        return 0

    def init_fast(self):
        print("[MOCK EPD] init_fast")
        return 0

    def reset(self):
        pass

    def Clear(self, color=0xFF):
        print("[MOCK EPD] cleared")

    def getbuffer(self, image):
        img = image
        imwidth, imheight = img.size
        if imwidth == self.width and imheight == self.height:
            img = img.convert("1")
        elif imwidth == self.height and imheight == self.width:
            img = img.rotate(90, expand=True).convert("1")
        else:
            return [0x00] * (int(self.width / 8) * self.height)
        return bytearray(img.tobytes("raw"))

    def _render_buffer(self, buf):
        MockEPD._counter += 1
        ts = time.strftime("%H:%M:%S")
        print(f"[MOCK EPD] frame #{MockEPD._counter} @ {ts}")
        img = Image.frombytes("1", (self.width, self.height), bytes(buf))
        img = img.rotate(270, expand=True)
        img.save("display_output.png")
        try:
            img.show()
        except Exception:
            pass

    def display(self, image):
        self._render_buffer(image)

    def display_fast(self, image):
        self._render_buffer(image)

    def displayPartial(self, image):
        self._render_buffer(image)

    def displayPartBaseImage(self, image):
        self._render_buffer(image)

    def sleep(self):
        print("[MOCK EPD] sleep")

    def TurnOnDisplay(self):
        pass

    def TurnOnDisplay_Fast(self):
        pass

    def TurnOnDisplayPart(self):
        pass

    def ReadBusy(self):
        pass

    def send_command(self, cmd):
        pass

    def send_data(self, data):
        pass

    def send_data2(self, data):
        pass
