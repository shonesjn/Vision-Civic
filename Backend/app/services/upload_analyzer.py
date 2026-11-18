import os
import sys
import cv2
import json
import uuid
import tempfile
import subprocess
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Callable
from app.core.config import settings
from app.detectors.registry import DetectorRegistry
from app.services.video_processor import extract_video_clip, save_snapshot, get_video_metadata, draw_bounding_box
from app.services.cloudinary_service import upload_image, upload_video
from app.database.mongodb import get_database

logger = logging.getLogger(__name__)

# Shared thread pool executor for non-blocking parallel model inference
executor = ThreadPoolExecutor(max_workers=4)


async def analyze_uploaded_image(
    image_path: str,
    original_filename: str,
    file_size_bytes: int,
    user_id: str,
    model_choice: str = "both"
) -> List[Dict[str, Any]]:
    """
    Process an uploaded image file using concurrent parallel model inference.
    Uploads the verified image snapshot (with bounding box & label) to Cloudinary and records the incident document in MongoDB.
    """
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image file does not exist: {image_path}")

    upload_time = datetime.now(timezone.utc)
    frame = cv2.imread(image_path)
    if frame is None or frame.size == 0:
        raise ValueError(f"Could not decode image file: {image_path}")

    waste_detector = DetectorRegistry.get_waste_bin_detector() if model_choice in ["waste_bin", "both", "all"] else None
    fire_detector = DetectorRegistry.get_fire_smoke_detector() if model_choice in ["fire_smoke", "both", "all"] else None
    pothole_detector = DetectorRegistry.get_pothole_detector() if model_choice in ["pothole", "all"] else None

    loop = asyncio.get_running_loop()
    tasks = []

    if waste_detector:
        tasks.append(loop.run_in_executor(executor, waste_detector.detect, frame))
    if fire_detector:
        tasks.append(loop.run_in_executor(executor, fire_detector.detect, frame))
    if pothole_detector:
        tasks.append(loop.run_in_executor(executor, pothole_detector.detect, frame))

    dets = []
    if tasks:
        results = await asyncio.gather(*tasks)
        for res in results:
            if res.get("detected"):
                dets.append(res)

    created_incidents = []
    db = get_database()

    for d in dets:
        itype = d["type"]
        model_type = "waste_bin" if itype == "WASTE_BIN_OVERFLOW" else "fire_smoke"
        conf = d["confidence"]
        bbox = d.get("bbox")

        # Annotate frame with bounding box and label
        annotated_frame = draw_bounding_box(
            frame=frame,
            bbox=bbox,
            label=itype,
            confidence=conf
        )

        # Save annotated snapshot and upload to Cloudinary (graceful fallback)
        snap_res = {}
        try:
            snap_path = save_snapshot(annotated_frame, prefix=f"upload_img_{itype.lower()}")
            snap_res = upload_image(snap_path, folder="vision_civic/snapshots")
        except Exception as e:
            logger.error("Cloudinary snapshot upload failed for %s: %s", itype, e)

        ext = os.path.splitext(original_filename)[1].lower().lstrip(".")
        incident_doc = {
            "incident_type": itype,
            "model_type": model_type,
            "confidence": round(conf, 4),
            "bbox": bbox,
            "source_type": "UPLOADED_IMAGE",
            "original_filename": original_filename,
            "uploaded_at": upload_time,
            "file_size_bytes": file_size_bytes,
            "snapshot_url": snap_res.get("url"),
            "snapshot_public_id": snap_res.get("public_id"),
            "video_url": None,
            "video_public_id": None,
            "status": "CONFIRMED",
            "created_by": user_id,
            "created_at": datetime.now(timezone.utc)
        }

        insert_res = await db.incidents.insert_one(incident_doc)
        incident_doc["_id"] = str(insert_res.inserted_id)
        created_incidents.append(incident_doc)

    return created_incidents



async def analyze_uploaded_video(
    video_path: str,
    original_filename: str,
    file_size_bytes: int,
    user_id: str,
    model_choice: str = "both",  # "waste_bin", "fire_smoke", or "both"
    progress_callback: Optional[Callable[[float, str], Any]] = None
) -> List[Dict[str, Any]]:
    """
    Process an uploaded video using optimized interleaved frame scheduling
    and parallel thread pool multi-model execution.
    Groups continuous detections into distinct incident clips to prevent duplicate entries.
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file does not exist: {video_path}")

    upload_time = datetime.now(timezone.utc)
    meta = get_video_metadata(video_path)
    video_duration = meta["duration"]
    video_recorded_at = meta.get("recorded_at")

    # TRIGGER CIVICSENSE_ALL_IN_ONE.PY ON THE UPLOADED VIDEO
    WORKSPACE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    SCRIPT_PATH = os.path.join(WORKSPACE_DIR, "Pothole", "civicsense_all_in_one.py")
    PYTHON_EXE = os.path.join(WORKSPACE_DIR, "Backend", "venv", "Scripts", "python.exe")
    if not os.path.exists(PYTHON_EXE):
        PYTHON_EXE = sys.executable

    json_out = os.path.join(tempfile.gettempdir(), f"cs_{uuid.uuid4().hex[:8]}.json")
    video_out = os.path.join(tempfile.gettempdir(), f"cs_ann_{uuid.uuid4().hex[:8]}.mp4")

    if os.path.exists(SCRIPT_PATH):
        logger.info("[CIVICSENSE] Triggering civicsense_all_in_one.py on uploaded video: %s", video_path)
        cmd = [
            PYTHON_EXE,
            SCRIPT_PATH,
            "--source", video_path,
            "--json-output", json_out,
            "--save-output", video_out,
            "--headless",
            "--no-esp"
        ]
        try:
            def run_cs_script():
                return subprocess.run(
                    cmd,
                    cwd=os.path.dirname(SCRIPT_PATH),
                    timeout=180,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace"
                )

            res = await asyncio.to_thread(run_cs_script)
            logger.info("[CIVICSENSE] civicsense_all_in_one.py finished (exit code %s)", res.returncode)

            if os.path.exists(json_out):
                with open(json_out, "r", encoding="utf-8") as jf:
                    cs_incidents = json.load(jf)

                db = get_database()
                saved_docs = []
                ann_src = video_out if os.path.exists(video_out) else video_path
                cap_src = cv2.VideoCapture(ann_src)

                for inc in cs_incidents:
                    itype = inc["incident_type"]
                    conf = inc["confidence"]
                    bbox = inc.get("bbox")
                    t_sec = float(inc.get("timestamp_seconds", 0.0))

                    # Capture keyframe snapshot
                    cap_src.set(cv2.CAP_PROP_POS_MSEC, t_sec * 1000)
                    ok, s_frame = cap_src.read()
                    snap_res = {}
                    annotated_snap = None
                    if ok and s_frame is not None:
                        annotated_snap = draw_bounding_box(s_frame, bbox=bbox, label=itype, confidence=conf)
                        snap_p = save_snapshot(annotated_snap, prefix=f"cs_{itype.lower()}")
                        try:
                            snap_res = upload_image(snap_p, folder="vision_civic/snapshots")
                        except Exception as e:
                            logger.warning("Cloudinary snapshot upload warning: %s", e)

                    # Extract context clip around timestamp
                    clip_p = extract_video_clip(
                        source_video_path=ann_src,
                        start_seconds=max(0.0, t_sec - 2.0),
                        end_seconds=min(video_duration, t_sec + 3.0),
                        prefix=f"cs_clip_{itype.lower()}"
                    )
                    clip_res = {}
                    if clip_p and os.path.exists(clip_p):
                        try:
                            clip_res = upload_video(clip_p, folder="vision_civic/incident_clips")
                        except Exception as e:
                            logger.warning("Cloudinary clip upload warning: %s", e)

                    snap_url = snap_res.get("url")
                    if not snap_url and annotated_snap is not None:
                        import base64
                        ret_enc, buf = cv2.imencode(".jpg", annotated_snap, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                        if ret_enc:
                            snap_url = f"data:image/jpeg;base64,{base64.b64encode(buf).decode('utf-8')}"

                    model_type = "waste_bin" if itype == "WASTE_BIN_OVERFLOW" else "pothole" if itype == "POTHOLE" else "fire_smoke"
                    doc = {
                        "incident_type": itype,
                        "model_type": model_type,
                        "confidence": round(float(conf), 4),
                        "bbox": bbox,
                        "source_type": "UPLOADED_VIDEO",
                        "original_filename": original_filename,
                        "uploaded_at": upload_time,
                        "video_duration_seconds": round(float(video_duration), 2),
                        "video_timestamp_detected": round(float(t_sec), 2),
                        "event_start_offset_seconds": round(max(0.0, float(t_sec) - 2.0), 2),
                        "event_end_offset_seconds": round(min(video_duration, float(t_sec) + 3.0), 2),
                        "clip_start_offset_seconds": round(max(0.0, float(t_sec) - 2.0), 2),
                        "clip_end_offset_seconds": round(min(video_duration, float(t_sec) + 3.0), 2),
                        "event_duration_seconds": 5.0,
                        "video_url": clip_res.get("url"),
                        "video_public_id": clip_res.get("public_id"),
                        "snapshot_url": snap_url,
                        "snapshot_public_id": snap_res.get("public_id"),
                        "status": "CONFIRMED",
                        "created_by": user_id,
                        "created_at": datetime.now(timezone.utc),
                        "engine": "civicsense_all_in_one.py"
                    }
                    insert_res = await db.incidents.insert_one(doc)
                    doc["_id"] = str(insert_res.inserted_id)
                    saved_docs.append(doc)

                cap_src.release()
                logger.info("[CIVICSENSE] Successfully processed %d incidents via civicsense_all_in_one.py", len(saved_docs))
                return saved_docs
        except Exception as e:
            logger.error("[CIVICSENSE] Execution failed, falling back to internal scanner: %s", e, exc_info=True)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Could not open video stream from {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    waste_detector = DetectorRegistry.get_waste_bin_detector() if model_choice in ["waste_bin", "both", "all"] else None
    fire_detector = DetectorRegistry.get_fire_smoke_detector() if model_choice in ["fire_smoke", "both", "all"] else None
    pothole_detector = DetectorRegistry.get_pothole_detector() if model_choice in ["pothole", "all"] else None

    # Sample frames every ~0.4s
    sample_step = max(1, int(fps * 0.4))

    frame_idx = 0
    sample_count = 0
    raw_detections: List[Dict[str, Any]] = []

    loop = asyncio.get_running_loop()

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % sample_step == 0:
            current_offset_sec = round(frame_idx / fps, 2)
            sample_count += 1
            tasks = []

            # Concurrent Execution across active models
            if waste_detector:
                tasks.append((loop.run_in_executor(executor, waste_detector.detect, frame.copy()), "waste_bin"))
            if fire_detector:
                tasks.append((loop.run_in_executor(executor, fire_detector.detect, frame.copy()), "fire_smoke"))
            if pothole_detector:
                tasks.append((loop.run_in_executor(executor, pothole_detector.detect, frame.copy()), "pothole"))

            if tasks:
                fut_results = await asyncio.gather(*[t[0] for t in tasks])
                for res in fut_results:
                    if res.get("detected"):
                        bbox = res.get("bbox")
                        annotated = draw_bounding_box(
                            frame=frame,
                            bbox=bbox,
                            label=res["type"],
                            confidence=res["confidence"]
                        )
                        raw_detections.append({
                            "offset": current_offset_sec,
                            "type": res["type"],
                            "confidence": res["confidence"],
                            "bbox": bbox,
                            "frame": annotated
                        })

            if progress_callback and total_frames > 0:
                pct = round((frame_idx / total_frames) * 70.0, 1)
                import inspect
                if inspect.iscoroutinefunction(progress_callback):
                    await progress_callback(pct, f"Scanning video ({current_offset_sec}s / {video_duration}s)...")
                else:
                    progress_callback(pct, f"Scanning video ({current_offset_sec}s / {video_duration}s)...")

        frame_idx += 1

    cap.release()

    # Separate raw detections by incident type
    incidents_by_type: Dict[str, List[Dict[str, Any]]] = {}
    for d in raw_detections:
        itype = d["type"]
        if itype not in incidents_by_type:
            incidents_by_type[itype] = []
        incidents_by_type[itype].append(d)

    # DEDUPLICATION & MERGING: Group consecutive/adjacent detections within 5.0s gap into 1 continuous incident clip
    grouped_incidents: List[Dict[str, Any]] = []
    cooldown_tolerance = 5.0

    for itype, dets in incidents_by_type.items():
        if not dets:
            continue

        dets.sort(key=lambda x: x["offset"])

        current_group = [dets[0]]
        for d in dets[1:]:
            if d["offset"] - current_group[-1]["offset"] <= cooldown_tolerance:
                current_group.append(d)
            else:
                grouped_incidents.append(current_group)
                current_group = [d]
        if current_group:
            grouped_incidents.append(current_group)

    created_incidents: List[Dict[str, Any]] = []
    total_groups = len(grouped_incidents)
    db = get_database()

    for idx, grp in enumerate(grouped_incidents):
        itype = grp[0]["type"]
        model_type = "waste_bin" if itype == "WASTE_BIN_OVERFLOW" else "fire_smoke"

        event_start_offset = grp[0]["offset"]
        event_end_offset = grp[-1]["offset"]
        event_duration = max(1.0, round(event_end_offset - event_start_offset, 2))

        # Select the highest-confidence frame in the merged event for the keyframe snapshot
        best_item = max(grp, key=lambda x: x["confidence"])
        best_conf = best_item["confidence"]
        best_frame = best_item["frame"]
        best_bbox = best_item.get("bbox")

        # Calculate exact clip boundaries including pre-event & post-event context buffer
        clip_start_offset = max(0.0, round(event_start_offset - settings.PRE_EVENT_SECONDS, 2))
        clip_end_offset = min(video_duration, round(event_end_offset + settings.POST_EVENT_SECONDS, 2))
        if clip_end_offset <= clip_start_offset:
            clip_end_offset = min(video_duration, clip_start_offset + 5.0)

        # 1. Save and upload snapshot image (annotated with bounding box & label tag)
        snap_res = {}
        try:
            snap_path = save_snapshot(best_frame, prefix=f"upload_snap_{itype.lower()}")
            snap_res = upload_image(snap_path, folder="vision_civic/snapshots")
        except Exception as e:
            logger.error("Snapshot upload failed for %s: %s", itype, e)

        # 2. Extract and upload exact incident video segment clip (with bounding box marked)
        video_res = {}
        try:
            clip_path = extract_video_clip(
                source_video_path=video_path,
                start_seconds=clip_start_offset,
                end_seconds=clip_end_offset,
                prefix=f"upload_clip_{itype.lower()}",
                bbox=best_bbox,
                label=itype,
                confidence=best_conf,
                event_start_seconds=event_start_offset,
                event_end_seconds=event_end_offset,
                detections=grp
            )
            video_res = upload_video(clip_path, folder="vision_civic/incident_clips")
        except Exception as e:
            logger.error("Video extract/upload failed for %s: %s", itype, e)

        # 3. Save MongoDB Incident Document
        ext = os.path.splitext(original_filename)[1].lower().lstrip(".")
        incident_doc = {
            "incident_type": itype,
            "model_type": model_type,
            "confidence": round(best_conf, 4),
            "bbox": best_bbox,
            "source_type": "UPLOADED_VIDEO",
            "original_filename": original_filename,
            "uploaded_at": upload_time,
            "video_duration_seconds": video_duration,
            "video_format": ext,
            "file_size_bytes": file_size_bytes,
            "video_timestamp_detected": best_item["offset"],
            "event_start_offset_seconds": event_start_offset,
            "event_end_offset_seconds": event_end_offset,
            "event_duration_seconds": event_duration,
            "clip_start_offset_seconds": clip_start_offset,
            "clip_end_offset_seconds": clip_end_offset,
            "pre_event_clip_seconds": float(settings.PRE_EVENT_SECONDS),
            "post_event_clip_seconds": float(settings.POST_EVENT_SECONDS),
            "video_recorded_at": video_recorded_at,
            "video_url": video_res.get("url"),
            "video_public_id": video_res.get("public_id"),
            "snapshot_url": snap_res.get("url"),
            "snapshot_public_id": snap_res.get("public_id"),
            "status": "CONFIRMED",
            "created_by": user_id,
            "created_at": datetime.now(timezone.utc)
        }
        insert_res = await db.incidents.insert_one(incident_doc)
        incident_doc["_id"] = str(insert_res.inserted_id)

        created_incidents.append(incident_doc)

        if progress_callback:
            progress_val = 70.0 + round(((idx + 1) / max(1, total_groups)) * 30.0, 1)
            import inspect
            msg = f"Generated incident clip {idx + 1} of {total_groups} ({itype})"
            if inspect.iscoroutinefunction(progress_callback):
                await progress_callback(progress_val, msg)
            else:
                progress_callback(progress_val, msg)

    return created_incidents
