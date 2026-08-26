import gpiozero, time
b = gpiozero.Button(16, pull_up=True)
while True:
    print("CHIUSO (lid chiuso)" if b.is_pressed else "APERTO (lid aperto)")
    time.sleep(0.1)
