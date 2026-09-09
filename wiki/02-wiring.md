# 2. Wiring and assembly

This chapter shows where to weld component on the board and how to connect each part to the Raspberry Pi. There is a schematic image in `hardware/Schematic_Amarelli_2026-09-09.png` if you want a picture to follow.

Remember that the board follow the breadboard row-column connection logic, I suggest you to welder only on the bottom face of the board, beacause 3d printed part gives more space in this side.

In this guide I use board row and column coordinates in order to give you precise assembly. The column is already numered on the board, the row numeber instead needs to be counted, I refer them counting above the bottom `+/-` row

## Order of assembly

1. The Raspberry Pi, fixed in bottom face of the perma-proto breadboard
2. Buttons, card reader, LED strip and reed switch
3. The screen last, since it covers most of the header.

After wiring you should look something like:

...



## Raspberry Pi 

...

## 3v3 and GND

...

## Buttons

There are four buttons: **Back (Left)**, **Down**, **Up**, and **Confirm (Right)**. Wire one side of each button to its BCM pin following the table, and the other side to the `-` column of the board. Place them in the **row 4**, as shown in the picture

| Button | BCM | Physical pin | Row of the board |
|---|---|---|---|
| Left | 5 | 29 ||
| Down | 6 | 31 ||
| Up | 13 | 33 ||
| Right | 19 | 35 ||

These are the pins the software reads.

## Card reader (external, SPI)

The camera card reader shares the same SPI0 bus as the display, but uses the second chip-select (CE1). The installer turns it on with a small system setting and runs the bus at 10 MHz. 
Place also the card SPI pinout in the **row 4**



Connect the reader's SPI wires (MOSI, MISO, SCLK) to the shared bus, its chip-select to CE1 (BCM 7, physical pin 26), plus 3.3 V and GND. Place card 

After the software is installed and the Pi reboots, the card is mounted for you
at `/mnt/amarelli-sd`.

## LED strip (WS2812B, 10 LEDs)

| LED wire | BCM | Physical Pin | Row of the board
|---| --- | --- | --- |
| DIN | BCM 12 |(physical pin 32) | |
| 5 V | 5V | 2 (or 4) ||
| GND |  GND | `-` | |

## Reed switch (lid sensor)


| Reed wire | Connect to |
|---|---|
| Wire 1 | BCM 16 (physical pin 36) |
| Wire 2 | GND (for example physical pin 39) |



It is equivalent which side you choose for GND and for BCM. Keep attention reed switch is very fragile!
Glue the magnet to the lid, so shutting the lid closes the switch. When the switch is closed, the box treats the lid as shut and sleeps the screen.

## Display (Waveshare 2.13" e-Paper, V4)

The display uses the SPI0 bus. Before wiring you to insert the wire connector in the screen, then you should cut the final part of the wire in order to have a male wire in one side (instead female). 

| Display signal | BCM | Physical pin |
|---|---|---|
| VCC | 3.3 V | 1 |
| GND | GND | 39 (any ground pin works) |
| DIN / MOSI | 10 | 19 |
| CLK / SCLK | 11 | 23 |
| CS / CE0 | 8 | 24 |
| DC | 25 | 22 |
| RST | 27 | 13 |
| BUSY | 24 | 18 |

In this project the reset wire (RST) goes to **BCM 27**, not the BCM 17 that Waveshare uses by default because in my RPi that pin is broken. The installer fixes the driver for you (see chapter 4), so keep RST on BCM 27


## Check before you power on

- No wire touches both 5 V and 3.3 V.
- The display RST goes to BCM 27 (pin 13).
- The LED data wire is on BCM 12 (pin 32).
- No pin is shorted to the pin next to it.

## Test the hardware

Before assembly with the 3d printed part and placing it in the Amarelli box it's better proceeding with software installation and configuration, in order to run test for verifying that everything is working. 

Once everything is wired, you should test each part before you trust the box. The test scripts need the software, so you run them after you install it. There is a small script for the screen, the buttons, the reed switch, the LED strip, and the card reader

When everything is wired, go to [Prepare the SD card and OS](03-prepare-os.md).
