import json
import logging
import os
import subprocess
from pathlib import Path

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


def _signal_bars(pct: int) -> str:
    if pct >= 75:
        return "\u2582\u2584\u2586\u2588"
    if pct >= 50:
        return "\u2582\u2584\u2586"
    if pct >= 25:
        return "\u2582\u2584"
    return "\u2582"


def _get_rclone_remotes() -> list[str]:
    """Ritorna i remoti configurati in rclone (es. ['dropbox:', 'gdrive:'])."""
    try:
        # Prova a rispettare RCLONE_CONFIG_FILE dal .env/config se presente
        cfg_path = os.getenv("RCLONE_CONFIG_FILE", "")
        cmd = ["rclone", "listremotes"]
        if cfg_path:
            cmd = ["rclone", "--config", cfg_path, "listremotes"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except FileNotFoundError:
        return []
    except Exception:
        return []
    return []


def _h(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


CSS = """* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, system-ui, sans-serif; background: #f0f2f5; color: #1c1e21; padding: 0; }
.header { background: #fff; padding: 14px 16px; border-bottom: 1px solid #dadde1; display: flex; align-items: center; gap: 10px; }
.header h1 { font-size: 1.15em; font-weight: 600; flex: 1; }
.dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; flex-shrink: 0; }
.dot-on { background: #31a24c; }
.dot-off { background: #dadde1; }
.card { background: #fff; margin: 12px 12px 0; border-radius: 10px; box-shadow: 0 1px 2px rgba(0,0,0,.06); overflow: hidden; }
.card-title { font-size: .8em; font-weight: 600; color: #65676b; text-transform: uppercase; letter-spacing: .04em; padding: 12px 16px 4px; }
.row { display: flex; align-items: center; gap: 10px; padding: 10px 16px; border-top: 1px solid #f0f2f5; text-decoration: none; color: inherit; min-height: 44px; }
.row:first-child { border-top: none; }
.row .name { flex: 1; font-size: .95em; font-weight: 500; }
.row .name small { font-weight: 400; color: #65676b; font-size: .85em; display: block; }
.row .signal { color: #65676b; font-size: .9em; white-space: nowrap; }
.row .actions { display: flex; gap: 6px; flex-shrink: 0; }
.btn-link { background: none; border: none; color: #216fdb; font-size: .85em; cursor: pointer; padding: 4px 6px; border-radius: 4px; }
.btn-link:hover { background: #e7f3ff; }
.btn-link.danger { color: #e41e3f; }
.btn-link.danger:hover { background: #ffe9ec; }
input[type=text], input[type=password] { width: 100%; padding: 10px 12px; border: 1px solid #ccd0d5; border-radius: 6px; font-size: .95em; outline: none; }
input[type=text]:focus, input[type=password]:focus { border-color: #216fdb; box-shadow: 0 0 0 1px #216fdb; }
.pwd-row { display: flex; align-items: center; gap: 6px; padding: 6px 16px 12px; }
.pwd-row input { flex: 1; }
.btn-eye { background: none; border: 1px solid #ccd0d5; border-radius: 6px; padding: 8px 10px; cursor: pointer; font-size: 1em; line-height: 1; }
.btn-block { display: block; width: calc(100% - 32px); margin: 0 16px 12px; padding: 10px; border: none; border-radius: 8px; font-size: .95em; font-weight: 600; cursor: pointer; text-align: center; }
.btn-primary { background: #216fdb; color: #fff; }
.btn-primary:hover { background: #1a5fc7; }
.btn-success { background: #31a24c; color: #fff; }
.btn-success:hover { background: #28853b; }
.btn-danger { background: #e41e3f; color: #fff; }
.btn-danger:hover { background: #c91836; }
.text-muted { color: #65676b; font-size: .82em; padding: 12px 16px; }
.flash { padding: 10px 16px; font-size: .9em; margin: 8px 12px 0; border-radius: 8px; }
.flash-success { background: #d4edda; color: #155724; }
.flash-error { background: #f8d7da; color: #721c24; }
.empty { color: #65676b; font-size: .88em; padding: 14px 16px; }"""


def create_app(wifi_manager=None, db=None, bus=None):
    app = Flask(__name__)

    @app.route("/generate_204")
    @app.route("/nm/generate_204")
    @app.route("/hotspot-detect.html")
    @app.route("/library/test/success.html")
    @app.route("/success.txt")
    def captive_check():
        return "", 204

    @app.route("/")
    def index():
        if not wifi_manager:
            return """<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Amarelli</title>
<style>body{font-family:-apple-system,sans-serif;padding:16px;background:#f0f2f5;color:#1c1e21}
h1{font-size:1.2em}.card{background:#fff;border-radius:10px;padding:16px;margin-top:12px}</style>
</head><body><div class="card"><h1>Amarelli Backup</h1>
<p class="text-muted">No WiFi manager available.</p></div></body></html>"""

        networks = wifi_manager.scan_networks()
        current = wifi_manager.get_current_ssid()
        saved = wifi_manager.get_saved_connections()
        online = wifi_manager.check_internet()
        ip = get_ip_address()
        ap_active = wifi_manager.is_ap_active()

        connected = current or "N/A"
        online_dot = "dot-on" if online else "dot-off"
        online_label = "Connected to Internet" if online else "Not connected"

        seen_ssids = {n["ssid"] for n in networks}

        saved_known = [s for s in saved if s != current and s in seen_ssids]
        saved_other = [s for s in saved if s != current and s not in seen_ssids]
        available = [n for n in networks if n["ssid"] and n["ssid"] != current]

        known_rows = ""
        for ssid in saved_known:
            known_rows += f"""<div class="row">
<div class="name">{_h(ssid)} <small>Saved</small></div>
<div class="actions">
<form method="post" action="/connect" style="display:inline">
<input type="hidden" name="ssid" value="{_h(ssid)}">
<button class="btn-link">Connect</button>
</form>
<button class="btn-link" onclick="showPwdForm('{_h(ssid)}')">Password</button>
<form method="post" action="/forget" style="display:inline"
onsubmit="return confirm('Forget &quot;{_h(ssid)}&quot;?')">
<input type="hidden" name="ssid" value="{_h(ssid)}">
<button class="btn-link danger">Forget</button>
</form>
</div></div>"""

        saved_hidden = ""
        for ssid in saved_other:
            saved_hidden += f"""<div class="row">
<div class="name">{_h(ssid)} <small>Not in range</small></div>
<div class="actions">
<button class="btn-link" onclick="showPwdForm('{_h(ssid)}')">Password</button>
<form method="post" action="/forget" style="display:inline"
onsubmit="return confirm('Forget &quot;{_h(ssid)}&quot;?')">
<input type="hidden" name="ssid" value="{_h(ssid)}">
<button class="btn-link danger">Forget</button>
</form>
</div></div>"""

        avail_rows = ""
        for n in available:
            sec = n["security"] if n["security"] else "Open"
            bars = _signal_bars(n["signal"])
            avail_rows += f"""<div class="row">
<div class="name">{_h(n["ssid"])} <small>{sec}</small></div>
<div class="signal">{bars} {n["signal"]}%</div>
<div class="actions">
<form method="post" action="/connect" style="display:inline">
<input type="hidden" name="ssid" value="{_h(n["ssid"])}">
<button class="btn-link">Connect</button>
</form>
</div></div>"""

        ap_badge = ""
        if ap_active:
            ap_badge = '<div class="text-muted" style="padding-top:0">AP: {ip}:5000</div>'

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Amarelli WiFi</title>
<style>{CSS}</style>
</head>
<body>

<div class="header">
<span class="dot {online_dot}" title="{online_label}"></span>
<h1>Amarelli Backup</h1>
<a href="/config" style="font-size:1.1em;text-decoration:none;color:#65676b" title="Settings">\u2699</a>
<span class="text-muted" style="font-size:.82em">{ip}</span>
</div>
{ap_badge}
<div id="msg"></div>

<div class="card">
<div class="card-title">Connected</div>
<div class="row">
<div class="name">{_h(connected)}</div>
<div class="actions">
<form method="post" action="/disconnect" style="display:inline"
onsubmit="return confirm('Disconnect from &quot;{_h(connected)}&quot;?')">
<button class="btn-link danger">Disconnect</button>
</form>
</div>
</div>
</div>

<div class="card">
<div class="card-title">Saved networks</div>
{known_rows if known_rows else '<div class="empty">No saved networks.</div>'}
</div>

<div class="card">
<div class="card-title">Available networks</div>
{avail_rows if avail_rows else '<div class="empty">No networks found.</div>'}
</div>

<div class="card">
<div class="card-title">Add new network</div>
<div class="pwd-row">
<input type="text" id="new-ssid" placeholder="SSID">
</div>
<div class="pwd-row">
<input type="password" id="new-pwd" placeholder="Password (if required)">
<button type="button" class="btn-eye" onclick="toggleNew()" aria-label="Show/Hide">\U0001F441</button>
</div>
<button class="btn btn-block btn-success" onclick="addNetwork()">Add & connect</button>
</div>

<div class="card" id="pwd-card" style="display:none">
<div class="card-title">Change password</div>
<div class="pwd-row">
<input type="password" id="chg-pwd" placeholder="New password">
<button type="button" class="btn-eye" onclick="toggleChg()" aria-label="Show/Hide">\U0001F441</button>
</div>
<button class="btn btn-block btn-primary" onclick="changePwd()">Save password</button>
</div>

<script>
const params = new URLSearchParams(window.location.search);
const ok = params.get('ok');
const err = params.get('err');
const msg = document.getElementById('msg');
if (ok) msg.innerHTML = '<div class="flash flash-success">' + ok + '</div>';
if (err) msg.innerHTML = '<div class="flash flash-error">' + err + '</div>';

var _chgSsid = '';

function showPwdForm(ssid) {{
    _chgSsid = ssid;
    document.getElementById('pwd-card').style.display = 'block';
    document.getElementById('chg-pwd').value = '';
    document.getElementById('pwd-card').scrollIntoView({{ behavior: 'smooth' }});
}}

function changePwd() {{
    var pwd = document.getElementById('chg-pwd').value;
    if (!pwd) return alert('Please enter a password.');
    var f = document.createElement('form');
    f.method = 'post';
    f.action = '/change-password';
    f.innerHTML = '<input name="ssid" value="' + _chgSsid + '"><input name="password" value="' + pwd + '">';
    document.body.appendChild(f);
    f.submit();
}}

function toggleNew() {{
    var f = document.getElementById('new-pwd');
    f.type = f.type === 'password' ? 'text' : 'password';
}}

function toggleChg() {{
    var f = document.getElementById('chg-pwd');
    f.type = f.type === 'password' ? 'text' : 'password';
}}

function addNetwork() {{
    var ssid = document.getElementById('new-ssid').value;
    var pwd = document.getElementById('new-pwd').value;
    if (!ssid) return alert('Please enter the network name.');
    var f = document.createElement('form');
    f.method = 'post';
    f.action = '/connect';
    f.innerHTML = '<input name="ssid" value="' + ssid + '"><input name="password" value="' + pwd + '">';
    document.body.appendChild(f);
    f.submit();
}}
</script>
</body>
</html>"""

    def _redirect_with(query: str):
        return redirect(f"/{query}")

    @app.route("/connect", methods=["POST"])
    def connect():
        ssid = request.form.get("ssid", "").strip()
        password = request.form.get("password", "")
        if not ssid or not wifi_manager:
            return _redirect_with("?err=No+WiFi+manager")
        ok = wifi_manager.connect_to_network(ssid, password)
        if ok:
            return _redirect_with(f"?ok=Connected+to+{ssid}")
        return _redirect_with(f"?err=Connection+failed+to+{ssid}")

    @app.route("/disconnect", methods=["POST"])
    def disconnect():
        if not wifi_manager:
            return _redirect_with("?err=No+WiFi+manager")
        wifi_manager.disconnect()
        return _redirect_with("?ok=Disconnected")

    @app.route("/forget", methods=["POST"])
    def forget():
        ssid = request.form.get("ssid", "").strip()
        if not ssid or not wifi_manager:
            return _redirect_with("?err=No+WiFi+manager")
        wifi_manager.forget_connection(ssid)
        return _redirect_with(f"?ok=Network+'{ssid}'+forgotten")

    @app.route("/change-password", methods=["POST"])
    def change_password():
        ssid = request.form.get("ssid", "").strip()
        password = request.form.get("password", "")
        if not ssid or not password or not wifi_manager:
            return _redirect_with("?err=Missing+parameters")
        wifi_manager.change_password(ssid, password)
        return _redirect_with(f"?ok=Password+updated+for+'{ssid}'")

    @app.route("/status")
    def status():
        if not wifi_manager:
            return jsonify({"error": "no wifi manager"}), 503
        return jsonify({
            "ip": get_ip_address(),
            "interface": wifi_manager.ifname,
            "connected_ssid": wifi_manager.get_current_ssid(),
            "ap_active": wifi_manager.is_ap_active(),
            "online": wifi_manager.check_internet(),
            "saved": wifi_manager.get_saved_connections(),
        })

    @app.route("/config")
    def config_page():
        try:
            with open(Path(__file__).resolve().parent.parent / "config.json") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}

        def _val(key):
            v = cfg.get(key)
            if v is None:
                return ""
            return str(v)

        def _select(name, current, options):
            opts = ""
            for val, label in options.items():
                sel = ' selected' if str(val) == str(current) else ''
                opts += f'<option value="{_h(val)}"{sel}>{_h(label)}</option>'
            return f'<select name="{_h(name)}" style="width:100%;padding:10px 12px;border:1px solid #ccd0d5;border-radius:6px;font-size:.95em;outline:none;background:#fff">{opts}</select>'

        def _text(name):
            return f'<input type="text" name="{_h(name)}" value="{_h(_val(name))}" style="width:100%;padding:10px 12px;border:1px solid #ccd0d5;border-radius:6px;font-size:.95em;outline:none">'

        prune_cur = cfg.get("prune_min_days")
        prune_display = "keep" if prune_cur is None else str(prune_cur)

        mode_sel = _select("mode", _val("mode"), {"upload": "Upload only", "mirror": "Mirroring"})
        filter_sel = _select("file_filter", _val("file_filter"), {"all": "All files", "images": "Photos only (JPG+RAW)", "jpg": "JPG only"})
        prune_sel = _select("prune_min_days", prune_display, {"immediate": "Delete now", "7": "After 7 days", "30": "After 30 days", "keep": "Keep forever"})
        op_mode_sel = _select("operation_mode", _val("operation_mode") or "manual", {"manual": "Manual (step-by-step)", "auto": "Automatic (LED headless)"})

        # --- rclone remotes ---
        remotes = _get_rclone_remotes()
        current_remote = _val("rclone_remote")
        # Assicura che il valore attuale sia tra le opzioni anche se non più listato
        datalist_opts = ""
        seen = set(remotes)
        if current_remote and current_remote not in seen:
            seen.add(current_remote)
            remotes = [current_remote] + remotes
        for r in remotes:
            datalist_opts += f'<option value="{_h(r)}">'
        rclone_hint = ""
        if not remotes:
            rclone_hint = '<div class="text-muted" style="padding:4px 0 0">Nessun remoto trovato: esegui <code>rclone config</code> sulla Raspberry.</div>'
        else:
            rclone_hint = '<div class="text-muted" style="padding:4px 0 0">Scegli un remoto rclone o inserisci un percorso locale (es. <code>/mnt/usb/backup</code>).</div>'

        uploader_sel = _select("uploader", _val("uploader") or "rclone", {"rclone": "rclone (Dropbox, Drive, S3, ...)", "webdav": "WebDAV"})

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Amarelli Settings</title>
<style>{CSS}
select:focus {{ border-color: #216fdb; box-shadow: 0 0 0 1px #216fdb; }}
</style>
</head>
<body>

<div class="header">
<h1>Amarelli Backup</h1>
<a href="/" style="font-size:1.1em;text-decoration:none;color:#65676b" title="WiFi">&larr; Back</a>
<a href="/logs" style="font-size:.9em;text-decoration:none;color:#65676b" title="Logs">\U0001F4CB</a>
</div>
<div id="msg"></div>

<form method="post" action="/config">

<div class="card">
<div class="card-title">Paths</div>
<div class="row" style="display:block;padding:8px 16px 12px"><div style="font-size:.8em;color:#65676b;margin-bottom:4px">SD source path</div>{_text("sd_src")}</div>
<div class="row" style="display:block;padding:8px 16px 12px"><div style="font-size:.8em;color:#65676b;margin-bottom:4px">Cache path</div>{_text("cache_path")}</div>
<div class="row" style="display:block;padding:8px 16px 12px"><div style="font-size:.8em;color:#65676b;margin-bottom:4px">Cloud destination</div>{_text("cloud_dst")}</div>
<div class="row" style="display:block;padding:8px 16px 12px"><div style="font-size:.8em;color:#65676b;margin-bottom:4px">Log path</div>{_text("log_path")}</div>
</div>

<div class="card">
<div class="card-title">Backup</div>
<div class="row" style="display:block;padding:8px 16px 12px"><div style="font-size:.8em;color:#65676b;margin-bottom:4px">Mode</div>{mode_sel}</div>
<div class="row" style="display:block;padding:8px 16px 12px"><div style="font-size:.8em;color:#65676b;margin-bottom:4px">File filter</div>{filter_sel}</div>
<div class="row" style="display:block;padding:8px 16px 12px"><div style="font-size:.8em;color:#65676b;margin-bottom:4px">Prune policy</div>{prune_sel}</div>
<div class="row" style="display:block;padding:8px 16px 12px"><div style="font-size:.8em;color:#65676b;margin-bottom:4px">Operation</div>{op_mode_sel}</div>
</div>

<div class="card">
<div class="card-title">Destinazione backup</div>
<div class="row" style="display:block;padding:8px 16px 12px"><div style="font-size:.8em;color:#65676b;margin-bottom:4px">Backend</div>{uploader_sel}</div>
<div class="row" style="display:block;padding:8px 16px 12px"><div style="font-size:.8em;color:#65676b;margin-bottom:4px">Remoto rclone</div>
<input list="rclone-remotes" name="rclone_remote" value="{_h(current_remote)}" placeholder="es. dropbox:amarelli-test  o  /mnt/usb/backup" style="width:100%;padding:10px 12px;border:1px solid #ccd0d5;border-radius:6px;font-size:.95em;outline:none">
<datalist id="rclone-remotes">{datalist_opts}</datalist>
{rclone_hint}
</div>
<div class="text-muted" style="padding:0 16px 12px">Se <b>WebDAV</b> è selezionato, configura <code>WEBDAV_*</code> nel file <code>.env</code>. Per <b>rclone</b> usa <code>rclone config</code> (vedi README).</div>
</div>

<div class="card">
<div class="card-title">Server</div>
<div class="row" style="display:block;padding:8px 16px 12px"><div style="font-size:.8em;color:#65676b;margin-bottom:4px">Flask host</div>{_text("flask_host")}</div>
<div class="row" style="display:block;padding:8px 16px 12px"><div style="font-size:.8em;color:#65676b;margin-bottom:4px">Flask port</div>{_text("flask_port")}</div>
</div>

<button class="btn btn-block btn-primary" style="margin-top:12px">Save changes</button>
</form>

<script>
const params = new URLSearchParams(window.location.search);
const ok = params.get('ok');
const err = params.get('err');
const msg = document.getElementById('msg');
if (ok) msg.innerHTML = '<div class="flash flash-success">' + ok + '</div>';
if (err) msg.innerHTML = '<div class="flash flash-error">' + err + '</div>';
</script>
</body>
</html>"""

    @app.route("/config", methods=["POST"])
    def config_save():
        if bus is None:
            return _redirect_with("?err=No+config+manager")
        for key in request.form:
            value = request.form[key]
            if key in ("mode", "file_filter", "operation_mode"):
                bus.emit("config:set", key=key, value=value)
            elif key == "prune_min_days":
                if value == "keep":
                    bus.emit("config:set", key="prune_min_days", value=None)
                elif value == "immediate":
                    bus.emit("config:set", key="prune_min_days", value=0)
                else:
                    bus.emit("config:set", key="prune_min_days", value=int(value))
            elif key == "flask_port":
                bus.emit("config:set", key=key, value=int(value) if value else 5000)
            else:
                bus.emit("config:set", key=key, value=value)
        return _redirect_with("?ok=Settings+saved")

    @app.route("/logs")
    def logs():
        try:
            with open("amarelli.log") as f:
                lines = f.readlines()
        except Exception:
            lines = ["(no log file)"]

        tail = lines[-200:]
        html_lines = ""
        for line in tail:
            esc = _h(line.rstrip("\n"))
            html_lines += f"<div>{esc}</div>"

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Amarelli Logs</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: ui-monospace, 'Cascadia Code', 'Fira Code', monospace; background: #1e1e2e; color: #cdd6f4; padding: 0; }}
.header {{ background: #181825; padding: 14px 16px; border-bottom: 1px solid #313244; display: flex; align-items: center; gap: 10px; }}
.header h1 {{ font-size: 1.15em; font-weight: 600; flex: 1; }}
.header a {{ color: #89b4fa; text-decoration: none; font-size: .9em; }}
.entry {{ padding: 2px 16px; font-size: .78em; line-height: 1.5; border-bottom: 1px solid #313244; word-break: break-all; }}
.entry:hover {{ background: #313244; }}
.count {{ color: #6c7086; font-size: .8em; padding: 8px 16px; text-align: center; }}
</style>
</head>
<body>

<div class="header">
<h1>Amarelli Logs</h1>
<a href="/config">&larr; Settings</a>
</div>

<div class="count">{len(tail)} lines (last 200)</div>

{html_lines}

</body>
</html>"""

    return app
