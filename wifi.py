import logging

import nmcli
from nmcli._exception import NotExistException


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

    def start_ap(self, ssid, password):
        if not password:
            raise ValueError("Password is required")

        self.down_device()
        self.delete_connection()

        nmcli.connection.add(
            conn_type="wifi",
            ifname=self.ifname,
            name=self.AP_CONNECTION_NAME,
            options=self._ap_options(ssid, password),
        )
        nmcli.connection.up(self.AP_CONNECTION_NAME)
        log.info("Access point '%s' active on %s", ssid, self.ifname)

    def stop_ap(self):
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
                "channel": row.channel,
            })
        seen = set()
        unique = []
        for n in networks:
            if n["ssid"] and n["ssid"] not in seen:
                seen.add(n["ssid"])
                unique.append(n)
        return unique

    def connect_to_network(self, ssid: str, password: str = "") -> bool:
        try:
            self.stop_ap()
        except Exception:
            pass
        try:
            nmcli.device.wifi_connect(ssid, password, ifname=self.ifname)
            log.info("Connected to '%s'", ssid)
            return True
        except Exception as e:
            log.error("Failed to connect to '%s': %s", ssid, e)
            return False

    def is_ap_active(self) -> bool:
        try:
            nmcli.connection.show(self.AP_CONNECTION_NAME)
            return True
        except NotExistException:
            return False
        except Exception:
            return False
