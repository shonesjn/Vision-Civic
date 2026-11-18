import asyncio
import base64
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional
import cv2
import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, Depends, HTTPException, status
from pydantic import BaseModel
from app.core.config import settings
from app.core.security import decode_access_token
from app.core.dependencies import get_current_user
from app.detectors.registry import DetectorRegistry
from app.monitoring.incident_manager import LiveIncidentManager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Monitoring & WebSockets"])


class MonitoringControlRequest(BaseModel):
    camera_name: str = "Webcam 1"
    model_choice: str = "both"  # "waste_bin", "fire_smoke", "both"


active_sessions: Dict[str, Dict[str, Any]] = {}


@router.post("/monitoring/start")
async def start_monitoring(
    req: MonitoringControlRequest,
    current_user: dict = Depends(get_current_user)
):
    """Register or initialize a monitoring session."""
    user_id = current_user["_id"]
    active_sessions[user_id] = {
        "status": "RUNNING",
        "camera_name": req.camera_name,
        "model_choice": req.model_choice,
        "started_at": datetime.now(timezone.utc).isoformat()
    }
    return {
        "status": "STARTED",
        "session": active_sessions[user_id],
        "message": "Monitoring session initialized."
    }


@router.post("/monitoring/stop")
async def stop_monitoring(current_user: dict = Depends(get_current_user)):
    """Stop active monitoring session."""
    user_id = current_user["_id"]
    if user_id in active_sessions:
        del active_sessions[user_id]
    return {"status": "STOPPED", "message": "Monitoring session stopped."}


@router.websocket("/ws/monitoring")
async def websocket_monitoring(
    websocket: WebSocket,
    token: Optional[str] = Query(None)
):
    """
    Real-time WebSocket endpoint for live camera feed processing.
    Accepts client frames, performs AI inference using preloaded detectors,
    maintains rolling buffer and incident deduplication,
    and returns detection metrics and saved incident events.
    """
    await websocket.accept()

    # Authenticate token from query param or cookies, with fallback for seamless live monitoring
    auth_token = token or websocket.cookies.get(settings.COOKIE_NAME)
    user_id = "operator_default"
    if auth_token:
        payload = decode_access_token(auth_token)
        if payload:
            user_id = payload.get("sub", "operator_default")

    # Initialize live incident manager for this connection
    async def incident_saved_callback(incident_doc: Dict[str, Any]):
        try:
            # Broadcast to frontend
            await websocket.send_json({
                "type": "INCIDENT_SAVED",
                "incident": incident_doc
            })
        except Exception as e:
            logger.warning("Could not send incident saved notification to client: %s", e)

    camera_name = "Webcam 1"
    model_choice = "both"
    incident_mgr = LiveIncidentManager(
        camera_name=camera_name,
        source_id="webcam_live",
        user_id=user_id,
        on_incident_saved=incident_saved_callback
    )

    waste_detector = DetectorRegistry.get_waste_bin_detector()
    fire_detector = DetectorRegistry.get_fire_smoke_detector()
    pothole_detector = DetectorRegistry.get_pothole_detector()

    try:
        while True:
            try:
                raw_text = await asyncio.wait_for(websocket.receive_text(), timeout=1.5)
            except asyncio.TimeoutError:
                # No frame received in 1.5s - check if active incident should be saved
                await incident_mgr.check_inactivity()
                continue

            data = json.loads(raw_text)
            msg_type = data.get("action")

            if msg_type == "configure":
                model_choice = data.get("model_choice", "both")
                camera_name = data.get("camera_name", "Webcam 1")
                save_to_db = data.get("save_to_db", True)
                incident_mgr.camera_name = camera_name
                incident_mgr.save_to_db = save_to_db
                logger.info("Configured session: model=%s, cam=%s, save_to_db=%s", model_choice, camera_name, save_to_db)
                await websocket.send_json({
                    "type": "CONFIG_ACK",
                    "model_choice": model_choice,
                    "camera_name": camera_name,
                    "save_to_db": save_to_db
                })
                continue

            elif msg_type in ["stop", "flush", "pause"]:
                await incident_mgr.flush()
                await websocket.send_json({"type": "FLUSH_ACK"})
                continue

            elif msg_type == "frame":
                if "save_to_db" in data:
                    incident_mgr.set_save_to_db(bool(data["save_to_db"]))

                frame_data = data.get("data")
                if not frame_data:
                    continue

                # Strip base64 header if present
                if "," in frame_data:
                    frame_data = frame_data.split(",")[1]

                img_bytes = base64.b64decode(frame_data)
                np_arr = np.frombuffer(img_bytes, np.uint8)
                frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

                if frame is None:
                    continue

                t0 = time.time()
                detections = []
                now_str = datetime.now(timezone.utc).isoformat()

                # Concurrent parallel inference across selected models
                tasks = []
                task_types = []
                if model_choice in ["waste_bin", "both", "all"] and waste_detector:
                    tasks.append(asyncio.to_thread(waste_detector.detect, frame))
                    task_types.append("waste_bin")
                if model_choice in ["fire_smoke", "both", "all"] and fire_detector:
                    tasks.append(asyncio.to_thread(fire_detector.detect, frame))
                    task_types.append("fire_smoke")
                if model_choice in ["pothole", "all"] and pothole_detector:
                    tasks.append(asyncio.to_thread(pothole_detector.detect, frame))
                    task_types.append("pothole")

                telemetry = {
                    "waste_overflow_prob": 0.0,
                    "fire_smoke_prob": 0.0,
                    "pothole_prob": 0.0,
                    "latency_ms": 0,
                    "status": "CLEAR"
                }

                if tasks:
                    results = await asyncio.gather(*tasks)
                    for idx, res in enumerate(results):
                        mtype = task_types[idx]
                        if mtype == "waste_bin":
                            telemetry["waste_overflow_prob"] = res.get("details", {}).get("overflow_prob", 0.0)
                        elif mtype == "fire_smoke":
                            telemetry["fire_smoke_prob"] = res.get("confidence", 0.0)
                        elif mtype == "pothole":
                            telemetry["pothole_prob"] = res.get("confidence", 0.0)

                        if res.get("detected"):
                            detections.append({
                                "detected": True,
                                "type": res["type"],
                                "confidence": res["confidence"],
                                "bbox": res.get("bbox"),
                                "label": res.get("label"),
                                "orig_w": frame.shape[1],
                                "orig_h": frame.shape[0],
                                "timestamp": now_str
                            })

                telemetry["latency_ms"] = int((time.time() - t0) * 1000)
                telemetry["status"] = "INCIDENT_ALERT" if detections else "CLEAR"

                # Feed into live incident deduplicator and rolling buffer
                incident_mgr.process_frame(frame, detections)

                # Return detection result and real-time telemetry to client
                await websocket.send_json({
                    "type": "DETECTION_UPDATE",
                    "detections": detections,
                    "telemetry": telemetry,
                    "active_incidents": list(incident_mgr.active_incidents.keys()),
                    "save_to_db": incident_mgr.save_to_db,
                    "timestamp": now_str
                })

            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for user %s", user_id)
    except Exception as e:
        logger.error("WebSocket exception: %s", e, exc_info=True)
        try:
            await websocket.close()
        except Exception:
            pass
    finally:
        try:
            await incident_mgr.flush()
        except Exception as e:
            logger.error("Error flushing incident manager on exit: %s", e)
