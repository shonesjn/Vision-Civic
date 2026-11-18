"""
CivicSense ESP32 Hardware Emulator / Mock Server
Emulates the exact behavior and endpoints of esp32_civicsense.ino:
  - /pothole
  - /fire
  - /smoke
  - /overflow
  - /normal
  - /status
Displays real-time hardware status: [BUZZER] [RED LED] [GREEN LED]
"""

import sys
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
import json

# Ensure UTF-8 output encoding on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

class ESP32State:
    hazard = "NONE"
    buzzer = False
    red_led = False
    green_led = True
    last_alert_time = 0
    ALERT_TIMEOUT = 2.0  # seconds

state = ESP32State()

def print_hardware_status(event_msg=""):
    buzzer_str = "🔊 [BUZZER: ON ]" if state.buzzer else "🔇 [BUZZER: OFF]"
    red_str = "🔴 [RED LED: ON ]" if state.red_led else "⚪ [RED LED: OFF]"
    green_str = "🟢 [GREEN LED: ON ]" if state.green_led else "⚪ [GREEN LED: OFF]"
    hazard_str = f"⚠️ Hazard: {state.hazard:<8}"
    
    print(f"\r{buzzer_str}  {red_str}  {green_str}  |  {hazard_str}  | {event_msg}")

class ESP32Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Suppress default server access logs to keep terminal display clean
        pass

    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/")
        if not path:
            path = "/"

        if path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"CivicSense ESP32 Online (Simulated)")
            return

        if path in ["/pothole", "/fire", "/smoke", "/overflow"]:
            hazard_type = path.replace("/", "").upper()
            state.hazard = hazard_type
            state.buzzer = True
            state.red_led = True
            state.green_led = False
            state.last_alert_time = time.time()
            
            print_hardware_status(f"🚨 ALERT TRIGGERED: {hazard_type}")
            
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(f"OK_{hazard_type}".encode())
            return

        if path == "/normal":
            state.hazard = "NONE"
            state.buzzer = False
            state.red_led = False
            state.green_led = True
            
            print_hardware_status("✅ ALL CLEAR: Safe state restored")
            
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK_NORMAL")
            return

        if path == "/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            resp = json.dumps({
                "hazard": state.hazard,
                "buzzer": state.buzzer,
                "red_led": state.red_led,
                "green_led": state.green_led,
                "simulated": True
            })
            self.wfile.write(resp.encode())
            return

        self.send_response(404)
        self.end_headers()

def run_server(port=80):
    try:
        server = HTTPServer(("0.0.0.0", port), ESP32Handler)
    except PermissionError:
        # Port 80 might require admin rights on some Windows setups, fallback to 8088
        port = 8088
        server = HTTPServer(("0.0.0.0", port), ESP32Handler)

    print("=" * 65)
    print(f" 🛡️  CIVICSENSE ESP32 SIMULATOR LISTENING ON PORT {port}")
    print(" Emulating ESP32 endpoints (/pothole, /fire, /smoke, /overflow, /normal)")
    print("=" * 65)
    print_hardware_status("Initialized & Ready (Initial: Normal Safe)")

    server.timeout = 0.5
    try:
        while True:
            server.handle_request()
            # Watchdog auto-silence
            if state.buzzer and (time.time() - state.last_alert_time > state.ALERT_TIMEOUT):
                state.hazard = "NONE"
                state.buzzer = False
                state.red_led = False
                state.green_led = True
                print_hardware_status("⏱️ Watchdog: Hazard cleared after timeout")
    except KeyboardInterrupt:
        print("\nStopping simulated ESP32 server...")
    finally:
        server.server_close()

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 80
    run_server(port)
