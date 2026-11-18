"""
CivicSense Unified Multi-Model Vision System
Runs 3 AI models concurrently on a single video/camera feed:
  1. Pothole Detection (YOLO11n)
  2. Fire & Smoke Detection (YOLO11n)
  3. Waste Bin Overflow Detection (CLIP model.safetensors)
Sends real-time alert events to ESP32:
  /pothole, /fire, /smoke, /overflow, /normal
"""

import os
import sys

# Ensure UTF-8 output encoding on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import time
import json
import queue
import argparse
import threading
import requests
import cv2

print("\n" + "=" * 60)
print(" 🛡️  CIVICSENSE UNIFIED AI SYSTEM STARTING...")
print(" ⏳ Initializing AI engines (PyTorch & Transformers)...")
print("=" * 60 + "\n")

import torch
import numpy as np
from PIL import Image
from ultralytics import YOLO
from transformers import CLIPProcessor, CLIPModel

# ==============================================================================
# CONFIGURATION DEFAULTS
# ==============================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# State file for real-time frontend and API synchronization
STATE_FILE = os.path.join(BASE_DIR, "civicsense_live_state.json")

def save_live_state(data):
    """Atomically writes current detection telemetry for real-time frontend polling."""
    try:
        tmp_file = STATE_FILE + ".tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp_file, STATE_FILE)
    except Exception:
        pass

# Model Paths
POTHOLE_PATH = os.path.join(BASE_DIR, "runs", "detect", "runs", "pothole_yolo11n", "weights", "best.pt")
if not os.path.exists(POTHOLE_PATH):
    POTHOLE_PATH = os.path.join(BASE_DIR, "best.pt")

FIRE_SMOKE_PATH = os.path.join(BASE_DIR, "mini_project", "runs", "fire_smoke", "weights", "best.pt")
CLIP_DIR = os.path.join(BASE_DIR, "saved_clip_model")
if not os.path.exists(CLIP_DIR):
    CLIP_DIR = os.path.join(BASE_DIR, "Garbahe", "saved_clip_model")

# Thresholds (calibrated for high accuracy & zero false alarms on CPU)
CONF_POTHOLE = 0.58
CONF_FIRE_SMOKE = 0.45
CONF_CLIP_OVERFLOW = 0.42

CLIP_LABELS = [
    "an overflowing waste bin with garbage spilling out",
    "a normal clean or empty waste bin",
    "an indoor room, person, furniture, or office desk without any trash or waste bin",
    "a clean road surface, asphalt, or outdoor street with no garbage"
]

# ==============================================================================
# ASYNC ESP32 CLIENT (Non-blocking background dispatcher)
# ==============================================================================
class ESP32Notifier:
    def __init__(self, esp_ip="192.168.65.33", enabled=True):
        self.esp_ip = esp_ip
        self.enabled = enabled
        self.work_queue = queue.Queue(maxsize=10)
        self.last_status_msg = "Disabled" if not enabled else "Connecting..."
        self.running = True
        self.last_err_print_time = 0

        if self.enabled:
            # Immediate startup check to verify connectivity
            self._test_connection()
            self.worker_thread = threading.Thread(target=self._worker, daemon=True)
            self.worker_thread.start()

    def _test_connection(self):
        url = f"http://{self.esp_ip}/"
        try:
            resp = requests.get(url, timeout=1.2)
            print(f"   📡 ESP32 Connection TEST: ✅ SUCCESS ({url} -> HTTP {resp.status_code})")
            self.last_status_msg = f"Connected ({resp.status_code})"
        except Exception as e:
            print(f"   ⚠️  ESP32 Connection TEST: ❌ FAILED ({url})")
            print(f"      Reason: {e}")
            print(f"      👉 TIP: Check if your PC is connected to the same Wi-Fi and verify the ESP32 IP on its OLED screen!")
            self.last_status_msg = "ESP Unreachable"

    def send(self, endpoint):
        if not self.enabled:
            return
        try:
            # Avoid duplicate flooding in queue
            self.work_queue.put_nowait(endpoint)
        except queue.Full:
            pass

    def _worker(self):
        while self.running:
            try:
                endpoint = self.work_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            url = f"http://{self.esp_ip}/{endpoint.lstrip('/')}"
            try:
                resp = requests.get(url, timeout=0.8)
                self.last_status_msg = f"Sent /{endpoint} ({resp.status_code})"
                print(f"⚡ [ESP32 ACK] Delivered /{endpoint} -> HTTP {resp.status_code} ({resp.text.strip()})")
            except requests.exceptions.RequestException as e:
                self.last_status_msg = f"ESP Offline ({endpoint})"
                now = time.time()
                if now - self.last_err_print_time > 2.0:
                    self.last_err_print_time = now
                    print(f"❌ [ESP32 UNREACHABLE] Could not reach http://{self.esp_ip}/{endpoint.lstrip('/')}")
                    print(f"   Error: {e}")
            finally:
                self.work_queue.task_done()

    def stop(self):
        self.running = False


# ==============================================================================
# CLIP ASYNC INFERENCE WORKER
# ==============================================================================
class AsyncClipWorker:
    """Runs heavy CLIP classification in the background so video stays smooth."""
    def __init__(self, model, processor, device):
        self.model = model
        self.processor = processor
        self.device = device
        self.input_queue = queue.Queue(maxsize=1)
        self.result = {"status": "CHECKING", "conf": 0.0, "is_overflow": False}
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def submit_frame(self, frame_bgr):
        try:
            # Non-blocking replace of latest frame
            if self.input_queue.full():
                try:
                    self.input_queue.get_nowait()
                except queue.Empty:
                    pass
            self.input_queue.put_nowait(frame_bgr.copy())
        except queue.Full:
            pass

    def _run(self):
        while self.running:
            try:
                frame_bgr = self.input_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            try:
                rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
                # Resize to standard 224x224 for CLIP to speed up processing substantially
                pil_img = Image.fromarray(rgb).resize((224, 224))
                inputs = self.processor(text=CLIP_LABELS, images=pil_img, return_tensors="pt", padding=True).to(self.device)
                with torch.no_grad():
                    outputs = self.model(**inputs)
                    probs = outputs.logits_per_image.softmax(dim=1)

                overflow_prob = float(probs[0][0].item())
                clean_prob = float(probs[0][1].item())
                scene_prob = max(float(probs[0][2].item()), float(probs[0][3].item()))

                # True overflow requires:
                # 1. Beating the confidence threshold
                # 2. Winning over clean bin
                # 3. Winning over neutral background non-bin scenes
                is_overflow = (
                    overflow_prob >= CONF_CLIP_OVERFLOW
                    and overflow_prob > clean_prob
                    and overflow_prob > (scene_prob + 0.05)
                )
                status = "OVERFLOW" if is_overflow else "NORMAL"
                conf = overflow_prob if is_overflow else (1.0 - overflow_prob)

                self.result = {
                    "status": status,
                    "conf": conf,
                    "is_overflow": is_overflow,
                    "overflow_prob": round(overflow_prob, 3),
                    "clean_prob": round(clean_prob, 3),
                    "scene_prob": round(scene_prob, 3)
                }
            except Exception as e:
                print(f"[CLIP Worker Error]: {e}")
            finally:
                self.input_queue.task_done()

    def stop(self):
        self.running = False


class ThreadedCamera:
    """
    Continuously grabs the latest frame from a camera stream in a background thread.
    This eliminates OpenCV internal FIFO buffer lag, ensuring 0ms latency on CPU.
    """
    def __init__(self, src):
        self.cap = cv2.VideoCapture(src)
        self.grabbed, self.frame = self.cap.read()
        self.running = True
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self._update, daemon=True)
        self.thread.start()

    def _update(self):
        while self.running:
            grabbed, frame = self.cap.read()
            if not grabbed:
                self.running = False
                break
            with self.lock:
                self.grabbed = grabbed
                self.frame = frame
            time.sleep(0.005)

    def read(self):
        with self.lock:
            if not self.grabbed or self.frame is None:
                return False, None
            return True, self.frame.copy()

    def isOpened(self):
        return self.cap.isOpened()

    def get(self, prop_id):
        return self.cap.get(prop_id)

    def release(self):
        self.running = False
        self.cap.release()


def deduplicate_incidents(raw_incidents, fps=25.0):
    if not raw_incidents:
        return []
    grouped = []
    for inc in raw_incidents:
        matched = False
        for g in grouped:
            if g["incident_type"] == inc["incident_type"]:
                if abs(inc["timestamp_seconds"] - g["timestamp_seconds"]) <= 3.0:
                    g["count"] += 1
                    if inc["confidence"] > g["confidence"]:
                        g["confidence"] = inc["confidence"]
                        if inc.get("bbox"):
                            g["bbox"] = inc["bbox"]
                    matched = True
                    break
        if not matched:
            grouped.append({
                "incident_type": inc["incident_type"],
                "confidence": round(float(inc["confidence"]), 4),
                "bbox": inc.get("bbox"),
                "timestamp_seconds": round(float(inc["timestamp_seconds"]), 2),
                "count": 1
            })
    return grouped


# ==============================================================================
# MAIN APPLICATION
# ==============================================================================
def run_unified_system(
    source="0",
    esp_ip="192.168.65.33",
    enable_esp=True,
    headless=False,
    save_output=None,
    json_output=None,
    max_frames=None
):
    print("=" * 60)
    print(" 🛡️  CIVICSENSE UNIFIED AI SYSTEM INITIALIZING...")
    print("=" * 60)

    # 1. Load Pothole Model
    print(f"📦 Loading Pothole Model: {POTHOLE_PATH}")
    if not os.path.exists(POTHOLE_PATH):
        print(f"❌ Error: Model not found at {POTHOLE_PATH}")
        return []
    pothole_model = YOLO(POTHOLE_PATH)
    print("   ✅ Pothole model loaded.")

    # 2. Load Fire & Smoke Model
    print(f"📦 Loading Fire & Smoke Model: {FIRE_SMOKE_PATH}")
    if not os.path.exists(FIRE_SMOKE_PATH):
        print(f"❌ Error: Model not found at {FIRE_SMOKE_PATH}")
        return []
    fire_smoke_model = YOLO(FIRE_SMOKE_PATH)
    print("   ✅ Fire & Smoke model loaded.")

    # 3. Load CLIP Waste Model
    print(f"📦 Loading CLIP model from: {CLIP_DIR}")
    if not os.path.exists(CLIP_DIR):
        print(f"❌ Error: CLIP folder not found at {CLIP_DIR}")
        return []
    device = "cuda" if torch.cuda.is_available() else "cpu"
    clip_model = CLIPModel.from_pretrained(CLIP_DIR, local_files_only=True).to(device)
    clip_proc = CLIPProcessor.from_pretrained(CLIP_DIR, local_files_only=True)
    print(f"   ✅ CLIP model loaded on {device}.")

    # Start Async CLIP Worker
    clip_worker = AsyncClipWorker(clip_model, clip_proc, device)

    # Start ESP32 Notifier
    notifier = ESP32Notifier(esp_ip=esp_ip, enabled=enable_esp)
    print(f"📡 ESP32 Notifier: {'ENABLED -> http://' + esp_ip if enable_esp else 'DISABLED'}")

    # 4. Open Video Source
    try:
        source_idx = int(source)
    except (ValueError, TypeError):
        source_idx = source

    is_live_cam = (str(source) in ["0", "1", "2"] or source_idx in [0, 1, 2])
    print(f"\n🎥 Opening Video Source: {source} (Live Stream: {is_live_cam})...")
    if is_live_cam:
        cap = ThreadedCamera(source_idx)
    else:
        cap = cv2.VideoCapture(source_idx)

    if not cap.isOpened():
        print(f"❌ Failed to open video source: {source}")
        return []

    frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 640
    frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 480
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0

    window_name = "CivicSense Unified System (Pothole | Fire | Waste)"
    if not headless:
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(window_name, min(1280, max(frame_w, 800)), min(720, max(frame_h, 600)))

    out_writer = None
    if save_output:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(save_output)), exist_ok=True)
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out_writer = cv2.VideoWriter(save_output, fourcc, fps, (frame_w, frame_h))
            print(f"📹 Recording output video to: {save_output}")
        except Exception as e:
            print(f"⚠️ Could not initialize VideoWriter for {save_output}: {e}")

    print("\n" + "=" * 60)
    print(" 🚀 RUNNING ALL 3 MODELS CONCURRENTLY (CPU-OPTIMIZED)")
    if not headless:
        print(" ⌨️  Controls:")
        print("    [Q] or [ESC] - Exit")
        print("    [P]         - Pause / Resume")
        print("    [S]         - Save snapshot")
        print("    [E]         - Toggle ESP32 signals ON/OFF")
    print("=" * 60 + "\n")

    # State tracking
    state = {
        "pothole": False,
        "fire": False,
        "smoke": False,
        "overflow": False
    }

    # Debounce counters (require >= 2 consecutive frames to prevent single-frame flickering)
    consec = {
        "pothole": 0,
        "fire": 0,
        "smoke": 0,
        "overflow": 0
    }

    # Distinct incident tracking with cooldown to prevent dashboard count explosion
    confirmed_incidents = []
    last_incident_log_time = {
        "POTHOLE": 0.0,
        "FIRE": 0.0,
        "SMOKE": 0.0,
        "WASTE_BIN_OVERFLOW": 0.0
    }
    INCIDENT_COOLDOWN_SEC = 5.0

    # Caches for alternating inference
    last_pothole_boxes = []
    last_pothole_detected = False
    last_fire_boxes = []
    last_fire_detected = False
    last_smoke_detected = False

    prev_time = time.time()
    last_alert_sent_time = 0
    last_hazard_seen_time = 0
    last_state_save_time = 0
    paused = False
    frame_idx = 0
    snapshot_idx = 0

    try:
        while True:
            if not paused:
                ret, frame = cap.read()
                if not ret or frame is None:
                    if not is_live_cam:
                        print("🏁 Video stream ended.")
                        break
                    time.sleep(0.01)
                    continue

                frame_idx += 1
                curr_offset = round(frame_idx / fps, 2)

                # Submit frame to background CLIP worker every 4 frames
                if frame_idx % 4 == 0 or frame_idx == 1:
                    clip_worker.submit_frame(frame)

                # -------------------------------------------------------------
                # 1 & 2. YOLO Inference (imgsz=480 for 2x CPU speedup)
                # On live camera: alternate pothole & fire/smoke to maintain high FPS
                # -------------------------------------------------------------
                do_pothole = (not is_live_cam) or (frame_idx % 2 == 0)
                do_fire_smoke = (not is_live_cam) or (frame_idx % 2 == 1)

                fh, fw = frame.shape[:2]

                if do_pothole:
                    p_res = pothole_model.predict(frame, conf=CONF_POTHOLE, imgsz=480, verbose=False)[0]
                    last_pothole_boxes = []
                    for box in p_res.boxes:
                        conf = float(box.conf[0])
                        xyxy = [int(v) for v in box.xyxy[0].tolist()]
                        bx1, by1, bx2, by2 = xyxy
                        bw = bx2 - bx1
                        bh = by2 - by1
                        bcy = (by1 + by2) / 2.0
                        area_ratio = (bw * bh) / float(fw * fh)

                        # False positive rejection filters:
                        # 1. Road surface ROI: reject sky, ceiling, trees, upper horizon
                        if by2 < fh * 0.35 or bcy < fh * 0.30:
                            continue
                        # 2. Min area: reject tiny speck noise (<0.2% of frame)
                        if area_ratio < 0.002:
                            continue
                        # 3. Aspect ratio: reject ultra-vertical strips (poles/trees/seams)
                        if (bh / max(1, bw)) > 2.8:
                            continue

                        last_pothole_boxes.append((xyxy, conf))
                    last_pothole_detected = len(last_pothole_boxes) > 0

                if do_fire_smoke:
                    fs_res = fire_smoke_model.predict(frame, conf=CONF_FIRE_SMOKE, imgsz=480, verbose=False)[0]
                    last_fire_boxes = []
                    has_f = False
                    has_s = False
                    for box in fs_res.boxes:
                        cls_id = int(box.cls[0])
                        name = fire_smoke_model.names.get(cls_id, "").lower()
                        conf = float(box.conf[0])
                        xyxy = [int(v) for v in box.xyxy[0].tolist()]
                        if "fire" in name:
                            has_f = True
                            last_fire_boxes.append((xyxy, conf, "FIRE"))
                        elif "smoke" in name:
                            has_s = True
                            last_fire_boxes.append((xyxy, conf, "SMOKE"))
                    last_fire_detected = has_f
                    last_smoke_detected = has_s

                # -------------------------------------------------------------
                # 3. Waste Bin Overflow (CLIP Async Result)
                # -------------------------------------------------------------
                clip_data = clip_worker.result
                raw_overflow = clip_data.get("is_overflow", False)
                clip_status = clip_data.get("status", "NORMAL")
                clip_conf = clip_data.get("conf", 0.0)

                # -------------------------------------------------------------
                # 4. Debounce & Stability Verification (Only update on active inference)
                # -------------------------------------------------------------
                if do_pothole:
                    consec["pothole"] = (consec["pothole"] + 1) if last_pothole_detected else max(0, consec["pothole"] - 1)
                if do_fire_smoke:
                    consec["fire"] = (consec["fire"] + 1) if last_fire_detected else max(0, consec["fire"] - 1)
                    consec["smoke"] = (consec["smoke"] + 1) if last_smoke_detected else max(0, consec["smoke"] - 1)
                consec["overflow"] = (consec["overflow"] + 1) if raw_overflow else max(0, consec["overflow"] - 1)

                pothole_detected = consec["pothole"] >= 3
                fire_detected = consec["fire"] >= 3
                smoke_detected = consec["smoke"] >= 3
                overflow_detected = consec["overflow"] >= 2
                pothole_count = len(last_pothole_boxes) if pothole_detected else 0

                now_t = time.time()

                # Log confirmed distinct incidents with cooldown (prevents dashboard counter explosion)
                if pothole_detected and (now_t - last_incident_log_time["POTHOLE"] > INCIDENT_COOLDOWN_SEC):
                    best_box, best_c = (last_pothole_boxes[0] if last_pothole_boxes else ([0, 0, 0, 0], CONF_POTHOLE))
                    confirmed_incidents.append({
                        "incident_type": "POTHOLE",
                        "confidence": best_c,
                        "bbox": best_box,
                        "timestamp_seconds": curr_offset
                    })
                    last_incident_log_time["POTHOLE"] = now_t
                    print(f"📌 [INCIDENT LOGGED] Pothole Detected (Confidence: {best_c:.2f})")

                if fire_detected and (now_t - last_incident_log_time["FIRE"] > INCIDENT_COOLDOWN_SEC):
                    f_boxes = [b for b in last_fire_boxes if b[2] == "FIRE"]
                    f_box, f_c = (f_boxes[0][0], f_boxes[0][1]) if f_boxes else ([0, 0, 0, 0], CONF_FIRE_SMOKE)
                    confirmed_incidents.append({
                        "incident_type": "FIRE",
                        "confidence": f_c,
                        "bbox": f_box,
                        "timestamp_seconds": curr_offset
                    })
                    last_incident_log_time["FIRE"] = now_t
                    print(f"📌 [INCIDENT LOGGED] Fire Outbreak (Confidence: {f_c:.2f})")

                if smoke_detected and (now_t - last_incident_log_time["SMOKE"] > INCIDENT_COOLDOWN_SEC):
                    s_boxes = [b for b in last_fire_boxes if b[2] == "SMOKE"]
                    s_box, s_c = (s_boxes[0][0], s_boxes[0][1]) if s_boxes else ([0, 0, 0, 0], CONF_FIRE_SMOKE)
                    confirmed_incidents.append({
                        "incident_type": "SMOKE",
                        "confidence": s_c,
                        "bbox": s_box,
                        "timestamp_seconds": curr_offset
                    })
                    last_incident_log_time["SMOKE"] = now_t
                    print(f"📌 [INCIDENT LOGGED] Smoke Cloud (Confidence: {s_c:.2f})")

                if overflow_detected and (now_t - last_incident_log_time["WASTE_BIN_OVERFLOW"] > INCIDENT_COOLDOWN_SEC):
                    confirmed_incidents.append({
                        "incident_type": "WASTE_BIN_OVERFLOW",
                        "confidence": clip_conf,
                        "bbox": [int(frame_w * 0.1), int(frame_h * 0.1), int(frame_w * 0.9), int(frame_h * 0.9)],
                        "timestamp_seconds": curr_offset
                    })
                    last_incident_log_time["WASTE_BIN_OVERFLOW"] = now_t
                    print(f"📌 [INCIDENT LOGGED] Waste Bin Overflow (Confidence: {clip_conf:.2f})")

                # -------------------------------------------------------------
                # 5. Trigger ESP32 Endpoints with Hysteresis & Debounce
                # -------------------------------------------------------------
                hazard_active = pothole_detected or fire_detected or smoke_detected or overflow_detected
                if hazard_active:
                    last_hazard_seen_time = now_t

                previously_alert = any([state["pothole"], state["fire"], state["smoke"], state["overflow"]])

                primary_hazard = None
                if fire_detected:
                    primary_hazard = "fire"
                elif smoke_detected:
                    primary_hazard = "smoke"
                elif pothole_detected:
                    primary_hazard = "pothole"
                elif overflow_detected:
                    primary_hazard = "overflow"

                # Send alert if newly triggered, OR keepalive heartbeat every 1.2s while hazard persists
                if hazard_active and primary_hazard:
                    is_new_alert = not previously_alert or not state.get(primary_hazard, False)
                    time_since_last_alert = now_t - last_alert_sent_time
                    if is_new_alert or time_since_last_alert > 1.2:
                        print(f"🚨 [HAZARD ACTIVE] {primary_hazard.upper()} -> notifying ESP32 (/{primary_hazard})")
                        notifier.send(primary_hazard)
                        last_alert_sent_time = now_t
                elif previously_alert and not hazard_active:
                    # Require 1.2s of clean frames before silencing buzzer, stopping rapid on/off flapping!
                    if (now_t - last_hazard_seen_time) > 1.2:
                        print("✅ [ALL CLEAR] Hazards gone -> sending /normal (silence buzzer & restore green LED)")
                        notifier.send("normal")
                        last_alert_sent_time = 0
                        state["pothole"] = False
                        state["fire"] = False
                        state["smoke"] = False
                        state["overflow"] = False

                if hazard_active:
                    state["pothole"] = pothole_detected
                    state["fire"] = fire_detected
                    state["smoke"] = smoke_detected
                    state["overflow"] = overflow_detected

                # -------------------------------------------------------------
                # 6. Draw Annotations on Frame
                # -------------------------------------------------------------
                display_frame = frame.copy()

                # Draw Pothole Bounding Boxes
                if pothole_detected:
                    for xyxy, conf in last_pothole_boxes:
                        x1, y1, x2, y2 = xyxy
                        cv2.rectangle(display_frame, (x1, y1), (x2, y2), (0, 255, 255), 2)
                        cv2.putText(display_frame, f"Pothole {conf:.2f}", (x1, max(y1 - 8, 15)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)

                # Draw Fire / Smoke Bounding Boxes
                if fire_detected or smoke_detected:
                    for xyxy, conf, cls_name in last_fire_boxes:
                        x1, y1, x2, y2 = xyxy
                        box_color = (0, 0, 255) if cls_name == "FIRE" else (0, 140, 255)
                        cv2.rectangle(display_frame, (x1, y1), (x2, y2), box_color, 2)
                        cv2.putText(display_frame, f"{cls_name} {conf:.2f}", (x1, max(y1 - 8, 15)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, box_color, 2)

                # -------------------------------------------------------------
                # 7. Professional HUD Top Bar
                # -------------------------------------------------------------
                h, w = display_frame.shape[:2]
                hud_h = 75

                # Semi-transparent dark header overlay
                overlay = display_frame.copy()
                cv2.rectangle(overlay, (0, 0), (w, hud_h), (18, 18, 18), -1)
                cv2.addWeighted(overlay, 0.75, display_frame, 0.25, 0, display_frame)

                # Calculate FPS
                curr_t = time.time()
                fps_calc = 1.0 / (curr_t - prev_time) if (curr_t - prev_time) > 0 else 0
                prev_time = curr_t

                # Pothole Status Badge
                p_text = f"POTHOLE: {pothole_count} FOUND" if pothole_detected else "POTHOLE: CLEAR"
                p_color = (0, 0, 255) if pothole_detected else (0, 255, 0)
                cv2.putText(display_frame, p_text, (15, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.65, p_color, 2)

                # Fire & Smoke Status Badge
                if fire_detected:
                    fs_text, fs_color = "FIRE DETECTED!", (0, 0, 255)
                elif smoke_detected:
                    fs_text, fs_color = "SMOKE DETECTED!", (0, 140, 255)
                else:
                    fs_text, fs_color = "FIRE/SMOKE: CLEAR", (0, 255, 0)
                cv2.putText(display_frame, fs_text, (260, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.65, fs_color, 2)

                # Waste Bin Overflow Badge
                bin_text = f"BIN: {clip_status} ({clip_conf*100:.0f}%)"
                bin_color = (0, 0, 255) if overflow_detected else (0, 255, 0)
                cv2.putText(display_frame, bin_text, (520, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.65, bin_color, 2)

                # Line 2: FPS & ESP Status
                esp_str = f"ESP32: {notifier.last_status_msg}"
                cv2.putText(display_frame, f"FPS: {fps_calc:.1f} | {esp_str}", (15, 58),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1, cv2.LINE_AA)

                if out_writer:
                    out_writer.write(display_frame)

                # Real-time state synchronization for Frontend cards
                now_t = time.time()
                if (now_t - last_state_save_time) >= 0.1:
                    last_state_save_time = now_t

                    p_conf = float(last_pothole_boxes[0][1]) if last_pothole_boxes and pothole_detected else 0.0
                    p_boxes = [[*b[0], round(b[1], 3)] for b in last_pothole_boxes] if pothole_detected else []

                    fs_conf = 0.0
                    fs_boxes = []
                    if fire_detected or smoke_detected:
                        for b in last_fire_boxes:
                            if b[1] > fs_conf:
                                fs_conf = b[1]
                            fs_boxes.append([*b[0], round(b[1], 3), b[2]])

                    live_state_data = {
                        "running": True,
                        "timestamp": now_t,
                        "source": str(source),
                        "fps": round(fps_calc, 1),
                        "frame_idx": frame_idx,
                        "primary_hazard": primary_hazard,
                        "pothole": {
                            "detected": pothole_detected,
                            "count": pothole_count,
                            "confidence": round(p_conf, 3),
                            "status": "POTHOLE_DETECTED" if pothole_detected else "CLEAR",
                            "bboxes": p_boxes,
                        },
                        "fire_smoke": {
                            "detected": fire_detected or smoke_detected,
                            "fire_detected": fire_detected,
                            "smoke_detected": smoke_detected,
                            "confidence": round(fs_conf, 3),
                            "status": "FIRE_ALERT" if fire_detected else ("SMOKE_ALERT" if smoke_detected else "CLEAR"),
                            "bboxes": fs_boxes,
                        },
                        "overflow": {
                            "detected": overflow_detected,
                            "status": clip_status,
                            "confidence": round(float(clip_conf), 3),
                            "label": "Overflowing waste bin with garbage spilling" if overflow_detected else "Clean / normal waste bin",
                        },
                        "esp32": {
                            "enabled": notifier.enabled,
                            "ip": esp_ip,
                            "last_msg": notifier.last_status_msg,
                            "active_signal": primary_hazard or "normal"
                        },
                        "total_incidents": len(confirmed_incidents),
                        "recent_incidents": confirmed_incidents[-10:] if confirmed_incidents else []
                    }
                    save_live_state(live_state_data)

            if not headless:
                cv2.imshow(window_name, display_frame)

                # Keyboard controls
                key = cv2.waitKey(1) & 0xFF
                if key in (ord('q'), 27):
                    print("⏹️ Stopped by user.")
                    break
                elif key == ord('p'):
                    paused = not paused
                    print("⏸️ Paused" if paused else "▶️ Resumed")
                elif key == ord('s'):
                    snapshot_idx += 1
                    fn = f"civicsense_snapshot_{snapshot_idx}_{int(time.time())}.jpg"
                    cv2.imwrite(fn, display_frame)
                    print(f"📸 Snapshot saved to: {fn}")
                elif key == ord('e'):
                    notifier.enabled = not notifier.enabled
                    notifier.last_status_msg = "Enabled" if notifier.enabled else "Disabled"
                    print(f"📡 ESP32 Notifier toggled: {notifier.enabled}")
            else:
                if max_frames and frame_idx >= max_frames:
                    print(f"Reached max frames limit: {max_frames}")
                    break

    finally:
        # Save STOPPED state for frontend cards
        save_live_state({
            "running": False,
            "status": "STOPPED",
            "timestamp": time.time(),
            "source": str(source),
            "fps": 0.0,
            "frame_idx": frame_idx,
            "primary_hazard": None,
            "pothole": {
                "detected": False,
                "count": 0,
                "confidence": 0.0,
                "status": "STANDBY",
                "bboxes": []
            },
            "fire_smoke": {
                "detected": False,
                "fire_detected": False,
                "smoke_detected": False,
                "confidence": 0.0,
                "status": "STANDBY",
                "bboxes": []
            },
            "overflow": {
                "detected": False,
                "status": "STANDBY",
                "confidence": 0.0,
                "label": "Engine Standby"
            },
            "esp32": {
                "enabled": False,
                "ip": esp_ip,
                "last_msg": "Engine Stopped",
                "active_signal": "none"
            },
            "total_incidents": len(confirmed_incidents),
            "recent_incidents": confirmed_incidents[-10:] if confirmed_incidents else []
        })

        # Cleanup
        cap.release()
        if out_writer:
            out_writer.release()
        clip_worker.stop()
        notifier.stop()
        if not headless:
            try:
                cv2.destroyAllWindows()
            except Exception:
                pass
        print("✅ Shutdown complete. All resources safely released.")

    # Deduplicate and return findings
    summary = deduplicate_incidents(confirmed_incidents, fps=fps)
    print(f"📊 Analysis complete: {len(summary)} distinct incident event(s) registered.")

    if json_output:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(json_output)), exist_ok=True)
            with open(json_output, "w", encoding="utf-8") as jf:
                json.dump(summary, jf, indent=2)
            print(f"💾 JSON report saved to: {json_output}")
        except Exception as e:
            print(f"Could not save JSON output: {e}")

    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CivicSense: Run Pothole, Fire/Smoke & Waste Overflow with ESP32 alerts")
    parser.add_argument("--source", type=str, default="0", help="Webcam (0), video file path, or ESP32-CAM stream URL")
    parser.add_argument("--esp-ip", type=str, default="192.168.206.33", help="ESP32 IP address (default: 192.168.206.33)")
    parser.add_argument("--no-esp", action="store_true", help="Disable sending HTTP requests to ESP32 (offline testing)")
    parser.add_argument("--headless", action="store_true", help="Run without OpenCV GUI window")
    parser.add_argument("--save-output", type=str, default=None, help="Save annotated output video to path")
    parser.add_argument("--json-output", type=str, default=None, help="Save detection JSON results to path")
    parser.add_argument("--max-frames", type=int, default=None, help="Max frames to process")
    args = parser.parse_args()

    run_unified_system(
        source=args.source,
        esp_ip=args.esp_ip,
        enable_esp=not args.no_esp,
        headless=args.headless,
        save_output=args.save_output,
        json_output=args.json_output,
        max_frames=args.max_frames
    )

