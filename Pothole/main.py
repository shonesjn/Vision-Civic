import cv2
import time
import os
import sys

# Ensure UTF-8 output encoding on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from ultralytics import YOLO

# ==========================================
# CONFIGURATION
# ==========================================
# Priority: best.pt in runs directory, fallback to root best.pt
RUNS_MODEL_PATH = os.path.join("runs", "detect", "runs", "pothole_yolo11n", "weights", "best.pt")
MODEL_PATH = RUNS_MODEL_PATH if os.path.exists(RUNS_MODEL_PATH) else "best.pt"
# Using the road video in the project directory
SOURCE = "Watch Video_ Terrible potholes in Rangoon Road.mp4"
CONF_THRESHOLD = 0.30  # Confidence threshold for pothole detection
IMG_SIZE = 640        # Inference resolution
SAVE_OUTPUT = True    # Save the annotated video to disk
OUTPUT_PATH = "pothole_detection_output.mp4"
# ==========================================


def main():
    if not os.path.exists(MODEL_PATH):
        print(f"❌ Error: Model file '{MODEL_PATH}' not found in the current directory.")
        return

    if isinstance(SOURCE, str) and not os.path.exists(SOURCE):
        print(f"❌ Error: Video file '{SOURCE}' not found.")
        return

    print(f"🚀 Loading trained model: {MODEL_PATH}...")
    model = YOLO(MODEL_PATH)
    print("✅ Model loaded successfully!")

    print(f"🎥 Opening video source: {SOURCE}...")
    cap = cv2.VideoCapture(SOURCE)

    if not cap.isOpened():
        print(f"❌ Error: Could not open video source: {SOURCE}")
        return

    # Video properties
    frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps_input = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    print(f"ℹ️ Video Info: {frame_width}x{frame_height} @ {fps_input:.1f} FPS ({total_frames} total frames)")

    video_writer = None
    if SAVE_OUTPUT:
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        video_writer = cv2.VideoWriter(OUTPUT_PATH, fourcc, fps_input, (frame_width, frame_height))
        print(f"💾 Saving annotated output to: {OUTPUT_PATH}")

    # Set up resizable display window
    window_name = "Pothole Detection - Video Playback"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, min(1280, frame_width), min(720, frame_height))

    print("\n" + "=" * 50)
    print(" 🚗 RUNNING POTHOLE DETECTION ON VIDEO")
    print(" ⌨️ Controls:")
    print("    [Q] / [ESC] - Exit")
    print("    [P]         - Pause / Resume")
    print("    [S]         - Save snapshot of current frame")
    print("=" * 50 + "\n")

    prev_time = time.time()
    paused = False
    screenshot_counter = 0
    frame_idx = 0

    while True:
        if not paused:
            ret, frame = cap.read()
            if not ret:
                print("🏁 Finished processing video!")
                break

            frame_idx += 1

            # 1. Run YOLO inference
            results = model.predict(frame, conf=CONF_THRESHOLD, imgsz=IMG_SIZE, verbose=False)
            result = results[0]

            # 2. Get annotated frame with bounding boxes
            annotated_frame = result.plot()

            # 3. Count detected potholes
            pothole_count = len(result.boxes)

            # 4. Calculate FPS
            curr_time = time.time()
            fps = 1.0 / (curr_time - prev_time) if (curr_time - prev_time) > 0 else 0
            prev_time = curr_time

            # 5. Draw HUD Dashboard (Overlay UI)
            overlay = annotated_frame.copy()
            cv2.rectangle(overlay, (0, 0), (frame_width, 60), (20, 20, 20), -1)
            cv2.addWeighted(overlay, 0.65, annotated_frame, 0.35, 0, annotated_frame)

            # Frame progress and FPS
            progress_str = f"Frame {frame_idx}/{total_frames}" if total_frames > 0 else f"Frame {frame_idx}"
            cv2.putText(
                annotated_frame,
                f"FPS: {fps:.1f} | {progress_str}",
                (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.75,
                (0, 255, 0),
                2,
                cv2.LINE_AA,
            )

            # Status Badge
            if pothole_count > 0:
                badge_text = f"WARNING: {pothole_count} POTHOLE{'S' if pothole_count > 1 else ''} DETECTED!"
                cv2.putText(
                    annotated_frame,
                    badge_text,
                    (frame_width - 520, 40),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.75,
                    (0, 0, 255),
                    2,
                    cv2.LINE_AA,
                )
            else:
                cv2.putText(
                    annotated_frame,
                    "ROAD STATUS: CLEAR",
                    (frame_width - 380, 40),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.75,
                    (0, 255, 0),
                    2,
                    cv2.LINE_AA,
                )

            # Save frame to output video if enabled
            if video_writer:
                video_writer.write(annotated_frame)

        # Display window
        cv2.imshow(window_name, annotated_frame)

        # Handle keyboard inputs
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q") or key == 27:  # 'q' or ESC
            print("⏹️ Stopped by user.")
            break
        elif key == ord("p"):
            paused = not paused
            print("⏸️ Paused" if paused else "▶️ Resumed")
        elif key == ord("s"):
            screenshot_counter += 1
            filename = f"pothole_snapshot_{screenshot_counter}_{int(time.time())}.jpg"
            cv2.imwrite(filename, annotated_frame)
            print(f"📸 Snapshot saved to: {filename}")

    # Cleanup
    cap.release()
    if video_writer:
        video_writer.release()
    cv2.destroyAllWindows()
    print("✅ Detection complete. Resources released.")
    if SAVE_OUTPUT:
        print(f"🎉 Output video saved to: {os.path.abspath(OUTPUT_PATH)}")


if __name__ == "__main__":
    main()
