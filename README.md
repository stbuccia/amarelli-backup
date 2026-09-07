# Amarelli Backup

Progetto DIY che consiste nel trasformare una scatola di liquerizia Amarelli in un dispositivo per backup di foto con upload automatico su un server remoto (WebDAV oppure una qualsiasi destinazione supportata da rclone: Google Drive, Dropbox, OneDrive, S3, SFTP, chiavetta USB, ...).

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

  In alternativa attivando il virtualenv:

  ```bash
  source .venv/bin/activate
  python software/main.py
  python software/main.py --mock   # mock EPD/tasti, upload reale (es. con rclone/Dropbox)
  ```

## Destinazione del backup

Il backend di upload si sceglie con `uploader` in `config.json` oppure dalla pagina web (`http://<ip>:5000/config` → sezione *Destinazione backup*). Il menu sul display non espone più la voce `Service`: la scelta del servizio è centralizzata sul web tra i remoti configurati con rclone. Il cambio ha effetto dal backup successivo.

| `uploader` | Destinazione |
|---|---|
| `webdav` | Server WebDAV (Nextcloud, ownCloud, ...) configurato via `.env` |
| `rclone` | Qualsiasi remoto rclone: Google Drive, Dropbox, OneDrive, S3, Backblaze, SFTP, cartella locale, ... |

La cartella remota di destinazione resta `cloud_dst` in entrambi i casi.

### WebDAV

Variabili nel file `.env`:

```dotenv
WEBDAV_HOSTNAME=https://cloud.example.com/remote.php/dav/files/utente
WEBDAV_FOLDER=
WEBDAV_LOGIN=utente
WEBDAV_PASSWORD=password
```

### rclone

`rclone` viene installato da `install.sh`. Configura il servizio una volta sola sulla Raspberry Pi (oppure sul PC e poi copia la config):

```bash
rclone config          # crea per esempio un remoto chiamato "gdrive"
rclone listremotes     # verifica i remoti disponibili -> es. "dropbox:"
rclone ls dropbox:     # verifica accesso al remoto
```

Poi imposta il remoto dalla pagina web `http://<ip>:5000/config` (campo *Remoto rclone*) oppure in `config.json`:

```json
"uploader": "rclone",
"rclone_remote": "dropbox:amarelli-test"
```

Valori accettati da `rclone_remote`:

+ `dropbox:amarelli-test` / `gdrive:foto/backup` - remoto + sottocartella
+ `dropbox` / `gdrive` - radice del remoto (`:` aggiunto automaticamente)
+ `/mnt/usb/backup` - cartella locale (chiavetta USB/disco), senza configurare nulla in rclone
+ vuoto - usa il primo remoto di `rclone listremotes`

In alternativa a `config.json`, il remoto può stare nel `.env` come `RCLONE_REMOTE` (usato solo se `rclone_remote` è vuoto). Chiavi opzionali di `config.json`: `rclone_binary` (percorso eseguibile), `rclone_config` (file alternativo, oppure `RCLONE_CONFIG_FILE` nel `.env`), `rclone_timeout` (secondi per comando, default 300).

Se rclone è già configurato sul PC di sviluppo, copia la config sulla Raspberry invece di rifarla:

```bash
scp ~/.config/rclone/rclone.conf raspberry@amarelli:~/.config/rclone/rclone.conf
```

I retry con backoff sono gestiti dall'applicazione (rclone è invocato con `--retries 1`): errori temporanei di rete fanno ripartire la fase di upload, errori di credenziali o exit code non recuperabili (1,3,4,7) fermano il backup con `Error` sul display.

#### Configurazione per servizio

Tutti i servizi seguenti si configurano con `rclone config` scegliendo il tipo (`Storage`) indicato. La pagina web `/config` elenca automaticamente i remoti trovati con `rclone listremotes`.

**Dropbox**
```bash
rclone config
# name> dropbox
# Storage> dropbox
# client_id / client_secret> INVIO (oppure crea app su https://www.dropbox.com/developers)
# Edit advanced config> n
# Use auto config> y  (su Pi headless: n, poi segui il link sul PC)
# Configure as Shared Drive> n
```
Configura `rclone_remote` come `dropbox:amarelli-test` (cartella creata al primo upload). Verifica: `rclone mkdir dropbox:amarelli-test && rclone ls dropbox:amarelli-test`.

**Google Drive**
```bash
rclone config
# name> gdrive
# Storage> drive
# client_id / client_secret> INVIO o crea progetto su console.cloud.google.com (consigliato per quota)
# scope> 3 (drive)
# service_account_file> INVIO
# Edit advanced config> n
# Use auto config> y  (apre browser; su Pi headless usa n e incolla il codice)
```
Usa `rclone_remote: "gdrive:foto/backup"` oppure `"gdrive:"` per la radice. Se usi account GSuite con Shared Drive, rispondi `team_drive> y`.

**OneDrive (Microsoft)**
```bash
rclone config
# name> onedrive
# Storage> onedrive
# region> 1 (Microsoft Cloud Global)
# Edit advanced config> n
# Use auto config> y
# config_type> 0 (OneDrive Personal/Business)
```
Remoto tipico: `onedrive:Amarelli/backup`.

**S3 / Backblaze B2 / Wasabi / MinIO**
```bash
rclone config
# name> s3backup
# Storage> s3
# provider> AWS / Backblaze / Wasabi / Minio / Altro
# env_auth> false
# access_key_id> ...
# secret_access_key> ...
# region> eu-central-1 (o us-east-1 per B2)
# endpoint> (solo per MinIO/Wasabi/B2)
# acl> private
```
Remoto: `s3backup:amarelli-bucket/foto`. Per bucket già esistente, rclone non lo crea automaticamente — crealo prima.

**SFTP**
```bash
rclone config
# name> sftp
# Storage> sftp
# host> 192.168.1.10
# user> pi
# port> 22
# pass> ... (o key_file)
```
Remoto: `sftp:/srv/backup/amarelli`. Il percorso assoluto dopo `:` è mantenuto (`sftp:/srv/backup`).

**WebDAV via rclone (alternativa a backend webdav nativo)**
```bash
rclone config
# name> kdrive
# Storage> webdav
# url> https://932687.connect.kdrive.infomaniak.com/webdav/
# vendor> other
# user> stbuccia@ikmail.com
# pass> ...
```
Remoto: `kdrive:amarelli-test`. Differenza col backend `webdav` nativo: rclone gestisce meglio retry/timeout, ma richiede `rclone` installato.

**Chiavetta USB / disco locale (senza rclone)**
Nessun `rclone config` necessario:
```json
"rclone_remote": "/mnt/usb/backup"
```
o `/media/pi/CHIAVE/foto`. In questo caso rclone copia localmente con `copyto` (nessuna rete).

> Suggerimento mock: per testare su laptop senza hardware (`python software/main.py --mock`) usa un remoto locale come `/tmp/fake-dropbox` o una cartella di test; il codice `software/sdcard.py:18` in mock accetta qualsiasi cartella come SD finta.

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
