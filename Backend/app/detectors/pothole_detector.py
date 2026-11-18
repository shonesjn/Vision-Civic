import os
import logging
from typing import Dict, Any, Optional
import numpy as np
from app.detectors.base import BaseDetector

logger = logging.getLogger(__name__)


class PotholeDetector(BaseDetector):
    """
    Pothole and Road Damage Object Detector.
    Utilizes the trained YOLO model (best.pt in Pothole directory).
    Loaded once and reused across inference frames.
    """

    def __init__(self, model_path: Optional[str] = None):
        self.model_path = model_path
        self.custom_model = None
        self._load_model()

    def _load_model(self):
        potential_model_paths = [
            self.model_path,
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "Pothole", "best.pt"),
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "Pothole", "runs", "detect", "runs", "pothole_yolo11n", "weights", "best.pt"),
            os.path.join(os.getcwd(), "..", "Pothole", "best.pt"),
            os.path.join(os.getcwd(), "models", "pothole.pt"),
        ]

        for p in potential_model_paths:
            if p and os.path.exists(p):
                try:
                    logger.info("Loading Pothole YOLO model weights from %s...", p)
                    from ultralytics import YOLO
                    self.custom_model = YOLO(p)
                    logger.info("[OK] Pothole YOLO model loaded successfully.")
                    return
                except Exception as e:
                    logger.error("Could not load YOLO model from %s: %s", p, e)

        logger.warning("Could not locate or load Pothole YOLO model weights.")

    def detect(self, frame: np.ndarray) -> Dict[str, Any]:
        """
        Process frame and detect presence of road potholes using trained YOLO model.
        Returns detection status, type (POTHOLE), confidence score, and bounding box.
        """
        if frame is None or frame.size == 0 or self.custom_model is None:
            return {
                "detected": False,
                "type": None,
                "confidence": 0.0,
                "bbox": None,
                "label": "CLEAR",
                "details": {}
            }

        try:
            results = self.custom_model(frame, imgsz=480, conf=0.45, verbose=False)
            best_det = None
            max_conf = 0.0

            for r in results:
                for box in r.boxes:
                    conf = float(box.conf[0].item())
                    if conf >= 0.45 and conf > max_conf:
                        max_conf = conf
                        xyxy = [int(v) for v in box.xyxy[0].tolist()]
                        best_det = {
                            "detected": True,
                            "type": "POTHOLE",
                            "confidence": round(conf, 4),
                            "bbox": xyxy,
                            "label": "POTHOLE DETECTED",
                            "details": {"model": "yolo11n", "class": "pothole"}
                        }

            if best_det:
                return best_det

        except Exception as e:
            logger.error("Error executing YOLO Pothole model: %s", e)

        return {
            "detected": False,
            "type": None,
            "confidence": 0.0,
            "bbox": None,
            "label": "CLEAR",
            "details": {}
        }
