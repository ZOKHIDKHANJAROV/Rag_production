import json
import os
from pathlib import Path

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse


app = FastAPI(title="CosyVoice Adapter")

COSYVOICE_URL = os.getenv("COSYVOICE_URL", "http://cosyvoice-service:50000")
TTS_SAMPLE_RATE = int(os.getenv("TTS_SAMPLE_RATE", "22050"))
TTS_REQUEST_TIMEOUT = int(os.getenv("TTS_REQUEST_TIMEOUT", "300"))
TTS_PROFILE_PATH = Path(os.getenv("TTS_PROFILE_PATH", "/app/data/voice-profile.json"))
TTS_REFERENCE_PATH = Path(os.getenv("TTS_REFERENCE_PATH", "/app/data/voice-reference.wav"))
INTERNAL_SERVICE_TOKEN = os.getenv("INTERNAL_SERVICE_TOKEN", "")
SERVICE_AUTH_HEADER = "X-Service-Token"

client: httpx.AsyncClient | None = None


def default_profile():
    return {"enabled": False, "mode": "sft", "speaker_id": "", "prompt_text": ""}


def load_profile():
    if not TTS_PROFILE_PATH.exists():
        return default_profile()
    try:
        return {**default_profile(), **json.loads(TTS_PROFILE_PATH.read_text(encoding="utf-8"))}
    except (OSError, json.JSONDecodeError):
        return default_profile()


def save_profile(profile):
    TTS_PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    TTS_PROFILE_PATH.write_text(json.dumps(profile), encoding="utf-8")


def public_profile(profile):
    return {**profile, "has_reference": TTS_REFERENCE_PATH.exists()}


@app.middleware("http")
async def require_service_token(request: Request, call_next):
    if request.url.path == "/health":
        return await call_next(request)

    if not INTERNAL_SERVICE_TOKEN:
        return JSONResponse(status_code=503, content={"detail": "Internal service token is not configured"})

    if request.headers.get(SERVICE_AUTH_HEADER, "") != INTERNAL_SERVICE_TOKEN:
        return JSONResponse(status_code=401, content={"detail": "Invalid internal service token"})

    return await call_next(request)


@app.on_event("startup")
async def startup_event():
    global client
    client = httpx.AsyncClient(timeout=httpx.Timeout(TTS_REQUEST_TIMEOUT, connect=10.0))


@app.on_event("shutdown")
async def shutdown_event():
    if client:
        await client.aclose()


@app.get("/health")
async def health():
    return {"status": "ok", "service": "tts-service", "profile": public_profile(load_profile())}


@app.get("/profile")
async def profile():
    return public_profile(load_profile())


@app.post("/admin/profile")
async def configure_profile(
    enabled: bool = Form(False),
    mode: str = Form("sft"),
    speaker_id: str = Form(""),
    prompt_text: str = Form(""),
    reference_audio: UploadFile | None = File(None),
):
    normalized_mode = mode.strip().lower()
    if normalized_mode not in {"sft", "zero_shot"}:
        raise HTTPException(status_code=400, detail="Unsupported voice mode")
    if normalized_mode == "zero_shot" and not (reference_audio or TTS_REFERENCE_PATH.exists()):
        raise HTTPException(status_code=400, detail="A reference audio file is required for zero-shot voice")

    if reference_audio:
        if not (reference_audio.filename or "").lower().endswith(".wav"):
            raise HTTPException(status_code=415, detail="Reference audio must be a WAV file")
        reference_bytes = await reference_audio.read()
        if not reference_bytes:
            raise HTTPException(status_code=400, detail="Reference audio is empty")
        if len(reference_bytes) > 20 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Reference audio exceeds 20MB")
        TTS_REFERENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
        TTS_REFERENCE_PATH.write_bytes(reference_bytes)

    configured = {
        "enabled": enabled,
        "mode": normalized_mode,
        "speaker_id": speaker_id.strip(),
        "prompt_text": prompt_text.strip(),
    }
    save_profile(configured)
    return public_profile(configured)


@app.post("/synthesize/stream")
async def synthesize_stream(text: str = Form(...)):
    if client is None:
        raise HTTPException(status_code=503, detail="TTS client is not initialized")

    profile = load_profile()
    if not profile["enabled"]:
        raise HTTPException(status_code=503, detail="Voice mode is disabled")
    if not text.strip():
        raise HTTPException(status_code=400, detail="Text is required")

    endpoint = "/inference_sft"
    data = {"tts_text": text.strip(), "spk_id": profile["speaker_id"]}
    reference_file = None
    files = None
    if profile["mode"] == "zero_shot":
        if not TTS_REFERENCE_PATH.exists():
            raise HTTPException(status_code=503, detail="Voice reference is not configured")
        endpoint = "/inference_zero_shot"
        data = {"tts_text": text.strip(), "prompt_text": profile["prompt_text"]}
        reference_file = TTS_REFERENCE_PATH.open("rb")
        files = {"prompt_wav": (TTS_REFERENCE_PATH.name, reference_file, "audio/wav")}

    async def pcm_stream():
        try:
            async with client.stream("POST", f"{COSYVOICE_URL}{endpoint}", data=data, files=files) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    if chunk:
                        yield chunk
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=503, detail="CosyVoice is unavailable") from exc
        finally:
            if reference_file:
                reference_file.close()

    return StreamingResponse(
        pcm_stream(),
        media_type="application/octet-stream",
        headers={"X-Audio-Format": "pcm_s16le", "X-Sample-Rate": str(TTS_SAMPLE_RATE)},
    )
