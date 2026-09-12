import logging
import os
import shutil
import socket
import ssl
import struct
import subprocess
import tempfile
import threading

import nmcli
from nmcli._exception import NotExistException

nmcli.disable_use_sudo()


log = logging.getLogger(__name__)

# I comandi di rete stanno in sbin, che non e' nel PATH di un utente normale
# (e nemmeno in quello minimo di alcune shell non interattive).
_SBIN_DIRS = ("/usr/sbin", "/sbin", "/usr/local/sbin")


def _find_tool(name: str) -> str | None:
    """Percorso assoluto di un comando di sistema, o None se non installato."""
    found = shutil.which(name)
    if found:
        return found
    for directory in _SBIN_DIRS:
        candidate = os.path.join(directory, name)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


class WiFiManager:
    AP_CONNECTION_NAME = "Liquorice AP"
    AP_IP = "192.168.4.1"
    # Porta 80 -> Flask, porta 53 -> il mini DNS interno: cosi' il telefono
    # apre la pagina anche digitando l'IP senza porta.
    CAPTIVE_REDIRECTS = (("tcp", 80, 5000), ("udp", 53, 1053))
    NFT_TABLE = "liquorice_captive"

    def __init__(self, cfg):
        self.cfg = cfg
        self.ifname = self._resolve_interface(cfg.wifi_interface)
        # SSID della rete client attiva prima di accendere l'AP: serve a
        # tornarci quando l'AP viene fermato.
        self._previous_ssid = None
        # False se l'AP e' attivo ma il redirect/DNS del captive portal non
        # ha potuto essere installato (pagina raggiungibile solo su :5000).
        self.captive_portal_ready = False

    @staticmethod
    def list_wifi_interfaces() -> list[str]:
        """Nomi delle interfacce Wi-Fi realmente presenti secondo NetworkManager."""
        try:
            r = subprocess.run(
                ["nmcli", "-t", "-f", "DEVICE,TYPE", "device", "status"],
                capture_output=True, text=True, timeout=10,
            )
        except Exception as e:
            log.debug("Cannot list wifi interfaces: %s", e)
            return []
        found = []
        for line in r.stdout.splitlines():
            parts = line.split(":")
            # Solo type "wifi": "wifi-p2p" (p2p-dev-wlan0) non puo' fare AP.
            if len(parts) >= 2 and parts[1] == "wifi" and parts[0]:
                found.append(parts[0])
        return found

    def _resolve_interface(self, configured: str) -> str:
        """Interfaccia da usare davvero, correggendo un WIFI_INTERFACE sbagliato.

        WIFI_INTERFACE nel .env viene spesso copiato da un PC di sviluppo
        (es. 'wlp0s20f3') mentre sul Raspberry l'interfaccia e' 'wlan0'. Con
        un nome inesistente il profilo AP viene creato ma NetworkManager
        rifiuta di attivarlo ("mismatching interface name") e l'unico
        sintomo visibile e' un generico "Connection activation failed".
        Se il nome configurato non esiste si usa la prima interfaccia Wi-Fi
        disponibile invece di fallire.
        """
        available = self.list_wifi_interfaces()
        if not available or configured in available:
            return configured
        log.warning(
            "Wi-Fi interface '%s' not found (available: %s): using '%s' instead. "
            "Update WIFI_INTERFACE in .env to silence this warning.",
            configured, ", ".join(available), available[0],
        )
        return available[0]

    def down_device(self):
        try:
            nmcli.device.down(self.ifname)
        except NotExistException:
            log.debug("Device %s not active, skipping down", self.ifname)

    def delete_connection(self):
        try:
            nmcli.connection.delete(self.AP_CONNECTION_NAME)
        except NotExistException:
            log.debug("Connection %s not present, skipping delete", self.AP_CONNECTION_NAME)

    def disable_ap_autostart(self):
        """Rimuove un eventuale profilo AP residuo, da chiamare all'avvio del
        programma.

        Se il box viene riavviato (o il servizio riparte) mentre il profilo
        'Liquorice AP' esiste ancora su disco, NetworkManager potrebbe
        provare ad attivarlo lui stesso al boot, lasciando il box collegato
        al proprio hotspot invece che alla rete Wi-Fi normale. Il profilo
        viene ricreato da zero ogni volta che l'AP viene avviato dal menu,
        quindi eliminarlo qui non fa perdere nulla di persistente.
        """
        self.delete_connection()

    def _ap_options(self, ssid, password):
        return {
            "wifi.ssid": ssid,
            "wifi.mode": "ap",
            "wifi.band": "bg",
            "wifi-sec.key-mgmt": "wpa-psk",
            "wifi-sec.psk": password,
            "ipv4.addresses": f"{self.AP_IP}/24",
            "ipv4.gateway": self.AP_IP,
            "ipv4.method": "shared",
            # L'AP non deve mai essere scelto da solo: se il box si riavvia
            # (anche con l'AP attivo o il profilo rimasto per un arresto
            # anomalo), NetworkManager deve tornare alla rete Wi-Fi normale
            # invece di riattivare l'hotspot da solo.
            "connection.autoconnect": "no",
            "connection.autoconnect-priority": "-999",
        }

    def _ensure_ip_forward(self):
        sysctl = _find_tool("sysctl")
        if not sysctl:
            log.warning("sysctl not found: skipping net.ipv4.ip_forward")
            return
        subprocess.run(
            [sysctl, "-w", "net.ipv4.ip_forward=1"],
            capture_output=True, check=False,
        )

    def _firewall_backend(self) -> tuple[str, str | None]:
        """Comando disponibile per il NAT: iptables, altrimenti nftables.

        Raspberry Pi OS recente non installa piu' 'iptables' (solo 'nft'):
        chiamarlo comunque solleva FileNotFoundError, che check=False non
        intercetta perche' riguarda l'avvio del processo, non il suo esito.
        """
        path = _find_tool("iptables")
        if path:
            return "iptables", path
        path = _find_tool("nft")
        if path:
            return "nft", path
        return "none", None

    def _add_iptables_rules(self) -> bool:
        """Installa i redirect del captive portal. False se non e' possibile."""
        backend, tool = self._firewall_backend()
        if backend == "iptables":
            for proto, dport, toport in self.CAPTIVE_REDIRECTS:
                subprocess.run(
                    [tool, "-t", "nat", "-C", "PREROUTING", "-p", proto,
                     "--dport", str(dport), "-j", "REDIRECT", "--to-port", str(toport)],
                    capture_output=True, check=False,
                )
                subprocess.run(
                    [tool, "-t", "nat", "-A", "PREROUTING", "-p", proto,
                     "--dport", str(dport), "-j", "REDIRECT", "--to-port", str(toport)],
                    capture_output=True, check=False,
                )
            return True
        if backend == "nft":
            # Tabella dedicata: si cancella in un colpo solo allo stop, senza
            # toccare le regole che NetworkManager crea per 'ipv4.method=shared'.
            self._del_iptables_rules()
            commands = [
                [tool, "add", "table", "ip", self.NFT_TABLE],
                [tool, "add", "chain", "ip", self.NFT_TABLE, "prerouting",
                 "{ type nat hook prerouting priority dstnat ; policy accept ; }"],
            ]
            for proto, dport, toport in self.CAPTIVE_REDIRECTS:
                commands.append([
                    tool, "add", "rule", "ip", self.NFT_TABLE, "prerouting",
                    proto, "dport", str(dport), "redirect", "to", f":{toport}",
                ])
            for cmd in commands:
                r = subprocess.run(cmd, capture_output=True, text=True, check=False)
                if r.returncode != 0:
                    log.warning("nft command failed (%s): %s",
                                " ".join(cmd[1:]), (r.stderr or "").strip())
                    return False
            return True
        log.warning(
            "Neither iptables nor nft available: captive portal redirect disabled, "
            "the page stays reachable at http://%s:5000", self.AP_IP,
        )
        return False

    def _del_iptables_rules(self) -> bool:
        backend, tool = self._firewall_backend()
        if backend == "iptables":
            for proto, dport, toport in self.CAPTIVE_REDIRECTS:
                subprocess.run(
                    [tool, "-t", "nat", "-D", "PREROUTING", "-p", proto,
                     "--dport", str(dport), "-j", "REDIRECT", "--to-port", str(toport)],
                    capture_output=True, check=False,
                )
            return True
        if backend == "nft":
            # La tabella puo' non esistere (primo avvio): l'errore e' atteso.
            subprocess.run(
                [tool, "delete", "table", "ip", self.NFT_TABLE],
                capture_output=True, check=False,
            )
            return True
        return False

    def _ensure_cert(self) -> tuple[str, str]:
        openssl = _find_tool("openssl")
        if not openssl:
            raise FileNotFoundError("openssl not installed")
        cert_dir = tempfile.mkdtemp(prefix="liquorice_tls_")
        cert_path = os.path.join(cert_dir, "cert.pem")
        key_path = os.path.join(cert_dir, "key.pem")
        subprocess.run(
            [openssl, "req", "-x509", "-newkey", "rsa:2048",
             "-keyout", key_path, "-out", cert_path,
             "-days", "3650", "-nodes",
             "-subj", f"/CN={self.AP_IP}/O=Liquorice"],
            capture_output=True, check=True,
        )
        log.info("Self-signed TLS cert generated at %s", cert_path)
        self._cert_dir = cert_dir
        return cert_path, key_path

    def _start_captive_tls(self):
        cert_path, key_path = self._ensure_cert()
        captive_paths = (
            b"/generate_204", b"/nm/generate_204",
            b"/hotspot-detect.html", b"/library/test/success.html",
            b"/success.txt",
        )
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert_path, key_path)
        bindsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        bindsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        bindsock.bind(("0.0.0.0", 443))
        bindsock.listen(5)
        bindsock.settimeout(1.0)
        stop_event = threading.Event()

        def client_thread(conn):
            try:
                data = conn.recv(4096)
                if data:
                    request_line = data.split(b"\r\n")[0]
                    path = request_line.split(b" ")[1] if b" " in request_line else b"/"
                    if any(path.startswith(p) for p in captive_paths):
                        response = (
                            b"HTTP/1.1 204 No Content\r\n"
                            b"Content-Length: 0\r\n"
                            b"Connection: close\r\n\r\n"
                        )
                    else:
                        response = (
                            b"HTTP/1.1 302 Found\r\n"
                            b"Location: http://" + self.AP_IP.encode() + b":5000/\r\n"
                            b"Content-Length: 0\r\n"
                            b"Connection: close\r\n\r\n"
                        )
                    conn.sendall(response)
            except Exception:
                pass
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

        def run():
            while not stop_event.is_set():
                try:
                    raw, addr = bindsock.accept()
                    ssock = context.wrap_socket(raw, server_side=True)
                    threading.Thread(target=client_thread, args=(ssock,), daemon=True).start()
                except socket.timeout:
                    continue
                except ssl.SSLError:
                    try:
                        raw.close()
                    except Exception:
                        pass
                except Exception:
                    break

        t = threading.Thread(target=run, daemon=True)
        t.start()
        self._tls_server_sock = bindsock
        self._tls_thread = t
        self._tls_stop_event = stop_event
        log.info("Captive TLS server ready on :443")

    def _stop_captive_tls(self):
        if hasattr(self, "_tls_stop_event"):
            self._tls_stop_event.set()
        if hasattr(self, "_tls_server_sock"):
            try:
                self._tls_server_sock.close()
            except Exception:
                pass
        if hasattr(self, "_cert_dir"):
            shutil.rmtree(self._cert_dir, ignore_errors=True)
        log.info("Captive TLS server stopped")

    def _start_dns_server(self):
        captive_domains = (
            b"connectivitycheck.gstatic.com",
            b"www.google.com",
            b"clients3.google.com",
            b"captive.apple.com",
            b"www.apple.com",
            b"gsp1.apple.com",
            b"msftconnecttest.com",
            b"ipv6.msftconnecttest.com",
        )

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", 1053))
        sock.settimeout(1.0)
        stop_event = threading.Event()
        log.info("DNS server listening on :1053")

        def run():
            while not stop_event.is_set():
                try:
                    data, addr = sock.recvfrom(1024)
                    if len(data) < 12:
                        continue
                    tid = data[:2]
                    qdcount = struct.unpack(">H", data[4:6])[0]
                    if qdcount == 0:
                        continue
                    pos = 12
                    for _ in range(qdcount):
                        original_pos = pos
                        qname_parts = []
                        while pos < len(data):
                            length = data[pos]
                            if length == 0:
                                pos += 1
                                break
                            pos += 1
                            if pos + length > len(data):
                                break
                            qname_parts.append(data[pos:pos + length])
                            pos += length
                            if length >= 192:
                                break
                        qname = b".".join(qname_parts).lower()
                        if pos + 4 > len(data):
                            break
                        qtype = struct.unpack(">H", data[pos:pos + 2])[0]
                        pos += 4
                        if not any(qname.endswith(d) for d in captive_domains):
                            continue
                        response = bytearray()
                        response += tid
                        response += struct.pack(">H", 0x8580)
                        response += struct.pack(">H", 1)
                        response += struct.pack(">H", 1)
                        response += struct.pack(">H", 0)
                        response += struct.pack(">H", 0)
                        response += data[original_pos:pos]
                        response += struct.pack(">H", 0xC00C)
                        response += struct.pack(">H", qtype)
                        response += struct.pack(">H", 1)
                        response += struct.pack(">I", 60)
                        response += struct.pack(">H", 4)
                        response += socket.inet_aton(self.AP_IP)
                        sock.sendto(response, addr)
                        log.debug("DNS spoof: %s -> %s", qname, self.AP_IP)
                except socket.timeout:
                    continue
                except OSError:
                    # Socket chiuso da _stop_dns_server: fine del thread.
                    break
                except Exception:
                    pass

        t = threading.Thread(target=run, daemon=True)
        t.start()
        self._dns_sock = sock
        self._dns_stop_event = stop_event
        self._dns_thread = t
        return t

    def _stop_dns_server(self):
        """Chiude davvero il socket UDP :1053.

        Senza questo il thread restava vivo con la porta occupata e il
        successivo avvio dell'AP falliva su bind() con "Address already in
        use", rendendo l'hotspot riavviabile solo riavviando il servizio.
        """
        stop_event = getattr(self, "_dns_stop_event", None)
        if stop_event is not None:
            stop_event.set()
        sock = getattr(self, "_dns_sock", None)
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass
            self._dns_sock = None
        log.info("DNS server stopped")

    def start_ap(self, ssid, password):
        if not password:
            raise ValueError("Password is required")
        # WPA2-PSK rifiuta chiavi piu' corte: meglio dirlo subito che
        # lasciare fallire l'attivazione con un errore generico.
        if len(password) < 8:
            raise ValueError("AP password must be at least 8 characters")

        # L'interfaccia puo' essere comparsa/cambiata dall'avvio (dongle USB,
        # driver caricato tardi): si ricontrolla prima di creare il profilo.
        self.ifname = self._resolve_interface(self.cfg.wifi_interface)

        # La rete client attiva va ricordata prima di spegnere l'interfaccia:
        # allo stop dell'AP si torna esattamente su quella.
        current = self.get_current_ssid()
        if current and current != self.AP_CONNECTION_NAME:
            self._previous_ssid = current
            log.info("Remembering current network '%s' for after the AP", current)

        self.down_device()
        self.delete_connection()
        self._ensure_ip_forward()

        nmcli.connection.add(
            conn_type="wifi",
            ifname=self.ifname,
            name=self.AP_CONNECTION_NAME,
            options=self._ap_options(ssid, password),
        )
        try:
            nmcli.connection.up(self.AP_CONNECTION_NAME)
        except Exception:
            # Il profilo appena creato non deve restare su disco: sarebbe un
            # AP fantasma, mai attivo ma pronto a confondere il prossimo
            # avvio (e le voci "AP attivo" del menu).
            self.delete_connection()
            raise
        self.captive_portal_ready = self._start_captive_portal()
        log.info("Access point '%s' active on %s (captive portal: %s)",
                 ssid, self.ifname, "ok" if self.captive_portal_ready else "degraded")

    def _start_captive_portal(self) -> bool:
        """Redirect NAT, DNS spoof e TLS: comodita', non requisiti dell'AP.

        Servono solo perche' il telefono apra la pagina da solo; la pagina
        resta comunque raggiungibile su http://192.168.4.1:5000. Un errore
        qui non deve far fallire start_ap: prima era cosi' e su Raspberry Pi
        OS senza 'iptables' il risultato era un hotspot acceso ma con "AP
        error!" sul display e il server web mai avviato.
        """
        ok = True
        for step in (self._add_iptables_rules, self._start_captive_tls,
                     self._start_dns_server):
            try:
                if step() is False:
                    ok = False
            except Exception as e:
                ok = False
                log.warning("Captive portal step %s failed: %s",
                            getattr(step, "__name__", step), e)
        return ok

    def _stop_captive_portal(self) -> None:
        for step in (self._del_iptables_rules, self._stop_captive_tls,
                     self._stop_dns_server):
            try:
                step()
            except Exception as e:
                log.warning("Captive portal cleanup %s failed: %s",
                            getattr(step, "__name__", step), e)
        self.captive_portal_ready = False

    def stop_ap(self, reconnect: bool = True):
        # Ogni passo e' isolato: un errore nella pulizia non deve impedire di
        # spegnere l'AP ne' di tornare sulla rete Wi-Fi di prima.
        self._stop_captive_portal()
        try:
            nmcli.connection.down(self.AP_CONNECTION_NAME)
            log.info("Access point stopped")
        except NotExistException:
            log.warning("Access point '%s' not active", self.AP_CONNECTION_NAME)
        except Exception as e:
            log.error("Error deactivating access point: %s", e)
        # Il profilo va rimosso, non solo disattivato: non deve restare su
        # disco tra una sessione e l'altra, ne' essere scelto da
        # NetworkManager a un riavvio successivo.
        self.delete_connection()
        if reconnect:
            self._reconnect_known_network()

    def _reconnect_known_network(self) -> bool:
        """Riprova una rete Wi-Fi gia' nota dopo aver fermato l'AP.

        NetworkManager non si riconnette da solo dopo un 'connection down'
        esplicito (a differenza di una disconnessione accidentale): senza
        questo passo il device resta senza AP e senza rete finche' l'utente
        non sceglie di nuovo una rete a mano. Ordine dei tentativi: la rete
        che era attiva prima dell'AP, poi la scelta automatica di
        NetworkManager ('device connect'), poi i profili salvati dal piu'
        recente (cosi' una rete configurata dalla pagina web vince sulle
        vecchie).
        """
        previous = self._previous_ssid
        if previous and self._activate_saved_connection(previous):
            log.info("Reconnected to '%s' (network active before the AP)", previous)
            self._previous_ssid = None
            return True

        try:
            r = subprocess.run(
                ["nmcli", "device", "connect", self.ifname],
                capture_output=True, text=True, timeout=30,
            )
            if r.returncode == 0:
                log.info("Reconnected to a previously known network")
                return True
            detail = r.stderr.strip() or r.stdout.strip()
            log.info("No known network available to reconnect to: %s", detail)
        except subprocess.TimeoutExpired:
            log.warning("Timeout while trying to reconnect to a known network")
        except Exception as e:
            log.warning("Failed to reconnect to a known network: %s", e)

        for name in self._reconnect_candidates(skip=previous):
            if self._activate_saved_connection(name):
                log.info("Reconnected to saved network '%s'", name)
                return True
        log.warning("Could not reconnect to any known Wi-Fi network")
        return False

    def _reconnect_candidates(self, skip: str | None = None) -> list[str]:
        """Profili salvati da provare, quelli in portata per primi.

        Non e' detto che la rete giusta sia l'ultima usata (il box si sposta:
        casa, studio, hotel), quindi si provano tutte quelle conosciute; le
        reti viste dalla scansione hanno priorita' perche' le altre
        farebbero solo perdere tempo in tentativi destinati a fallire.
        """
        candidates = [n for n in self._saved_connections_by_recency() if n != skip]
        try:
            visible = {net["ssid"] for net in self.scan_networks() if net.get("ssid")}
        except Exception:
            visible = set()
        if not visible:
            return candidates
        # Il nome del profilo di solito coincide con l'SSID, ma non sempre:
        # i profili non riconosciuti restano in coda invece di essere scartati.
        in_range = [n for n in candidates if n in visible]
        others = [n for n in candidates if n not in visible]
        return in_range + others

    def _activate_saved_connection(self, name: str) -> bool:
        """Attiva un profilo Wi-Fi salvato per nome (nmcli connection up)."""
        try:
            r = subprocess.run(
                ["nmcli", "connection", "up", name, "ifname", self.ifname],
                capture_output=True, text=True, timeout=30,
            )
            return r.returncode == 0
        except Exception:
            return False

    def _saved_connections_by_recency(self) -> list[str]:
        """Profili Wi-Fi salvati, dal piu' usato di recente al piu' vecchio."""
        try:
            r = subprocess.run(
                ["nmcli", "-t", "-f", "TYPE,TIMESTAMP,NAME", "connection", "show"],
                capture_output=True, text=True, timeout=10,
            )
            rows = []
            for line in r.stdout.strip().splitlines():
                if not line.startswith("802-11-wireless:"):
                    continue
                parts = line.split(":", 2)
                if len(parts) < 3 or parts[2] == self.AP_CONNECTION_NAME:
                    continue
                try:
                    timestamp = int(parts[1])
                except ValueError:
                    timestamp = 0
                rows.append((timestamp, parts[2]))
            rows.sort(key=lambda row: row[0], reverse=True)
            return [name for _, name in rows]
        except Exception:
            return []

    def scan_networks(self) -> list[dict]:
        try:
            output = nmcli.device.wifi(ifname=self.ifname, rescan=True)
        except Exception:
            try:
                output = nmcli.device.wifi(ifname=self.ifname)
            except Exception as e:
                log.error("Failed to scan networks: %s", e)
                return []
        seen = set()
        unique = []
        for row in output:
            if row.ssid and row.ssid not in seen:
                seen.add(row.ssid)
                unique.append({
                    "ssid": row.ssid,
                    "signal": row.signal,
                    "security": row.security,
                    "channel": row.chan,
                })
        return unique

    def connect_to_network(self, ssid: str, password: str = "") -> bool:
        # wlan0 e' una sola interfaccia fisica: non puo' essere AP e client
        # allo stesso tempo, quindi l'AP va fermato per provare la nuova
        # rete. Se il tentativo fallisce, l'AP viene ripristinato invece di
        # lasciare il box senza AP e senza rete (irraggiungibile finche' non
        # si intervene fisicamente).
        # reconnect=False: si sta per tentare esplicitamente un'altra rete,
        # non ha senso lasciare che nmcli ne scelga un'altra nel frattempo.
        ap_was_active = self.is_ap_active()
        try:
            self.stop_ap(reconnect=False)
        except Exception:
            pass
        cmd = ["nmcli", "device", "wifi", "connect", ssid]
        if password:
            cmd += ["password", password]
        cmd += ["ifname", self.ifname]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if r.returncode == 0:
                log.info("Connected to '%s'", ssid)
                # Diventa la rete "di prima" per il prossimo ciclo AP:
                # altrimenti uno stop successivo tornerebbe sulla vecchia.
                self._previous_ssid = ssid
                return True
            detail = r.stderr.strip() or r.stdout.strip()
            log.error("Failed to connect to '%s': %s", ssid, detail)
        except subprocess.TimeoutExpired:
            log.error("Failed to connect to '%s': timeout", ssid)
        # Connessione non riuscita: rimane la rete precedente se nmcli non ha
        # toccato quella attiva, altrimenti si ripristina l'AP per non
        # perdere ogni accesso al box.
        if ap_was_active and not self.is_ap_active() and not self.get_current_ssid():
            self._restore_ap()
        return False

    def _restore_ap(self) -> None:
        try:
            ssid = self.cfg.wifi_ap_ssid
            password = self.cfg.wifi_ap_password
            if not password:
                log.error("Cannot restore AP: WIFI_AP_PASSWORD not set")
                return
            self.start_ap(ssid, password)
            log.warning("Connection attempt failed: access point restored so the box stays reachable")
        except Exception as e:
            log.error("Failed to restore access point after failed connection: %s", e)

    def is_ap_active(self) -> bool:
        try:
            nmcli.connection.show(self.AP_CONNECTION_NAME)
            return True
        except NotExistException:
            return False
        except Exception:
            return False

    def get_current_ssid(self) -> str | None:
        try:
            r = subprocess.run(
                ["nmcli", "-t", "-f", "TYPE,NAME,DEVICE", "connection", "show", "--active"],
                capture_output=True, text=True, timeout=10,
            )
            for line in r.stdout.strip().splitlines():
                if line.startswith("802-11-wireless:") and line.count(":") >= 2:
                    parts = line.split(":", 2)
                    if parts[2]:
                        return parts[1]
            return None
        except Exception:
            return None

    def get_saved_connections(self) -> list[str]:
        try:
            r = subprocess.run(
                ["nmcli", "-t", "-f", "TYPE,NAME", "connection", "show"],
                capture_output=True, text=True, timeout=10,
            )
            saved = []
            for line in r.stdout.strip().splitlines():
                if line.startswith("802-11-wireless:"):
                    name = line.split(":", 1)[1]
                    if name != self.AP_CONNECTION_NAME:
                        saved.append(name)
            return saved
        except Exception:
            return []

    def check_internet(self) -> bool:
        try:
            r = subprocess.run(
                ["nmcli", "networking", "connectivity", "check"],
                capture_output=True, text=True, timeout=15,
            )
            return r.stdout.strip() == "full"
        except Exception:
            return False

    def forget_connection(self, ssid: str) -> bool:
        try:
            r = subprocess.run(
                ["nmcli", "connection", "delete", ssid],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0:
                log.info("Forgot connection '%s'", ssid)
                return True
            log.error("Failed to forget '%s': %s", ssid, r.stderr.strip())
            return False
        except Exception as e:
            log.error("Failed to forget '%s': %s", ssid, e)
            return False

    def disconnect(self) -> bool:
        try:
            r = subprocess.run(
                ["nmcli", "device", "disconnect", self.ifname],
                capture_output=True, text=True, timeout=10,
            )
            return r.returncode == 0
        except Exception:
            return False

    def change_password(self, ssid: str, password: str) -> bool:
        try:
            r = subprocess.run(
                ["nmcli", "connection", "modify", ssid, "802-11-wireless-security.psk", password],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0:
                log.info("Password updated for '%s'", ssid)
                return True
            log.error("Failed to update password for '%s': %s", ssid, r.stderr.strip())
            return False
        except Exception as e:
            log.error("Failed to update password for '%s': %s", ssid, e)
            return False
