"""
cameras.py — Motor de streaming MJPEG para cámaras de equipos
GRUPO ESMA — Plataforma de Telemetría

Soporta:
  - Cámaras IP vía RTSP  (rtsp://user:pass@192.168.1.x/stream)
  - Cámaras IP vía HTTP MJPEG  (http://192.168.1.x/video)
  - Webcam local  (0, 1, 2 … índice de dispositivo)

Arquitectura: un hilo captura frames de la cámara y los deposita en un
buffer compartido. Múltiples clientes HTTP leen del mismo buffer, así la
cámara solo se abre una vez sin importar cuántos navegadores la vean.
"""

import cv2
import threading
import time
import logging

logger = logging.getLogger(__name__)

# ── Configuración global ──────────────────────────────────────────
JPEG_QUALITY   = 60    # calidad JPEG 0-100
FRAME_INTERVAL = 0.08  # segundos entre frames (~12 fps)
RECONNECT_WAIT = 5     # segundos antes de reintentar si la cámara cae
IDLE_TIMEOUT   = 30    # segundos sin lectores → cerrar la captura
MAX_OPEN_CAMS  = 8     # máximo de cámaras abiertas simultáneamente


# ── Frame de error (se genera al importar, DESPUÉS de definir la función) ──

def _build_error_frame():
    """Genera un frame JPEG negro con texto 'Sin señal'."""
    try:
        import numpy as np
        img = np.zeros((240, 320, 3), dtype="uint8")
        cv2.putText(img, "Sin senal", (70, 130),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.1, (70, 70, 70), 2)
        _, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 60])
        return buf.tobytes()
    except Exception:
        # Si OpenCV no está disponible devuelve un JPEG mínimo válido (1×1 negro)
        return (
            b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00'
            b'\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t'
            b'\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a'
            b'\x1f\x1e\x1d\x1a\x1c\x1c $.\' ",#\x1c\x1c(7),01444\x1f\'9=82<.342\x1e\xbf'
            b'\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00'
            b'\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00'
            b'\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b'
            b'\xff\xc4\x00\xb5\x10\x00\x02\x01\x03\x03\x02\x04\x03\x05\x05\x04'
            b'\x04\x00\x00\x01}\x01\x02\x03\x00\x04\x11\x05\x12!1A\x06\x13Qa'
            b'\x07"q\x142\x81\x91\xa1\x08#B\xb1\xc1\x15R\xd1'
            b'\xf0$3br\x82\t\n\x16\x17\x18\x19\x1a%&\'()*456789:CDEFGHIJ'
            b'STUVWXYZ\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xfb\xd4P\x00\x00\x00\xff\xd9'
        )


# Constante global — se define aquí, DESPUÉS de _build_error_frame
_ERROR_FRAME: bytes = _build_error_frame()


# ── Clase de stream ───────────────────────────────────────────────

class CameraStream:
    """Maneja la captura continua de una única fuente de video."""

    def __init__(self, url: str):
        self.url        = url
        self._frame     = None
        self._lock      = threading.Lock()
        self._thread    = None
        self._running   = False
        self._readers   = 0
        self._last_read = time.time()
        self._error     = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._running = True
        self._error   = None
        self._thread  = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def get_frame(self):
        with self._lock:
            self._last_read = time.time()
            return self._frame

    def add_reader(self):
        self._readers += 1

    def remove_reader(self):
        self._readers = max(0, self._readers - 1)

    @property
    def is_alive(self):
        return self._thread is not None and self._thread.is_alive()

    @property
    def error(self):
        return self._error

    def _capture_loop(self):
        while self._running:
            cap = None
            try:
                src = self.url
                try:
                    src = int(self.url)   # webcam local: "0", "1" …
                except (ValueError, TypeError):
                    pass

                cap = cv2.VideoCapture(src)
                if not cap.isOpened():
                    raise RuntimeError(f"No se pudo abrir: {self.url}")

                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                self._error = None
                logger.info(f"[CAMS] Abierta: {self.url}")

                while self._running:
                    if (self._readers == 0 and
                            time.time() - self._last_read > IDLE_TIMEOUT):
                        logger.info(f"[CAMS] Cerrando por inactividad: {self.url}")
                        self._running = False
                        break

                    ok, frame = cap.read()
                    if not ok:
                        time.sleep(0.5)
                        continue

                    _, buf = cv2.imencode(
                        '.jpg', frame,
                        [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
                    )
                    with self._lock:
                        self._frame = buf.tobytes()

                    time.sleep(FRAME_INTERVAL)

            except Exception as exc:
                self._error = str(exc)
                logger.warning(f"[CAMS] Error {self.url}: {exc}")
            finally:
                if cap and cap.isOpened():
                    cap.release()

            if self._running:
                logger.info(f"[CAMS] Reconectando en {RECONNECT_WAIT}s: {self.url}")
                time.sleep(RECONNECT_WAIT)


# ── Registro global de streams ────────────────────────────────────

_streams: dict = {}
_streams_lock  = threading.Lock()


def _get_stream(cam_id: int, url: str) -> CameraStream:
    with _streams_lock:
        if cam_id not in _streams:
            if len(_streams) >= MAX_OPEN_CAMS:
                for cid, st in list(_streams.items()):
                    if st._readers == 0:
                        st.stop()
                        del _streams[cid]
                        break
            _streams[cam_id] = CameraStream(url)

        stream = _streams[cam_id]
        if not stream.is_alive:
            stream.start()
        return stream


def generate_mjpeg(cam_id: int, url: str):
    """
    Generador MJPEG para Flask Response.

    Uso:
        return Response(generate_mjpeg(cam.id, cam.url_stream),
                        mimetype='multipart/x-mixed-replace; boundary=frame')
    """
    stream = _get_stream(cam_id, url)
    stream.add_reader()
    try:
        while True:
            frame = stream.get_frame()
            if frame is None:
                frame = _ERROR_FRAME
                time.sleep(0.5)
            else:
                time.sleep(FRAME_INTERVAL)

            yield (
                b'--frame\r\n'
                b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n'
            )
    finally:
        stream.remove_reader()


def get_snapshot(cam_id: int, url: str) -> bytes:
    """Captura un único frame JPEG (para thumbnails)."""
    stream = _get_stream(cam_id, url)
    stream.add_reader()
    deadline = time.time() + 3
    while time.time() < deadline:
        frame = stream.get_frame()
        if frame is not None:
            stream.remove_reader()
            return frame
        time.sleep(0.1)
    stream.remove_reader()
    return _ERROR_FRAME


def stop_all():
    """Detiene todos los streams activos."""
    with _streams_lock:
        for st in _streams.values():
            st.stop()
        _streams.clear()
