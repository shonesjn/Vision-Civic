import os
import cv2
import torch
from PIL import Image
from transformers import CLIPProcessor, CLIPModel

# ==========================================
# CONFIGURATION
# ==========================================
MODEL_DIR = "saved_clip_model"
LABELS = [
    "an overflowing waste bin with garbage spilling out",
    "a normal clean or empty waste bin"
]
CONFIDENCE_THRESHOLD = 0.50
# ==========================================

def load_clip_model(model_path=MODEL_DIR):
    if not os.path.exists(model_path):
        # Fallback check
        alt_path = os.path.join("Garbahe", model_path)
        if os.path.exists(alt_path):
            model_path = alt_path
        else:
            raise FileNotFoundError(f"Cannot find model directory at '{model_path}'")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"🚀 Loading CLIP model ({MODEL_DIR}/model.safetensors) on {device}...")
    
    # Load model and processor directly from the local folder containing model.safetensors
    model = CLIPModel.from_pretrained(model_path, local_files_only=True).to(device)
    processor = CLIPProcessor.from_pretrained(model_path, local_files_only=True)
    print("✅ Model loaded successfully from local safetensors!")
    return model, processor, device

def predict_frame(image_bgr, model, processor, device, labels=LABELS):
    # Convert OpenCV BGR to PIL RGB
    rgb_img = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(rgb_img)

    inputs = processor(text=labels, images=pil_img, return_tensors="pt", padding=True).to(device)
    with torch.no_grad():
        outputs = model(**inputs)
        probs = outputs.logits_per_image.softmax(dim=1)

    overflow_prob = probs[0][0].item()
    clean_prob = probs[0][1].item()

    if overflow_prob > CONFIDENCE_THRESHOLD:
        status = "OVERFLOWING"
        conf = overflow_prob
        is_overflow = True
    else:
        status = "CLEAN / NORMAL"
        conf = clean_prob
        is_overflow = False

    return status, conf, is_overflow

def run(source=0):
    model, processor, device = load_clip_model()

    # Check if source is image file
    if isinstance(source, str) and os.path.exists(source) and os.path.splitext(source)[1].lower() in ['.jpg', '.jpeg', '.png', '.bmp', '.webp']:
        print(f"\n🖼️ Processing Image: {source}")
        frame = cv2.imread(source)
        if frame is None:
            print("❌ Could not read image.")
            return

        status, conf, is_overflow = predict_frame(frame, model, processor, device)
        h, w = frame.shape[:2]
        color = (0, 0, 255) if is_overflow else (0, 255, 0)
        cv2.rectangle(frame, (0, 0), (w, 55), (20, 20, 20), -1)
        display_text = f"BIN STATUS: {status} ({conf * 100:.1f}%)"
        cv2.putText(frame, display_text, (20, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2, cv2.LINE_AA)

        out_path = f"detected_{os.path.basename(source)}"
        cv2.imwrite(out_path, frame)
        print(f"✅ Result: {status} (Confidence: {conf*100:.1f}%)")
        print(f"💾 Saved to: {out_path}")

        cv2.imshow("Waste Overflow Detection (CLIP)", frame)
        print("Press any key to close...")
        cv2.waitKey(0)
        cv2.destroyAllWindows()
        return

    # Video or Webcam
    print(f"\n🎥 Opening Video/Webcam Source: {source}...")
    try:
        source_idx = int(source)
    except (ValueError, TypeError):
        source_idx = source

    cap = cv2.VideoCapture(source_idx)
    if not cap.isOpened():
        print(f"❌ Could not open video/webcam source: {source}")
        return

    window_name = "Waste Overflow Detection (CLIP)"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

    print("\nControls:")
    print("  [Q] or [ESC] - Quit")
    print("  [S]         - Save snapshot\n")

    frame_count = 0
    status, conf, is_overflow = "INITIALIZING", 0.0, False

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        frame_count += 1
        # Run inference every 3 frames for smooth real-time performance
        if frame_count % 3 == 0 or frame_count == 1:
            status, conf, is_overflow = predict_frame(frame, model, processor, device)

        # Draw UI Overlay
        h, w = frame.shape[:2]
        color = (0, 0, 255) if is_overflow else (0, 255, 0)

        # Header background
        cv2.rectangle(frame, (0, 0), (w, 55), (20, 20, 20), -1)
        display_text = f"BIN STATUS: {status} ({conf * 100:.1f}%)"
        cv2.putText(frame, display_text, (20, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2, cv2.LINE_AA)

        cv2.imshow(window_name, frame)

        key = cv2.waitKey(1) & 0xFF
        if key in (ord('q'), 27):
            break
        elif key == ord('s'):
            out_img = f"clip_overflow_snapshot_{int(cv2.getTickCount())}.jpg"
            cv2.imwrite(out_img, frame)
            print(f"📸 Saved snapshot to {out_img}")

    cap.release()
    cv2.destroyAllWindows()
    print("Finished.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run CLIP model.safetensors for Waste Bin Overflow Detection")
    parser.add_argument("--source", type=str, default="0", help="Webcam index (0), image path, or video path")
    args = parser.parse_args()

    run(args.source)
