import logging

import nmcli
from nmcli._exception import NotExistException

nmcli.disable_use_sudo()


log = logging.getLogger(__name__)


class WiFiManager:
    AP_CONNECTION_NAME = "Amarelli AP"
    AP_IP = "192.168.4.1"

    def __init__(self, cfg):
        self.cfg = cfg
        self.ifname = cfg.wifi_interface

    def down_device(self):
        try:
            nmcli.device.down(self.ifname)
        except NotExistException:
            log.debug("Device %s not active, skipping down", self.ifname)

    def delete_connection(self):
        try:
            nmcli.connection.delete(self.AP_CONNECTION_NAME)
        except NotExistException:
            log.debug(
                "Connection %s not present, skipping delete", self.AP_CONNECTION_NAME
            )

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
        }

    def _ensure_ip_forward(self):
        import subprocess
        subprocess.run(
            ["sysctl", "-w", "net.ipv4.ip_forward=1"],
            capture_output=True, check=False,
        )

    def _add_iptables_rules(self):
        import subprocess
        subprocess.run(
            ["iptables", "-t", "nat", "-C", "PREROUTING",
             "-p", "tcp", "--dport", "80",
             "-j", "REDIRECT", "--to-port", "5000"],
            capture_output=True, check=False,
        )
        subprocess.run(
            ["iptables", "-t", "nat", "-A", "PREROUTING",
             "-p", "tcp", "--dport", "80",
             "-j", "REDIRECT", "--to-port", "5000"],
            capture_output=True, check=False,
        )
        subprocess.run(
            ["iptables", "-t", "nat", "-C", "PREROUTING",
             "-p", "udp", "--dport", "53",
             "-j", "REDIRECT", "--to-port", "1053"],
            capture_output=True, check=False,
        )
        subprocess.run(
            ["iptables", "-t", "nat", "-A", "PREROUTING",
             "-p", "udp", "--dport", "53",
             "-j", "REDIRECT", "--to-port", "1053"],
            capture_output=True, check=False,
        )

    def _del_iptables_rules(self):
        import subprocess
        subprocess.run(
            ["iptables", "-t", "nat", "-D", "PREROUTING",
             "-p", "tcp", "--dport", "80",
             "-j", "REDIRECT", "--to-port", "5000"],
            capture_output=True, check=False,
        )
        subprocess.run(
            ["iptables", "-t", "nat", "-D", "PREROUTING",
             "-p", "udp", "--dport", "53",
             "-j", "REDIRECT", "--to-port", "1053"],
            capture_output=True, check=False,
        )

    def _ensure_cert(self) -> tuple[str, str]:
        import os, tempfile, subprocess as _subprocess
        cert_dir = tempfile.mkdtemp(prefix="amarelli_tls_")
        cert_path = os.path.join(cert_dir, "cert.pem")
        key_path = os.path.join(cert_dir, "key.pem")
        _subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048",
             "-keyout", key_path, "-out", cert_path,
             "-days", "3650", "-nodes",
             "-subj", f"/CN={self.AP_IP}/O=Amarelli"],
            capture_output=True, check=True,
        )
        log.info("Self-signed TLS cert generated at %s", cert_path)
        self._cert_dir = cert_dir
        return cert_path, key_path

    def _start_captive_tls(self):
        import ssl, socket, threading, os, subprocess as _subprocess
        cert_path, key_path = self._ensure_cert()
        CAPTIVE_PATHS = (
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
        log.info("Captive TLS server listening on :443")
        stop_event = threading.Event()
        def client_thread(conn):
            try:
                data = conn.recv(4096)
                if data:
                    request_line = data.split(b"\r\n")[0]
                    path = request_line.split(b" ")[1] if b" " in request_line else b"/"
                    is_captive = any(path.startswith(p) for p in CAPTIVE_PATHS)
                    if is_captive:
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
                    t = threading.Thread(target=client_thread, args=(ssock,), daemon=True)
                    t.start()
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
        import shutil
        if hasattr(self, '_tls_stop_event'):
            self._tls_stop_event.set()
        if hasattr(self, '_tls_server_sock'):
            try:
                self._tls_server_sock.close()
            except Exception:
                pass
        if hasattr(self, '_cert_dir'):
            shutil.rmtree(self._cert_dir, ignore_errors=True)
        log.info("Captive TLS server stopped")

    def _start_dns_server(self):
        import socket, struct, threading

        CAPTIVE_DOMAINS = (
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
        log.info("DNS server listening on :1053")

        def run():
            while True:
                try:
                    data, addr = sock.recvfrom(1024)
                    if len(data) < 12:
                        continue
                    tid = data[:2]
                    flags = data[2:4]
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
                            qname_parts.append(data[pos:pos+length])
                            qname_pos = pos
                            pos += length
                            if length >= 192:
                                break
                        qname = b".".join(qname_parts).lower()
                        if pos + 4 > len(data):
                            break
                        qtype = struct.unpack(">H", data[pos:pos+2])[0]
                        qclass = struct.unpack(">H", data[pos+2:pos+4])[0]
                        pos += 4
                        spoof = any(qname.endswith(d) for d in CAPTIVE_DOMAINS)
                        if not spoof:
                            continue
                        response = bytearray()
                        response += tid
                        response += struct.pack(">H", 0x8580)
                        response += struct.pack(">H", 1)
                        response += struct.pack(">H", 1)
                        response += struct.pack(">H", 0)
                        response += struct.pack(">H", 0)
                        response += data[original_pos:pos]
                        ip = socket.inet_aton(self.AP_IP)
                        response += struct.pack(">H", 0xC00C)
                        response += struct.pack(">H", qtype)
                        response += struct.pack(">H", 1)
                        response += struct.pack(">I", 60)
                        response += struct.pack(">H", 4)
                        response += ip
                        sock.sendto(response, addr)
                        log.debug("DNS spoof: %s -> %s", qname, self.AP_IP)
                except Exception:
                    pass

        t = threading.Thread(target=run, daemon=True)
        t.start()
        self._dns_thread = t
        return t

    def _stop_dns_server(self):
        log.info("DNS server stopped")

    def start_ap(self, ssid, password):
        if not password:
            raise ValueError("Password is required")

        self.down_device()
        self.delete_connection()
        self._ensure_ip_forward()

        nmcli.connection.add(
            conn_type="wifi",
            ifname=self.ifname,
            name=self.AP_CONNECTION_NAME,
            options=self._ap_options(ssid, password),
        )
        nmcli.connection.up(self.AP_CONNECTION_NAME)
        self._add_iptables_rules()
        self._start_captive_tls()
        self._start_dns_server()
        log.info("Access point '%s' active on %s", ssid, self.ifname)

    def stop_ap(self):
        self._del_iptables_rules()
        self._stop_captive_tls()
        self._stop_dns_server()
        try:
            nmcli.connection.down(self.AP_CONNECTION_NAME)
            log.info("Access point stopped")
        except NotExistException:
            log.warning("Access point '%s' not active", self.AP_CONNECTION_NAME)

    def scan_networks(self) -> list[dict]:
        try:
            output = nmcli.device.wifi(ifname=self.ifname, rescan=True)
        except Exception:
            try:
                output = nmcli.device.wifi(ifname=self.ifname)
            except Exception as e:
                log.error("Failed to scan networks: %s", e)
                return []
        networks = []
        for row in output:
            networks.append({
                "ssid": row.ssid,
                "signal": row.signal,
                "security": row.security,
                "channel": row.chan,
            })
        seen = set()
        unique = []
        for n in networks:
            if n["ssid"] and n["ssid"] not in seen:
                seen.add(n["ssid"])
                unique.append(n)
        return unique

    def connect_to_network(self, ssid: str, password: str = "") -> bool:
        import subprocess
        try:
            self.stop_ap()
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
                return True
            else:
                detail = r.stderr.strip() or r.stdout.strip()
                log.error("Failed to connect to '%s': %s", ssid, detail)
                return False
        except subprocess.TimeoutExpired:
            log.error("Failed to connect to '%s': timeout", ssid)
            return False

    def is_ap_active(self) -> bool:
        try:
            nmcli.connection.show(self.AP_CONNECTION_NAME)
            return True
        except NotExistException:
            return False
        except Exception:
            return False

    def get_current_ssid(self) -> str | None:
        import subprocess
        try:
            r = subprocess.run(
                ["nmcli", "-t", "-f", "TYPE,NAME,DEVICE", "connection", "show", "--active"],
                capture_output=True, text=True, timeout=10
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
        import subprocess
        try:
            r = subprocess.run(
                ["nmcli", "-t", "-f", "TYPE,NAME", "connection", "show"],
                capture_output=True, text=True, timeout=10
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
        import subprocess
        try:
            r = subprocess.run(
                ["nmcli", "networking", "connectivity", "check"],
                capture_output=True, text=True, timeout=15
            )
            return r.stdout.strip() == "full"
        except Exception:
            return False

    def forget_connection(self, ssid: str) -> bool:
        import subprocess
        try:
            r = subprocess.run(
                ["nmcli", "connection", "delete", ssid],
                capture_output=True, text=True, timeout=10
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
        import subprocess
        try:
            r = subprocess.run(
                ["nmcli", "device", "disconnect", self.ifname],
                capture_output=True, text=True, timeout=10
            )
            return r.returncode == 0
        except Exception:
            return False

    def change_password(self, ssid: str, password: str) -> bool:
        import subprocess
        try:
            r = subprocess.run(
                ["nmcli", "connection", "modify", ssid, "802-11-wireless-security.psk", password],
                capture_output=True, text=True, timeout=10
            )
            if r.returncode == 0:
                log.info("Password updated for '%s'", ssid)
                return True
            log.error("Failed to update password for '%s': %s", ssid, r.stderr.strip())
            return False
        except Exception as e:
            log.error("Failed to update password for '%s': %s", ssid, e)
            return False
