import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse


app = FastAPI(title="ASR Service")

ASR_MODEL = os.getenv("ASR_MODEL", "small")
ASR_DEVICE = os.getenv("ASR_DEVICE", "cuda")
ASR_COMPUTE_TYPE = os.getenv("ASR_COMPUTE_TYPE", "float16")
INTERNAL_SERVICE_TOKEN = os.getenv("INTERNAL_SERVICE_TOKEN", "")
SERVICE_AUTH_HEADER = "X-Service-Token"

model = None


@app.middleware("http")
async def require_service_token(request: Request, call_next):
    if request.url.path == "/health":
        return await call_next(request)

    if not INTERNAL_SERVICE_TOKEN:
        return JSONResponse(status_code=503, content={"detail": "Internal service token is not configured"})

    if request.headers.get(SERVICE_AUTH_HEADER, "") != INTERNAL_SERVICE_TOKEN:
        return JSONResponse(status_code=401, content={"detail": "Invalid internal service token"})

    return await call_next(request)


def normalize_transcript(segments) -> str:
    return " ".join(segment.text.strip() for segment in segments if segment.text.strip()).strip()


def get_model():
    global model
    if model is None:
        from faster_whisper import WhisperModel

        model = WhisperModel(
            ASR_MODEL,
            device=ASR_DEVICE,
            compute_type=ASR_COMPUTE_TYPE,
        )
    return model


@app.get("/health")
async def health():
    return {"status": "ok", "service": "asr-service", "model": ASR_MODEL}


@app.post("/transcribe")
async def transcribe(audio: UploadFile = File(...)):
    if not audio.filename:
        raise HTTPException(status_code=400, detail="Audio file is required")

    payload = await audio.read()
    if not payload:
        raise HTTPException(status_code=400, detail="Empty audio")

    suffix = Path(audio.filename).suffix or ".webm"
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temporary_file:
            temporary_file.write(payload)
            temporary_path = temporary_file.name

        segments, info = get_model().transcribe(
            temporary_path,
            vad_filter=True,
            beam_size=1,
        )
        text = normalize_transcript(segments)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Speech recognition failed") from exc
    finally:
        if temporary_path:
            Path(temporary_path).unlink(missing_ok=True)

    return {"text": text, "language": info.language, "duration": info.duration}
