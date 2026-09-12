from gpiozero import Button
from time import sleep
buttons = []
for pin, name in [(5, "UP"), (6, "DOWN"), (13, "CONFIRM"), (19, "BACK")]:
    b = Button(pin, pull_up=True, bounce_time=0.05)
    b.when_pressed = lambda n=name: print(f"{n} premuto!")
    buttons.append(b)
    print(f"{name} (BCM {pin}) pronto")
input("Premi INVIO per uscire\n> ")
