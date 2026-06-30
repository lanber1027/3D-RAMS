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

  useEffect(() => {
    if (!containerRef.current || !scene?.center) return undefined;

    Cesium.Ion.defaultAccessToken = "";
    const viewer = new Cesium.Viewer(containerRef.current, {
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

    return () => {
      if (!viewer.isDestroyed()) viewer.destroy();
    };
  }, [scene, annotations]);

  if (!scene) {
    return (
      <div className="empty-map">
        <MapPinned size={24} />
        <span>Map updates after the agent resolves a site.</span>
      </div>
    );
  }

  return (
    <div className="scene-shell">
      <div ref={containerRef} className="scene-viewer" />
      <div className="map-caption">
        <strong>{location?.label || "Selected site"}</strong>
        <span>{toList(annotations).length} mapped risk marker(s)</span>
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

function RiskCards({ hazards, briefing }) {
  const items = toList(hazards).slice(0, 6);
  return (
    <section className="panel">
      <div className="panel-heading">
        <AlertTriangle size={18} />
        <h2>Risk Review</h2>
      </div>
      <div className="risk-grid">
        {items.length ? (
          items.map((hazard) => (
            <article key={hazard.id || hazard.title}>
              <strong>{hazard.title}</strong>
              <em className={`status ${hazard.confidence || "warning"}`}>{hazard.confidence || "review"}</em>
              <p>{hazard.reason || hazard.summary || "Review this item before the site visit."}</p>
            </article>
          ))
        ) : (
          <p className="empty-copy">Risk cards appear after the agent runs tools.</p>
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
    if (["completed", "failed", "cancelled", "waiting_for_clarification"].includes(status.status) && !completedRunsRef.current.has(status.runId)) {
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

      <section className="insight-grid">
        <RiskCards hazards={ui.hazards} briefing={ui.briefing} />
        <EvidenceAndTrace evidence={ui.evidence} trace={ui.trace} safety={ui.safety} runtime={runtime} runStatus={runStatus} />
      </section>
    </main>
  );
}

export default App;
