from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .access import validate_access_code
from .agent import run_site_briefing
from .chat_agent import run_fieldbrief_chat
from .config import RuntimeConfig
from .durable_runner import cancel_durable_run, confirm_location_for_run, create_durable_run, read_durable_run
from .hosted_logging import log_event, now_ms
from .models import ChatRequest, HealthResponse, LocationConfirmRequest, RunCreateRequest, SessionStartRequest, SiteBriefRequest, UploadUrlRequest
from .session_store import create_session, get_session, public_session
from .upload_service import create_upload_target


app = FastAPI(title="3D-RAMS Hosted Pre-Visit Agent API", version="0.2.0")
_startup_config = RuntimeConfig.from_env(request_bedrock=False)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_startup_config.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
def health() -> dict[str, str]:
    return {"status": "ok", "service": "3d-rams-demo1"}


@app.post("/api/run")
def run_agent(payload: SiteBriefRequest, x_3drams_access: str | None = Header(default=None)) -> dict[str, object]:
    config = RuntimeConfig.from_env(request_bedrock=payload.useBedrock)
    if config.app_access_token_hash:
        validate_access_code(x_3drams_access, config)
    return run_site_briefing(payload.to_agent_request())


@app.post("/api/session/start")
def start_session(payload: SessionStartRequest) -> dict[str, object]:
    started = now_ms()
    config = RuntimeConfig.from_env(request_bedrock=False)
    access_label = validate_access_code(payload.accessCode, config)
    session = create_session(tester_alias=payload.testerAlias, access_label=access_label, config=config)
    log_event(
        "session_start",
        sessionId=session["sessionId"],
        accessLabel=access_label,
        testerAliasPresent=bool(payload.testerAlias),
        storageMode=session.get("storageMode", "memory"),
        latencyMs=now_ms() - started,
    )
    return {
        "sessionId": session["sessionId"],
        "testerAlias": session.get("testerAlias"),
        "accessLabel": session.get("accessLabel"),
        "runtime": {
            "hostedProductMode": True,
            "accessMode": "shared-code" if config.app_access_token_hash else "local-dev-open",
            "sessionTraceMode": session.get("storageMode", "memory"),
        },
    }


@app.post("/api/upload-url")
def create_upload_url(payload: UploadUrlRequest) -> dict[str, object]:
    started = now_ms()
    config = RuntimeConfig.from_env(request_bedrock=False)
    get_session(payload.sessionId, config)
    upload = create_upload_target(
        session_id=payload.sessionId,
        filename=payload.filename,
        content_type=payload.contentType,
        size_bytes=payload.sizeBytes,
        config=config,
    )
    from .session_store import add_upload

    add_upload(payload.sessionId, upload, config)
    log_event(
        "upload_url",
        sessionId=payload.sessionId,
        uploadId=upload.get("uploadId"),
        contentType=payload.contentType,
        sizeBytes=payload.sizeBytes,
        status=upload.get("status"),
        storageMode=upload.get("storageMode"),
        latencyMs=now_ms() - started,
    )
    return upload


@app.post("/api/chat")
def chat(payload: ChatRequest) -> dict[str, object]:
    started = now_ms()
    config = RuntimeConfig.from_env(request_bedrock=payload.useBedrock)
    get_session(payload.sessionId, config)
    log_event(
        "chat_start",
        sessionId=payload.sessionId,
        useBedrock=payload.useBedrock,
        messageLength=len(payload.message),
        uploadCount=len(payload.uploadedFileIds),
    )
    result = run_fieldbrief_chat(
        session_id=payload.sessionId,
        message=payload.message,
        uploaded_file_ids=payload.uploadedFileIds,
        use_bedrock=payload.useBedrock,
        config=config,
    )
    log_event(
        "chat_end",
        sessionId=payload.sessionId,
        runId=result.get("runId"),
        needsClarification=result.get("needsClarification"),
        safetyLevel=result.get("safety", {}).get("level"),
        fallbackStatus=result.get("fallback", {}).get("status"),
        modelCallCount=len(result.get("modelCalls", [])),
        latencyMs=now_ms() - started,
    )
    return result


@app.post("/api/runs", status_code=202)
def create_run(payload: RunCreateRequest) -> dict[str, object]:
    started = now_ms()
    config = RuntimeConfig.from_env(request_bedrock=payload.useBedrock)
    get_session(payload.sessionId, config)
    result = create_durable_run(
        session_id=payload.sessionId,
        message=payload.message,
        uploaded_file_ids=payload.uploadedFileIds,
        use_bedrock=payload.useBedrock,
        auto_start=payload.autoStart,
        config=config,
    )
    log_event(
        "durable_run_create",
        sessionId=payload.sessionId,
        runId=result.get("runId"),
        status=result.get("status"),
        autoStart=payload.autoStart,
        useBedrock=payload.useBedrock,
        latencyMs=now_ms() - started,
    )
    return result


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, object]:
    return read_durable_run(run_id)


@app.post("/api/runs/{run_id}/cancel")
def cancel_run(run_id: str) -> dict[str, object]:
    started = now_ms()
    result = cancel_durable_run(run_id)
    log_event(
        "durable_run_cancel",
        sessionId=result.get("sessionId"),
        runId=run_id,
        status=result.get("status"),
        latencyMs=now_ms() - started,
    )
    return result


@app.post("/api/runs/{run_id}/confirm-location", status_code=202)
def confirm_run_location(run_id: str, payload: LocationConfirmRequest) -> dict[str, object]:
    started = now_ms()
    config = RuntimeConfig.from_env(request_bedrock=True)
    try:
        result = confirm_location_for_run(run_id, payload.candidateId, config)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_event(
        "durable_run_location_confirm",
        sessionId=result.get("sessionId"),
        runId=run_id,
        status=result.get("status"),
        candidateId=payload.candidateId,
        latencyMs=now_ms() - started,
    )
    return result


@app.get("/api/session/{session_id}")
def read_session(session_id: str) -> dict[str, object]:
    config = RuntimeConfig.from_env(request_bedrock=False)
    return public_session(get_session(session_id, config))
