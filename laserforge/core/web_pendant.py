"""
LaserForge Mobile Remote Jogger & Workshop Monitoring Web Pendant.
Runs a lightweight embedded HTTP/JSON server allowing users to jog the laser,
frame boundaries, and monitor job progress from any phone or tablet on the local Wi-Fi.
"""

from typing import Dict, Any, Optional, Callable
import http.server
import json
import threading
import socket
import io

PENDANT_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
<title>LaserForge Mobile Jogger ⚡</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
  body { background: #0f172a; color: #f8fafc; padding: 12px; display: flex; flex-direction: column; align-items: center; }
  h1 { font-size: 1.1rem; color: #38bdf8; margin-bottom: 8px; font-weight: 700; text-align: center; }
  .badge { display: inline-block; padding: 4px 10px; border-radius: 9999px; font-size: 0.75rem; font-weight: bold; margin-bottom: 12px; }
  .badge-idle { background: #065f46; color: #34d399; }
  .badge-run { background: #1e40af; color: #60a5fa; }
  .badge-alarm { background: #991b1b; color: #f87171; }
  
  .panel { background: #1e293b; border: 1px solid #334155; border-radius: 12px; width: 100%; max-width: 400px; padding: 14px; margin-bottom: 12px; }
  .step-selector { display: flex; gap: 6px; margin-bottom: 14px; }
  .step-btn { flex: 1; padding: 8px 4px; background: #334155; color: #cbd5e1; border: none; border-radius: 6px; font-weight: bold; font-size: 0.85rem; cursor: pointer; }
  .step-btn.active { background: #0284c7; color: #fff; }
  
  /* Jog Keypad 3x3 Grid */
  .jog-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; max-width: 260px; margin: 0 auto 14px auto; }
  .jog-btn { aspect-ratio: 1; background: #1e3a8a; color: #fff; font-size: 1.4rem; font-weight: bold; border: none; border-radius: 10px; display: flex; align-items: center; justify-content: center; touch-action: manipulation; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.3); }
  .jog-btn:active { background: #2563eb; transform: scale(0.96); }
  .jog-btn.center { background: #334155; font-size: 0.8rem; color: #94a3b8; }
  
  /* Action Buttons */
  .btn-row { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 8px; }
  .act-btn { padding: 12px 8px; border: none; border-radius: 8px; font-weight: bold; font-size: 0.9rem; cursor: pointer; touch-action: manipulation; }
  .btn-frame { background: #0d9488; color: #fff; }
  .btn-laser { background: #d97706; color: #fff; }
  .btn-home { background: #475569; color: #fff; }
  .btn-unlock { background: #4f46e5; color: #fff; }
  .btn-estop { background: #dc2626; color: #fff; width: 100%; padding: 16px; font-size: 1.1rem; border-radius: 10px; margin-top: 6px; font-weight: 800; }
  .coords { font-family: monospace; font-size: 0.9rem; color: #38bdf8; text-align: center; margin-bottom: 8px; }
</style>
</head>
<body>
  <h1>LaserForge Mobile Jogger ⚡</h1>
  <div id="statusBadge" class="badge badge-idle">IDLE</div>
  <div class="coords" id="coordsDisplay">X: 0.00 | Y: 0.00 | Z: 0.00</div>

  <div class="panel">
    <div class="step-selector">
      <button class="step-btn" onclick="setStep(0.1)">0.1 mm</button>
      <button class="step-btn" onclick="setStep(1.0)">1 mm</button>
      <button class="step-btn active" onclick="setStep(10.0)">10 mm</button>
      <button class="step-btn" onclick="setStep(50.0)">50 mm</button>
    </div>

    <div class="jog-grid">
      <button class="jog-btn" onclick="jog(-1, 1)">↖</button>
      <button class="jog-btn" onclick="jog(0, 1)">▲</button>
      <button class="jog-btn" onclick="jog(1, 1)">↗</button>
      <button class="jog-btn" onclick="jog(-1, 0)">◀</button>
      <button class="jog-btn center" onclick="jog(0, 0)">●</button>
      <button class="jog-btn" onclick="jog(1, 0)">▶</button>
      <button class="jog-btn" onclick="jog(-1, -1)">↙</button>
      <button class="jog-btn" onclick="jog(0, -1)">▼</button>
      <button class="jog-btn" onclick="jog(1, -1)">↘</button>
    </div>

    <div class="btn-row">
      <button class="act-btn btn-frame" onclick="triggerCmd('frame')">🎯 Frame</button>
      <button class="act-btn btn-laser" onclick="triggerCmd('guide_beam')">🔦 Laser Beam</button>
    </div>
    <div class="btn-row">
      <button class="act-btn btn-home" onclick="triggerCmd('home')">🏠 Home ($H)</button>
      <button class="act-btn btn-unlock" onclick="triggerCmd('unlock')">🔓 Unlock ($X)</button>
    </div>
    <button class="act-btn btn-estop" onclick="triggerCmd('estop')">🛑 EMERGENCY STOP</button>
  </div>

<script>
  let currentStep = 10.0;
  function setStep(val) {
    currentStep = val;
    document.querySelectorAll('.step-btn').forEach(b => {
      b.classList.toggle('active', parseFloat(b.innerText) === val);
    });
  }

  function jog(dirX, dirY) {
    if (dirX === 0 && dirY === 0) return;
    const dx = dirX * currentStep;
    const dy = dirY * currentStep;
    fetch('/api/jog', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({dx: dx, dy: dy})
    });
  }

  function triggerCmd(action) {
    fetch('/api/' + action, { method: 'POST' });
  }

  setInterval(() => {
    fetch('/api/status')
      .then(r => r.json())
      .then(d => {
        const b = document.getElementById('statusBadge');
        b.innerText = (d.state || 'IDLE').toUpperCase();
        b.className = 'badge badge-' + (d.state === 'run' ? 'run' : d.state === 'alarm' ? 'alarm' : 'idle');
        document.getElementById('coordsDisplay').innerText =
          `X: ${(d.x || 0).toFixed(2)} | Y: ${(d.y || 0).toFixed(2)} | Z: ${(d.z || 0).toFixed(2)}`;
      }).catch(() => {});
  }, 1000);
</script>
</body>
</html>
"""


class WebPendantServer:
    """Embedded touch-screen jogger and telemetry server for workshop mobile devices."""

    def __init__(self, port: int = 8088, host: str = "0.0.0.0"):
        self.port = port
        self.host = host
        self.httpd: Optional[http.server.ThreadingHTTPServer] = None
        self.server_thread: Optional[threading.Thread] = None
        self.is_running = False

        # Callback handlers connected to LaserForge machine controller
        self.on_jog: Optional[Callable[[float, float], None]] = None
        self.on_frame: Optional[Callable[[], None]] = None
        self.on_guide_beam: Optional[Callable[[], None]] = None
        self.on_home: Optional[Callable[[], None]] = None
        self.on_unlock: Optional[Callable[[], None]] = None
        self.on_estop: Optional[Callable[[], None]] = None
        self.get_status_cb: Optional[Callable[[], Dict[str, Any]]] = None

    def start(self) -> bool:
        """Starts the background web server thread."""
        if self.is_running:
            return True

        pendant_self = self

        class PendantRequestHandler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass  # Silence stdout logging

            def do_GET(self):
                if self.path == "/" or self.path == "/index.html":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(PENDANT_HTML.encode("utf-8"))
                elif self.path == "/api/status":
                    status = pendant_self.get_status_cb() if pendant_self.get_status_cb else {"state": "Idle", "x": 0.0, "y": 0.0, "z": 0.0}
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps(status).encode("utf-8"))
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_POST(self):
                content_len = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else "{}"
                data = {}
                try:
                    data = json.loads(body)
                except Exception:
                    pass

                if self.path == "/api/jog":
                    dx = float(data.get("dx", 0.0))
                    dy = float(data.get("dy", 0.0))
                    if pendant_self.on_jog:
                        pendant_self.on_jog(dx, dy)
                    self._send_ok()
                elif self.path == "/api/frame":
                    if pendant_self.on_frame:
                        pendant_self.on_frame()
                    self._send_ok()
                elif self.path == "/api/guide_beam":
                    if pendant_self.on_guide_beam:
                        pendant_self.on_guide_beam()
                    self._send_ok()
                elif self.path == "/api/home":
                    if pendant_self.on_home:
                        pendant_self.on_home()
                    self._send_ok()
                elif self.path == "/api/unlock":
                    if pendant_self.on_unlock:
                        pendant_self.on_unlock()
                    self._send_ok()
                elif self.path == "/api/estop":
                    if pendant_self.on_estop:
                        pendant_self.on_estop()
                    self._send_ok()
                else:
                    self.send_response(404)
                    self.end_headers()

            def _send_ok(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"ok"}')

        try:
            self.httpd = http.server.ThreadingHTTPServer((self.host, self.port), PendantRequestHandler)
            self.server_thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
            self.server_thread.start()
            self.is_running = True
            return True
        except Exception as e:
            print(f"Failed to start Web Pendant Server: {e}")
            self.is_running = False
            return False

    def stop(self):
        """Stops the embedded HTTP server cleanly."""
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None
        self.is_running = False

    @staticmethod
    def get_local_ip() -> str:
        """Finds primary local LAN IP address of this machine."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"
