import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Bot,
  Cloud,
  FileUp,
  GitBranch,
  KeyRound,
  MapPinned,
  RefreshCw,
  Send,
  ShieldCheck,
  Square,
} from "lucide-react";
import * as Cesium from "cesium";
import "cesium/Build/Cesium/Widgets/widgets.css";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "";
const STARTER_PROMPT =
  "I want to visit 8 Albert Embankment tomorrow for a survey. Please prepare a pre-visit RAMS-style review pack.";

function toList(value) {
  return Array.isArray(value) ? value : [];
}

function SceneViewer({ scene, annotations, location }) {
  const containerRef = useRef(null);
  const [renderError, setRenderError] = useState("");
  const [renderStatus, setRenderStatus] = useState("waiting for confirmed location");

  useEffect(() => {
    setRenderError("");
    setRenderStatus(scene?.center ? "rendering 3D scene" : "waiting for confirmed location");
    if (!containerRef.current || !scene?.center) return undefined;

    Cesium.Ion.defaultAccessToken = "";
    let viewer;
    try {
      viewer = new Cesium.Viewer(containerRef.current, {
        animation: false,
        timeline: false,
        baseLayer: false,
        geocoder: false,
        homeButton: false,
        sceneModePicker: false,
        baseLayerPicker: false,
        navigationHelpButton: false,
        fullscreenButton: false,
        infoBox: false,
        selectionIndicator: false,
      });

      viewer.scene.globe.baseColor = Cesium.Color.fromCssColorString("#e6ece9");
      viewer.scene.skyAtmosphere.show = false;
      viewer.scene.fog.enabled = false;

      const center = scene.center;
      viewer.entities.add({
        name: "Review area",
        polygon: {
          hierarchy: Cesium.Cartesian3.fromDegreesArray([
            center.longitude - 0.006,
            center.latitude - 0.004,
            center.longitude + 0.006,
            center.latitude - 0.004,
            center.longitude + 0.006,
            center.latitude + 0.004,
            center.longitude - 0.006,
            center.latitude + 0.004,
          ]),
          height: 0,
          material: Cesium.Color.fromCssColorString("#7fb9a7").withAlpha(0.36),
          outline: true,
          outlineColor: Cesium.Color.fromCssColorString("#0b6f65"),
        },
      });

      toList(annotations).forEach((annotation) => {
        viewer.entities.add({
          name: annotation.title,
          position: Cesium.Cartesian3.fromDegrees(annotation.longitude, annotation.latitude, 24),
          point: {
            pixelSize: annotation.confidence === "low" ? 12 : 10,
            color: Cesium.Color.fromCssColorString(annotation.confidence === "low" ? "#d97706" : "#1d4ed8"),
            outlineColor: Cesium.Color.WHITE,
            outlineWidth: 2,
          },
          label: {
            text: annotation.title,
            font: "12px sans-serif",
            fillColor: Cesium.Color.fromCssColorString("#111827"),
            showBackground: true,
            backgroundColor: Cesium.Color.WHITE.withAlpha(0.84),
            pixelOffset: new Cesium.Cartesian2(0, -22),
          },
        });
      });

      viewer.camera.flyTo({
        destination: Cesium.Cartesian3.fromDegrees(center.longitude, center.latitude, 1500),
        orientation: {
          heading: Cesium.Math.toRadians(scene.camera?.headingDegrees || 0),
          pitch: Cesium.Math.toRadians(scene.camera?.pitchDegrees || -48),
        },
        duration: 0,
      });
      setRenderStatus("3D scene rendered");
    } catch (err) {
      setRenderError(err?.message || "3D scene renderer failed.");
      setRenderStatus("3D scene unavailable");
      if (viewer && !viewer.isDestroyed()) viewer.destroy();
      viewer = null;
    }

    return () => {
      if (viewer && !viewer.isDestroyed()) viewer.destroy();
    };
  }, [scene, annotations]);

  if (!scene) {
    return (
      <div className="empty-map">
        <MapPinned size={24} />
        <strong>waiting for confirmed location</strong>
        <span>Confirm a candidate site or provide a coordinate, postcode, nearest town, or supported fixture before the map tools run.</span>
      </div>
    );
  }

  if (renderError) {
    return (
      <div className="scene-fallback">
        <div className="map-status unavailable">3D scene unavailable</div>
        <MapPinned size={28} />
        <h3>{location?.label || "Selected site"}</h3>
        <p>{renderError}</p>
        {scene.center && (
          <dl>
            <div>
              <dt>Coordinate</dt>
              <dd>{scene.center.latitude}, {scene.center.longitude}</dd>
            </div>
            <div>
              <dt>Risk markers</dt>
              <dd>{toList(annotations).length}</dd>
            </div>
          </dl>
        )}
      </div>
    );
  }

  return (
    <div className="scene-shell">
      <div className={`map-status ${renderStatus === "3D scene rendered" ? "rendered" : "pending"}`}>{renderStatus}</div>
      <div ref={containerRef} className="scene-viewer" />
      <div className="map-caption">
        <strong>{location?.label || "Selected site"}</strong>
        <span>{toList(annotations).length} mapped risk marker(s)</span>
        {(location?.confidence || location?.dataMode) && (
          <small>{[location.confidence, location.dataMode].filter(Boolean).join(" - ")}</small>
        )}
      </div>
    </div>
  );
}

function CandidateMapPreview({ candidate }) {
  const latitude = Number(candidate?.latitude);
  const longitude = Number(candidate?.longitude);
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return null;
  const context = candidate.locationContext || {};
  const submitted = context.submittedLocation;
  const bboxPadding = 0.035;
  const bbox = [
    longitude - bboxPadding,
    latitude - bboxPadding,
    longitude + bboxPadding,
    latitude + bboxPadding,
  ].map((value) => value.toFixed(6)).join(",");
  const marker = `${latitude.toFixed(6)},${longitude.toFixed(6)}`;
  const mapSrc = `https://www.openstreetmap.org/export/embed.html?bbox=${encodeURIComponent(bbox)}&layer=mapnik&marker=${encodeURIComponent(marker)}`;
  const mapLink = `https://www.openstreetmap.org/?mlat=${latitude.toFixed(6)}&mlon=${longitude.toFixed(6)}#map=15/${latitude.toFixed(6)}/${longitude.toFixed(6)}`;
  return (
    <div className="candidate-map-preview">
      <div className="candidate-map-canvas" aria-label="Candidate location preview">
        <iframe
          className="candidate-map-frame"
          title={`Map preview for ${candidate.name || "candidate site"}`}
          src={mapSrc}
          loading="lazy"
          referrerPolicy="no-referrer-when-downgrade"
        />
        <div className="candidate-map-source">
          OpenStreetMap preview - confirm before tools run
        </div>
      </div>
      <div className="candidate-map-summary">
        <strong>{candidate.name || "Candidate site"}</strong>
        <span>{candidate.relativeLocation || context.summary || "Location context pending"}</span>
        <dl>
          <div>
            <dt>{submitted?.type || "input"}</dt>
            <dd>{submitted?.value || `${candidate.latitude}, ${candidate.longitude}`}</dd>
          </div>
          <div>
            <dt>coordinate</dt>
            <dd>{latitude.toFixed(6)}, {longitude.toFixed(6)}</dd>
          </div>
        </dl>
        <a href={mapLink} target="_blank" rel="noreferrer">Open larger map</a>
      </div>
    </div>
  );
}

function AccessPanel({ onStart, loading }) {
  const [accessCode, setAccessCode] = useState("");
  const [testerAlias, setTesterAlias] = useState(localStorage.getItem("3drams-tester-alias") || "");

  async function submit(event) {
    event.preventDefault();
    localStorage.setItem("3drams-tester-alias", testerAlias);
    onStart({ accessCode, testerAlias });
  }

  return (
    <section className="access-panel">
      <div>
        <p className="eyebrow">Hosted Agent MVP</p>
        <h1>3D-RAMS Pre-Visit Agent</h1>
        <p>
          Enter the test access code, then ask for a site-visit risk briefing in normal language.
          Bedrock access stays server-side.
        </p>
      </div>
      <form onSubmit={submit}>
        <label>
          Access code
          <input
            value={accessCode}
            onChange={(event) => setAccessCode(event.target.value)}
            placeholder="Leave blank for local dev"
            type="password"
          />
        </label>
        <label>
          Tester alias
          <input
            value={testerAlias}
            onChange={(event) => setTesterAlias(event.target.value)}
            placeholder="Optional, e.g. teammate-a"
          />
        </label>
        <button disabled={loading}>
          <KeyRound size={16} />
          {loading ? "Starting" : "Start test session"}
        </button>
      </form>
    </section>
  );
}

function ChatPanel({ messages, prompt, setPrompt, onSend, loading, uploads, onMockUpload, activeRun, onCancel }) {
  return (
    <section className="agent-chat panel">
      <div className="panel-heading">
        <Bot size={18} />
        <h2>FieldBrief Agent</h2>
      </div>
      <div className="message-list">
        {messages.map((message) => (
          <article className={`message ${message.role}`} key={message.id}>
            <span>{message.role === "user" ? "You" : "3D-RAMS Agent"}</span>
            <p>{message.text}</p>
            {message.questions?.length > 0 && (
              <ul>
                {message.questions.map((question) => (
                  <li key={question}>{question}</li>
                ))}
              </ul>
            )}
          </article>
        ))}
      </div>
      <div className="upload-strip">
        <button className="secondary" type="button" onClick={onMockUpload}>
          <FileUp size={16} />
          Register test PDF/image
        </button>
        <span>{uploads.length ? `${uploads.length} evidence file(s) registered` : "Uploads use S3 when hosted; local mode registers metadata only."}</span>
      </div>
      <form className="composer" onSubmit={onSend}>
        <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} />
        {activeRun && ["queued", "running"].includes(activeRun.status) && (
          <button className="danger" type="button" onClick={onCancel}>
            <Square size={16} />
            Cancel
          </button>
        )}
        <button disabled={loading || !prompt.trim()}>
          <Send size={16} />
          {loading ? "Queued" : "Send"}
        </button>
      </form>
    </section>
  );
}

function RiskCards({ hazards, briefing, reviewMode }) {
  const items = toList(hazards).slice(0, 6);
  const confidenceLabel = (confidence) => `${confidence || "review"} confidence`;
  return (
    <section className="panel">
      <div className="panel-heading">
        <AlertTriangle size={18} />
        <h2>Risk Review</h2>
      </div>
      {reviewMode && (
        <div className={`review-mode ${reviewMode.includes("provisional") ? "provisional" : ""}`}>
          {reviewMode}
        </div>
      )}
      <div className="risk-grid">
        {items.length ? (
          items.map((hazard) => (
            <article key={hazard.id || hazard.title}>
              <strong>{hazard.title}</strong>
              <em className={`status ${hazard.confidence || "warning"}`}>{hazard.confidence || "review"}</em>
              <p>{hazard.reason || hazard.summary || hazard.note || "Review this item before the site visit."}</p>
              <small>{hazard.dataMode || hazard.source || "source pending"}</small>
            </article>
          ))
        ) : (
          <p className="empty-copy">Risk cards appear after the agent runs tools.</p>
        )}
      </div>
      <div className="risk-factor-panel">
        <h3>Risk Factors</h3>
        {items.length ? (
          <div className="risk-factor-list">
            {items.map((hazard) => (
              <article key={`factor-${hazard.id || hazard.title}`}>
                <strong>{hazard.title}</strong>
                <span>{confidenceLabel(hazard.confidence)}</span>
                <p>{(hazard.sourceIds || hazard.evidenceIds || []).join(", ") || hazard.source || "source pending"} - human review required</p>
              </article>
            ))}
          </div>
        ) : (
          <p className="empty-copy">Risk factors appear once hazards have evidence links.</p>
        )}
      </div>
      {briefing && (
        <div className="briefing-block">
          <h3>{briefing.headline}</h3>
          <ul>
            {toList(briefing.priority_checks).map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function LocationConfirmationPanel({ resolution, onConfirm, onReject, onManual, loading }) {
  if (!resolution?.siteName && !toList(resolution?.locationCandidates).length) return null;
  const candidates = toList(resolution.locationCandidates);
  const primaryCandidate = candidates[0];
  return (
    <section className="panel location-confirmation-panel">
      <div className="panel-heading">
        <MapPinned size={18} />
        <h2>Confirm Site Location</h2>
      </div>
      <p className="confirmation-copy">
        {candidates.length
          ? "The agent found source-labelled candidate locations. Confirm one before map, evidence, risk, or briefing tools run."
          : "The agent searched the cached/source resolver but did not find a reliable candidate. Any risk prompts shown below are provisional and not site-specific evidence."}
      </p>
      <CandidateMapPreview candidate={primaryCandidate} />
      {candidates.length > 0 ? (
        <div className="candidate-grid">
          {candidates.map((candidate) => (
            <article key={candidate.candidateId} className="candidate-card">
              <div>
                <strong>{candidate.name}</strong>
                <span>{candidate.confidence || "review"} confidence</span>
              </div>
              <dl>
                <div>
                  <dt>Nearest town/road</dt>
                  <dd>{candidate.nearestTown || candidate.nearestRoad || candidate.locationContext?.nearestTown || "not available"}</dd>
                </div>
                <div>
                  <dt>Authority</dt>
                  <dd>{candidate.countyOrAuthority || "not available"}</dd>
                </div>
                <div>
                  <dt>Postcode area</dt>
                  <dd>{candidate.postcodeArea || "not available"}</dd>
                </div>
                <div>
                  <dt>Approx coordinate</dt>
                  <dd>{candidate.latitude}, {candidate.longitude}</dd>
                </div>
                <div>
                  <dt>Ward/parish</dt>
                  <dd>{candidate.ward || candidate.parish || "not available"}</dd>
                </div>
                <div>
                  <dt>Region</dt>
                  <dd>{candidate.region || candidate.locationContext?.region || "not available"}</dd>
                </div>
                <div>
                  <dt>Relative position</dt>
                  <dd>{candidate.relativeLocation || candidate.locationContext?.relativeLocation || "not available"}</dd>
                </div>
              </dl>
              <p>{candidate.reason || "Candidate requires human confirmation before use."}</p>
              <small>{candidate.source || "source pending"} - {candidate.dataMode || "source-labelled"}</small>
              <div className="candidate-actions">
                <button type="button" onClick={() => onConfirm(candidate.candidateId)} disabled={loading}>
                  Confirm this site
                </button>
                <button className="secondary" type="button" onClick={onReject} disabled={loading}>
                  Not this site
                </button>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <p className="empty-copy">No reliable cached/public candidate was found for {resolution.siteName}. The site-specific review workflow has not started.</p>
      )}
      <button className="secondary" type="button" onClick={onManual} disabled={loading}>
        Enter coordinates manually
      </button>
    </section>
  );
}

function RunStatusBar({ runStatus, onResume, canResume }) {
  const status = runStatus?.status || "ready";
  const latestStep = runStatus?.currentStep || "not started";
  const modelCalls = runStatus?.modelCallsUsed ?? 0;
  const maxModelCalls = runStatus?.maxModelCalls ?? 0;
  const maxToolCalls = runStatus?.maxToolCalls ?? 0;
  return (
    <section className="run-status-bar">
      <article>
        <span>Run status</span>
        <strong>{status}</strong>
      </article>
      <article>
        <span>Latest step</span>
        <strong>{latestStep}</strong>
      </article>
      <article>
        <span>Model calls</span>
        <strong>{modelCalls}/{maxModelCalls}</strong>
      </article>
      <article>
        <span>Tool cap</span>
        <strong>{maxToolCalls || "ready"}</strong>
      </article>
      {canResume && (
        <button className="secondary" type="button" onClick={onResume}>
          <RefreshCw size={16} />
          Resume latest run
        </button>
      )}
    </section>
  );
}

function EvidenceAndTrace({ evidence, trace, safety, runtime, runStatus }) {
  const lifecycleTrace = toList(runStatus?.steps);
  const toolTrace = toList(trace);
  const visibleTrace = lifecycleTrace.length ? [...lifecycleTrace, ...toolTrace] : toolTrace;
  return (
    <section className="panel evidence-trace">
      <div className="panel-heading">
        <GitBranch size={18} />
        <h2>Evidence, Trace + Safety</h2>
      </div>
      <div className="runtime-strip">
        <article>
          <span>Mode</span>
          <strong>{runtime?.activeAgentMode || "not run"}</strong>
        </article>
        <article>
          <span>Briefing</span>
          <strong>{runtime?.briefingMode || "not run"}</strong>
        </article>
        <article>
          <span>Safety</span>
          <strong>{safety?.level || "not run"}</strong>
        </article>
      </div>
      <div className="evidence-trace-grid">
        <div>
          <h3>Evidence Register</h3>
          {toList(evidence).map((item) => (
            <article className="compact-row" key={item.id}>
              <strong>{item.title}</strong>
              <span>{item.source}</span>
              <small>{item.status}</small>
            </article>
          ))}
        </div>
        <div>
          <h3>Tool Timeline</h3>
          {visibleTrace.map((step, index) => (
            <article className="compact-row trace" key={`${step.name}-${index}`}>
              <strong>{String(index + 1).padStart(2, "0")} · {step.name}</strong>
              <span>{step.summary}</span>
              <small>{step.status}</small>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

function App() {
  const [session, setSession] = useState(null);
  const [messages, setMessages] = useState([
    {
      id: "welcome",
      role: "assistant",
      text: "Tell me where you are going and what kind of site visit you are planning. I will ask for missing critical details, run tools, and return a RAMS-style review pack for human review.",
    },
  ]);
  const [prompt, setPrompt] = useState(STARTER_PROMPT);
  const [run, setRun] = useState(null);
  const [runStatus, setRunStatus] = useState(null);
  const [uploads, setUploads] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const completedRunsRef = useRef(new Set());

  const ui = run?.uiState || {};
  const accessLabel = session?.accessLabel || "not started";
  const runtime = run?.runtime || {};
  const locationResolution = run?.locationResolution || ui.locationResolution || null;
  const reviewMode = ui.reviewMode || (runStatus && ["queued", "running"].includes(runStatus.status) ? "new run in progress" : null);
  const safetyTone = ui.safety?.allowed === false ? "blocked" : ui.safety?.level === "needs_input" ? "warning" : "allowed";

  async function startSession(payload) {
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE_URL}/api/session/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) throw new Error(`Session start failed (${response.status})`);
      const nextSession = await response.json();
      setSession(nextSession);
      localStorage.setItem("3drams-session", JSON.stringify(nextSession));
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function sendMessage(event) {
    event.preventDefault();
    if (!prompt.trim() || !session) return;
    const userMessage = { id: `user-${Date.now()}`, role: "user", text: prompt.trim() };
    setMessages((current) => [...current, userMessage]);
    setPrompt("");
    setRun({
      runId: "pending",
      assistantMessage: "Run queued.",
      uiState: {
        location: null,
        scene: null,
        annotations: [],
        hazards: [],
        evidence: [],
        sources: [],
        briefing: null,
        safety: { allowed: true, level: "running", message: "New run is executing." },
        trace: [],
        architecture: null,
        locationResolution: null,
        reviewMode: "new run in progress",
      },
      runtime: { activeAgentMode: "queued", briefingMode: "not-run" },
      trace: [],
      evidence: [],
      scene: null,
      annotations: [],
      briefing: null,
      safety: { allowed: true, level: "running", message: "New run is executing." },
    });
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE_URL}/api/runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sessionId: session.sessionId,
          message: userMessage.text,
          uploadedFileIds: uploads.map((upload) => upload.uploadId),
          useBedrock: true,
          autoStart: true,
        }),
      });
      if (!response.ok) throw new Error(`Agent run failed (${response.status})`);
      const status = await response.json();
      localStorage.setItem("3drams-latest-run", status.runId);
      applyRunStatus(status);
    } catch (err) {
      setError(err.message);
      setLoading(false);
    }
  }

  async function fetchRunStatus(runId) {
    const response = await fetch(`${API_BASE_URL}/api/runs/${runId}`);
    if (response.status === 404) {
      localStorage.removeItem("3drams-latest-run");
      throw new Error("Run not found. Start a fresh session if the backend restarted.");
    }
    if (!response.ok) throw new Error(`Run status failed (${response.status})`);
    return response.json();
  }

  function applyRunStatus(status) {
    setRunStatus(status);
    const result = status.result || {
      sessionId: status.sessionId,
      runId: status.runId,
      assistantMessage: status.errorSummary?.message || `Run ${status.status}: ${status.currentStep}`,
      needsClarification: status.status === "waiting_for_clarification",
      clarifyingQuestions: status.result?.clarifyingQuestions || [],
      uiState: status.finalUiState || status.partialUiState || {},
      runtime: status.runtime || {},
      trace: status.partialUiState?.trace || status.steps || [],
      evidence: status.partialUiState?.evidence || [],
      scene: status.partialUiState?.scene || null,
      annotations: status.partialUiState?.annotations || [],
      briefing: status.partialUiState?.briefing || null,
      safety: status.partialUiState?.safety || null,
      modelCalls: [],
      tokenUsage: null,
    };
    setRun(result);
    if (["completed", "failed", "cancelled", "waiting_for_clarification", "waiting_for_location_confirmation"].includes(status.status) && !completedRunsRef.current.has(status.runId)) {
      completedRunsRef.current.add(status.runId);
      setMessages((current) => [
        ...current,
        {
          id: status.runId,
          role: "assistant",
          text: result.assistantMessage,
          questions: result.clarifyingQuestions || [],
        },
      ]);
    }
    if (!["queued", "running"].includes(status.status)) {
      setLoading(false);
    }
  }

  async function resumeLatestRun() {
    const runId = localStorage.getItem("3drams-latest-run");
    if (!runId) return;
    setLoading(true);
    setError("");
    try {
      applyRunStatus(await fetchRunStatus(runId));
    } catch (err) {
      setError(err.message);
      setLoading(false);
    }
  }

  async function cancelActiveRun() {
    if (!runStatus?.runId) return;
    setError("");
    try {
      const response = await fetch(`${API_BASE_URL}/api/runs/${runStatus.runId}/cancel`, { method: "POST" });
      if (!response.ok) throw new Error(`Cancel failed (${response.status})`);
      applyRunStatus(await response.json());
    } catch (err) {
      setError(err.message);
    }
  }

  async function confirmLocation(candidateId) {
    if (!runStatus?.runId) return;
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE_URL}/api/runs/${runStatus.runId}/confirm-location`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ candidateId }),
      });
      if (!response.ok) throw new Error(`Location confirmation failed (${response.status})`);
      applyRunStatus(await response.json());
    } catch (err) {
      setError(err.message);
      setLoading(false);
    }
  }

  function rejectLocationCandidate() {
    setPrompt("This is not the right site. The corrected postcode, latitude/longitude, OS grid reference, nearest road/town, or public evidence is ");
  }

  function enterCoordinatesManually() {
    const siteName = locationResolution?.siteName || "the site";
    setPrompt(`I want to visit ${siteName} at <latitude>, <longitude> tomorrow for a survey. Please prepare a pre-visit RAMS-style review pack.`);
  }

  async function registerMockUpload() {
    if (!session) return;
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE_URL}/api/upload-url`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sessionId: session.sessionId,
          filename: `test-evidence-${uploads.length + 1}.pdf`,
          contentType: "application/pdf",
          sizeBytes: 2048,
        }),
      });
      if (response.status === 404) {
        localStorage.removeItem("3drams-session");
        throw new Error("Session not found. Refresh and start a new test session.");
      }
      if (!response.ok) throw new Error(`Upload registration failed (${response.status})`);
      const upload = await response.json();
      setUploads((current) => [...current, upload]);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (session) return;
    const cachedSession = localStorage.getItem("3drams-session");
    if (cachedSession) {
      try {
        setSession(JSON.parse(cachedSession));
        return;
      } catch {
        localStorage.removeItem("3drams-session");
      }
    }
    const cachedAlias = localStorage.getItem("3drams-tester-alias") || "";
    if (import.meta.env.DEV) {
      startSession({ accessCode: "", testerAlias: cachedAlias });
    }
  }, [session]);

  useEffect(() => {
    if (!runStatus?.runId || !["queued", "running"].includes(runStatus.status)) return undefined;
    const timer = window.setInterval(async () => {
      try {
        applyRunStatus(await fetchRunStatus(runStatus.runId));
      } catch (err) {
        setError(err.message);
        setLoading(false);
        window.clearInterval(timer);
      }
    }, 1300);
    return () => window.clearInterval(timer);
  }, [runStatus?.runId, runStatus?.status]);

  if (!session) {
    return (
      <main className="app-shell">
        {error && <div className="error-banner">{error}</div>}
        <AccessPanel onStart={startSession} loading={loading} />
      </main>
    );
  }

  return (
    <main className="app-shell product-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">3D-RAMS Hosted Agent</p>
          <h1>Pre-Visit FieldBrief Agent</h1>
          <p className="topbar-summary">
            Ask for a site visit review pack in normal language. The agent runs server-side tools and returns map, evidence, trace, and safety output.
          </p>
        </div>
        <div className="status-stack">
          <div className="safety-pill pending">
            <KeyRound size={16} />
            {accessLabel}
          </div>
          <div className={`safety-pill ${safetyTone}`}>
            <ShieldCheck size={16} />
            {ui.safety?.level || "ready"}
          </div>
          <div className="safety-pill pending">
            <Cloud size={16} />
            {runtime.sessionTraceMode || "memory"}
          </div>
        </div>
      </header>

      {error && <div className="error-banner">{error}</div>}

      <RunStatusBar
        runStatus={runStatus}
        onResume={resumeLatestRun}
        canResume={Boolean(localStorage.getItem("3drams-latest-run"))}
      />

      <section className="product-grid">
        <ChatPanel
          messages={messages}
          prompt={prompt}
          setPrompt={setPrompt}
          onSend={sendMessage}
          loading={loading}
          uploads={uploads}
          onMockUpload={registerMockUpload}
          activeRun={runStatus}
          onCancel={cancelActiveRun}
        />
        <section className="panel map-panel">
          <div className="panel-heading">
            <MapPinned size={18} />
            <h2>3D Site Risk Scene</h2>
          </div>
          <SceneViewer scene={ui.scene} annotations={ui.annotations} location={ui.location} />
        </section>
      </section>

      <LocationConfirmationPanel
        resolution={locationResolution}
        onConfirm={confirmLocation}
        onReject={rejectLocationCandidate}
        onManual={enterCoordinatesManually}
        loading={loading}
      />

      <section className="insight-grid">
        <RiskCards hazards={ui.hazards} briefing={ui.briefing} reviewMode={reviewMode} />
        <EvidenceAndTrace evidence={ui.evidence} trace={ui.trace} safety={ui.safety} runtime={runtime} runStatus={runStatus} />
      </section>
    </main>
  );
}

export default App;
