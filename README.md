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

+ Esegui `./install.sh` dalla root del repository. Lo script abilita SPI, installa le dipendenze e copia il driver Waveshare nel virtualenv.
+ Riavvia la Raspberry Pi dopo l'installazione, per applicare la configurazione SPI e i permessi dei gruppi.
+ Avvia l'applicazione con `.venv/bin/python software/main.py`.

## Scheda SD

La microSD inserita nel lettore esterno viene rilevata automaticamente e montata in `/mnt/amarelli-sd`. Il percorso e' configurato tramite `sd_src` in `config.json`.

Quando non e' inserita una scheda e non ci sono file in cache da caricare, il display mostra `Status: Waiting for SD card`. Inserendo la scheda lo stato torna a `Ready`; avviando il backup, i file vengono letti dalla scheda, copiati in cache e caricati come di consueto.

I dati persistenti dell'applicazione si trovano in `/home/raspberry/amarelli`: `cache/` contiene i file in attesa di upload, `files.db` il database e `amarelli.log` i log.

L'overlay SPI del lettore SD usa 10 MHz. Dopo aver aggiornato `install.sh`, rieseguire `./install.sh` e riavviare la Raspberry Pi per applicare la velocita' aggiornata.


...
+ `nmcli connection delete "Amarelli AP"`

## Assemblaggio

+ Prima max17043, sdi spi, led, reed switch
+ raspberry, powerboost
+ eink spi

## Display Waveshare e-Paper

Il display Waveshare e-Paper e' collegato tramite il bus SPI0 del Raspberry Pi.

| Segnale display | GPIO BCM | Pin fisico Raspberry Pi |
|---|---:|---:|
| VCC | 3.3 V | 1 o 17 |
| GND | GND | 6, 9, 14, 20, 25, 30, 34 o 39 |
| DIN / MOSI | 10 | 19 |
| CLK / SCLK | 11 | 23 |
| CS / CE0 | 8 | 24 |
| DC | 25 | 22 |
| RST | 27 | 13 |
| BUSY | 24 | 18 |

Il segnale `RST` e' stato spostato dal GPIO BCM 17 al GPIO BCM 27, perche' GPIO 17 non e' disponibile nel progetto.

Nel driver Python Waveshare, il file `waveshare_epd/epdconfig.py` deve contenere:

```python
RST_PIN = 27
```

Verificare che il virtualenv stia usando il driver e la configurazione corretti:

```bash
.venv/bin/python -c "import waveshare_epd.epdconfig as e; print(e.__file__); print('RST:', e.RST_PIN)"
```

Per verificare che il programma stia usando il driver e la configurazione corretti:
L'output deve contenere:
```text
RST: 27
```

Per visualizzare una schermata di test sul pannello 2.13" V4:

```bash
.venv/bin/python software/tests/hardware/test_eink.py
```

SPI deve essere abilitato sul Raspberry Pi. Verificare la presenza di entrambi i chip-select con:
```bash
ls -l /dev/spidev*
```

L'output previsto include:
```text
/dev/spidev0.0
/dev/spidev0.1
```
