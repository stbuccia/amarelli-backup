# Amarelli Backup

Progetto DIY che consiste nel trasformare una scatola di liquerizia Amarelli in un dispositivo per backup di foto con upload automatico su un WebDav server. 

## Componenti necessari 

+ Raspberry Pi Zero W
+ Scheda microSD

## Configurazione

+ Scarica ([ Raspberry Pi OS Lite (32-bit)](https://www.raspberrypi.com/software/operating-systems/)) e installa sulla scheda microSD, configurando il Wifi e la connessione SSH
...

+ `cp -r "~/e-Paper/RaspberryPi_JetsonNano/python/lib/waveshare_epd" .`
+ `python3 -m venv  .venv`
+ source .venv/bin/activate
+ `.venv/bin/pip install .`

+ `python3 main.py`
