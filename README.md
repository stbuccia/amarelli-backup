# Amarelli Backup

Progetto DIY che consiste nel trasformare una scatola di liquerizia Amarelli in un dispositivo per backup di foto con upload automatico su un WebDav server. 

## Struttura del repository

+ `software/`: applicazione Python.
+ `config.json`: configurazione dell'applicazione.
+ `software/tests/hardware/`: script manuali per provare i componenti Raspberry Pi.
+ `hardware/`: cablaggi e materiale relativo all'elettronica.
+ `assets/images/`: immagini e anteprime del display.
+ `docs/`: note e documentazione di progetto.

## Componenti necessari 

+ Raspberry Pi Zero W
+ Scheda microSD

## Configurazione

+ Scarica ([ Raspberry Pi OS Lite (32-bit)](https://www.raspberrypi.com/software/operating-systems/)) e installa sulla scheda microSD, configurando il Wifi e la connessione SSH
+ Python 3.10 o successivo
...

+ `cp -r "~/e-Paper/RaspberryPi_JetsonNano/python/lib/waveshare_epd" software/`
+ `python3 -m venv  .venv`
+ source .venv/bin/activate
+ `.venv/bin/pip install .`

+ `python3 software/main.py`


...
+ `nmcli connection delete "Amarelli AP"`

## Assemblaggio

+ Prima max17043, sdi spi, led, reed switch
+ raspberry, powerboost
+ eink spi
