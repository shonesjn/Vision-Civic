import os
from ultralytics import YOLO
import requests
import cv2
import time

# =========================
# SETTINGS
# =========================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

RUNS_MODEL = os.path.join(BASE_DIR, "runs", "detect", "runs", "pothole_yolo11n", "weights", "best.pt")
MODEL_PATH = RUNS_MODEL if os.path.exists(RUNS_MODEL) else os.path.join(BASE_DIR, "best.pt")

# Fallback to existing sample video if pothole_video.mp4 is not present
SAMPLE_VIDEO = os.path.join(BASE_DIR, "Watch Video_ Terrible potholes in Rangoon Road.mp4")
VIDEO_PATH = os.path.join(BASE_DIR, "pothole_video.mp4")
if not os.path.exists(VIDEO_PATH):
    VIDEO_PATH = SAMPLE_VIDEO

ESP32_IP = "192.168.206.33"
CONFIDENCE_THRESHOLD = 0.58

# =========================
# LOAD MODEL
# =========================

print(f"Loading model from: {MODEL_PATH}...")
if not os.path.exists(MODEL_PATH):
    print(f"ERROR: Model file not found at {MODEL_PATH}")
    exit()

model = YOLO(MODEL_PATH)
print("Model loaded successfully.")

# =========================
# OPEN VIDEO
# =========================

print(f"Opening video source: {VIDEO_PATH}...")
cap = cv2.VideoCapture(VIDEO_PATH)

if not cap.isOpened():
    print(f"ERROR: Could not open video at '{VIDEO_PATH}'.")
    exit()

print("Video opened successfully.")

# Keep track of current ESP32 state and debounce
pothole_state = False
consec_detections = 0

# =========================
# PROCESS VIDEO
# =========================

while True:
    ret, frame = cap.read()

    if not ret:
        print("Video finished.")
        break

    fh, fw = frame.shape[:2]

    # Run YOLO detection
    results = model(frame, conf=CONFIDENCE_THRESHOLD, verbose=False)
    valid_boxes = []

    for box in results[0].boxes:
        conf = float(box.conf[0])
        xyxy = [int(v) for v in box.xyxy[0].tolist()]
        bx1, by1, bx2, by2 = xyxy
        bw = bx2 - bx1
        bh = by2 - by1
        bcy = (by1 + by2) / 2.0
        area_ratio = (bw * bh) / float(fw * fh)

        # Filter out sky/horizon/ceiling, tiny specks, vertical strips
        if by2 < fh * 0.35 or bcy < fh * 0.30:
            continue
        if area_ratio < 0.002:
            continue
        if (bh / max(1, bw)) > 2.8:
            continue

        valid_boxes.append((xyxy, conf))

    raw_found = len(valid_boxes) > 0
    if raw_found:
        consec_detections += 1
    else:
        consec_detections = max(0, consec_detections - 1)

    pothole_found = consec_detections >= 3

    if pothole_found:
        for xyxy, confidence in valid_boxes:
            print(f"Pothole confirmed | Confidence: {confidence:.2f}")

    # =========================
    # SEND SIGNAL ONLY WHEN STATE CHANGES
    # =========================

    if pothole_found and not pothole_state:
        pothole_state = True
        try:
            response = requests.get(
                f"http://{ESP32_IP}/pothole",
                timeout=0.5
            )
            print("ESP32:", response.text)
        except requests.exceptions.RequestException as e:
            print("ESP32 connection error:", e)

    elif not pothole_found and pothole_state:
        pothole_state = False
        try:
            response = requests.get(
                f"http://{ESP32_IP}/normal",
                timeout=0.5
            )
            print("ESP32:", response.text)
        except requests.exceptions.RequestException as e:
            print("ESP32 connection error:", e)

    # =========================
    # DISPLAY DETECTION
    # =========================

    annotated_frame = results[0].plot()
    cv2.imshow("CivicSense - Pothole Detection", annotated_frame)

    # Press Q or ESC to stop
    key = cv2.waitKey(1) & 0xFF
    if key == ord("q") or key == 27:
        break

# =========================
# CLEANUP
# =========================

cap.release()
cv2.destroyAllWindows()

# Make sure LED is OFF at the end
try:
    requests.get(
        f"http://{ESP32_IP}/normal",
        timeout=0.5
    )
except:
    pass

print("CivicSense detection stopped.")
