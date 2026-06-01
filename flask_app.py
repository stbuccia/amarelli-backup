import logging
import subprocess

from flask import Flask, request, jsonify, redirect

log = logging.getLogger(__name__)


def get_ip_address() -> str:
    try:
        result = subprocess.run(
            ["hostname", "-I"], capture_output=True, text=True, timeout=5
        )
        ip = result.stdout.strip().split()[0]
        return ip if ip else "N/A"
    except Exception:
        return "N/A"


def create_app(wifi_manager=None, db=None):
    app = Flask(__name__)

    @app.route("/")
    def index():
        networks = []
        current_ssid = "N/A"
        ip = get_ip_address()
        ap_active = False

        if wifi_manager:
            networks = wifi_manager.scan_networks()
            ap_active = wifi_manager.is_ap_active()
            try:
                import nmcli
                statuses = nmcli.device.status()
                for dev in statuses:
                    if dev.device == wifi_manager.ifname and dev.connection:
                        current_ssid = dev.connection
                        break
            except Exception:
                pass

        rows = ""
        for n in networks:
            signal_bars = "▂▄▆█" if n["signal"] >= 75 else "▂▄▆" if n["signal"] >= 50 else "▂▄" if n["signal"] >= 25 else "▂"
            checked = " checked" if n["ssid"] == current_ssid else ""
            rows += f"""<tr>
                <td><input type="radio" name="ssid" value="{n["ssid"]}"{checked}></td>
                <td>{n["ssid"]}</td>
                <td>{signal_bars} {n["signal"]}%</td>
                <td>{n["security"] if n["security"] else "Aperta"}</td>
            </tr>"""

        ap_badge = '<span class="badge badge-on">AP Attivo</span>' if ap_active else '<span class="badge badge-off">AP Spento</span>'

        return f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Amarelli - Connessioni</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, sans-serif; background: #f5f5f5; color: #333; padding: 16px; }}
h1 {{ font-size: 1.4em; margin-bottom: 4px; }}
h2 {{ font-size: 1.1em; margin: 20px 0 10px; }}
.card {{ background: #fff; border-radius: 12px; padding: 16px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
.badge {{ display: inline-block; font-size: .8em; padding: 2px 8px; border-radius: 20px; }}
.badge-on {{ background: #d4edda; color: #155724; }}
.badge-off {{ background: #e2e3e5; color: #383d41; }}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{ text-align: left; padding: 8px 4px; border-bottom: 1px solid #eee; }}
th {{ font-size: .8em; color: #888; }}
input[type=radio] {{ transform: scale(1.2); }}
input[type=text], input[type=password] {{ width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 8px; font-size: 1em; margin: 4px 0; }}
.btn {{ display: inline-block; padding: 10px 20px; border: none; border-radius: 8px; font-size: 1em; cursor: pointer; }}
.btn-primary {{ background: #007bff; color: #fff; }}
.btn-success {{ background: #28a745; color: #fff; }}
.btn-block {{ width: 100%; }}
.mt {{ margin-top: 12px; }}
.text-muted {{ color: #888; font-size: .85em; }}
.flash {{ padding: 10px; border-radius: 8px; margin-bottom: 12px; }}
.flash-success {{ background: #d4edda; color: #155724; }}
.flash-error {{ background: #f8d7da; color: #721c24; }}
</style>
</head>
<body>
<div class="card">
<h1>Amarelli Backup</h1>
<p class="text-muted">IP: {ip} &middot; {ap_badge}</p>
</div>

<div id="msg"></div>

<div class="card">
<h2>Reti disponibili</h2>
<form id="connect-form" method="post" action="/connect">
<table>
<thead><tr><th></th><th>Rete</th><th>Segnale</th><th>Sicurezza</th></tr></thead>
<tbody>{rows}</tbody>
</table>
<div class="mt">
<input type="password" name="password" placeholder="Password (se richiesta)">
<button type="submit" class="btn btn-primary btn-block mt">Connetti</button>
</div>
</form>
</div>

<div class="card">
<h2>Aggiungi nuova rete</h2>
<form method="post" action="/add">
<input type="text" name="ssid" placeholder="Nome rete (SSID)" required>
<input type="password" name="password" placeholder="Password">
<button type="submit" class="btn btn-success btn-block mt">Aggiungi e connetti</button>
</form>
</div>

<div class="card">
<h2>Stato connessione</h2>
<p><a href="/status" class="btn btn-primary">Verifica stato</a></p>
</div>

<script>
const params = new URLSearchParams(window.location.search);
const ok = params.get('ok');
const err = params.get('err');
const msg = document.getElementById('msg');
if (ok) msg.innerHTML = '<div class="flash flash-success">' + ok + '</div>';
if (err) msg.innerHTML = '<div class="flash flash-error">' + err + '</div>';
document.getElementById('connect-form').addEventListener('submit', function(e) {{
    var sel = this.querySelector('input[name=ssid]:checked');
    if (!sel) {{ e.preventDefault(); alert('Seleziona una rete WiFi.'); }}
}});
</script>
</body>
</html>"""

    def _redirect_with(query: str):
        return redirect(f"/{query}")

    @app.route("/connect", methods=["POST"])
    def connect():
        ssid = request.form.get("ssid", "").strip()
        password = request.form.get("password", "")
        if not ssid:
            return index()
        if wifi_manager:
            ok = wifi_manager.connect_to_network(ssid, password)
            if ok:
                return _redirect_with(f"?ok=Connesso+a+{ssid}")
            return _redirect_with(f"?err=Errore+connessione+a+{ssid}")
        return _redirect_with("?err=Nessun+gestore+WiFi")

    @app.route("/add", methods=["POST"])
    def add():
        ssid = request.form.get("ssid", "").strip()
        password = request.form.get("password", "")
        if not ssid:
            return index()
        if wifi_manager:
            ok = wifi_manager.connect_to_network(ssid, password)
            if ok:
                return _redirect_with(f"?ok=Connesso+a+{ssid}")
            return _redirect_with(f"?err=Errore+connessione+a+{ssid}")
        return _redirect_with("?err=Nessun+gestore+WiFi")

    @app.route("/status")
    def status():
        ip = get_ip_address()
        iface = wifi_manager.ifname if wifi_manager else "N/A"
        ap_active = wifi_manager.is_ap_active() if wifi_manager else False
        current_ssid = "N/A"
        try:
            import nmcli
            statuses = nmcli.device.status()
            for dev in statuses:
                if dev.device == iface and dev.connection:
                    current_ssid = dev.connection
                    break
        except Exception:
            pass
        return jsonify({
            "ip": ip,
            "interface": iface,
            "ap_active": ap_active,
            "connected_ssid": current_ssid,
        })

    return app
