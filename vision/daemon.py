"""
Daemon vision — détection d'objets YOLOv8n en background.

Tourne en parallèle de FastAPI via asyncio.
Capture les frames webcam à ~2fps et analyse avec YOLOv8n.
Envoie les événements au Gateway via webhook interne ET publie
les bounding boxes normalisées dans VisionObjectsQueue pour
l'affichage temps réel dans le browser.

Note : la détection de gestes et de visage est gérée côté browser
       (mediapipe_vision.js). Ce daemon ne fait que la détection d'objets.
"""

from __future__ import annotations

import asyncio

import httpx
from loguru import logger

from config.settings import settings
from vision.object_detector import ObjectDetector
from vision.objects_queue import get_vision_objects_queue

_JARVIS_WEBHOOK = "http://localhost:8000/api/webhooks"
_TARGET_FPS = 2
_FRAME_INTERVAL = 1.0 / _TARGET_FPS


async def run_vision_daemon() -> None:
    """Boucle principale du daemon vision."""
    try:
        import cv2  # type: ignore[import-untyped]
    except ImportError:
        logger.error("Vision daemon: opencv-python non installé — daemon désactivé")
        return

    detector = ObjectDetector(confidence=settings.vision_yolo_confidence)
    objects_q = get_vision_objects_queue()

    cap = cv2.VideoCapture(settings.vision_webcam_index)
    if not cap.isOpened():
        logger.error("Vision daemon: webcam introuvable", index=settings.vision_webcam_index)
        return

    cap.set(cv2.CAP_PROP_FPS, _TARGET_FPS)
    logger.info("Vision daemon démarré", fps=_TARGET_FPS)

    loop = asyncio.get_running_loop()

    async with httpx.AsyncClient(timeout=1.0) as client:
        while True:
            loop_start = loop.time()

            ret, frame = await loop.run_in_executor(None, cap.read)
            if not ret or frame is None:
                await asyncio.sleep(0.5)
                continue

            import cv2 as _cv2

            frame = _cv2.flip(frame, 1)
            h, w = frame.shape[:2]

            result = await loop.run_in_executor(None, detector.process, frame)

            if result:
                # Normaliser les bbox pour le browser (coordonnées [0,1])
                boxes = [
                    {
                        "label": o.label,
                        "conf": round(o.confidence, 2),
                        "bbox": [
                            o.bbox[0] / w,
                            o.bbox[1] / h,
                            o.bbox[2] / w,
                            o.bbox[3] / h,
                        ],
                    }
                    for o in result.objects
                ]
                objects_q.publish(boxes)

                if result.new_objects:
                    await _send_event(
                        client,
                        "object_detected",
                        {
                            "new_objects": result.new_objects,
                            "all_objects": [o.label for o in result.objects],
                        },
                    )

            elapsed = loop.time() - loop_start
            await asyncio.sleep(max(0.0, _FRAME_INTERVAL - elapsed))

    cap.release()


async def _send_event(client: httpx.AsyncClient, event_type: str, data: dict) -> None:
    try:
        await client.post(f"{_JARVIS_WEBHOOK}/{event_type}", json=data)
    except Exception as e:
        logger.debug("Vision event send failed", error=str(e))
