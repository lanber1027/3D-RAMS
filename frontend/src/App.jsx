import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  Bot,
  Cloud,
  FileUp,
  GitBranch,
  MapPinned,
  MessageSquare,
  RotateCcw,
  Send,
  ShieldCheck,
  X,
} from "lucide-react";
import * as Cesium from "cesium";
import "cesium/Build/Cesium/Widgets/widgets.css";

const AGENTCORE_URL = import.meta.env.VITE_AGENTCORE_URL || "/agentcore/invocations";
const LOCAL_ASIONE_URL = import.meta.env.VITE_LOCAL_ASIONE_URL || AGENTCORE_URL;
const STARTER_PROMPT =
  "I want to visit 8 Albert Embankment tomorrow for a survey. Please prepare a pre-visit RAMS-style review pack.";

const DEFAULT_REQUEST = {
  siteName: "8 Albert Embankment and land to the rear",
  latitude: 51.492099,
  longitude: -0.118712,
  goal: "Pre-visit RAMS scoping pack",
  fixturePack: "public-lambeth-thames",
  includePlanningFixture: true,
  simulateMapFailure: false,
  useBedrock: true,
  additionalRequest: "",
};

function toList(value) {
  return Array.isArray(value) ? value : [];
}

function runToUiState(run) {
  if (!run) return {};
  return {
    location: run.location,
    scene: run.scene,
    annotations: run.annotations,
    hazards: run.hazards,
    evidence: run.evidence,
    briefing: run.briefing,
    safety: run.safety,
    trace: run.trace,
  };
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
              <p>{hazard.reason || hazard.summary || hazard.note || "Review this item before the site visit."}</p>
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

function EvidenceAndTrace({ evidence, trace, safety, runtime }) {
  return (
    <section className="panel evidence-trace">
      <div className="panel-heading">
        <GitBranch size={18} />
        <h2>Evidence, Trace + Safety</h2>
      </div>
      <div className="runtime-strip">
        <article>
          <span>Mode</span>
          <strong>{runtime?.activeAgentMode || runtime?.entryAgentMode || "not run"}</strong>
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
          {toList(trace).map((step, index) => (
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
  const [request, setRequest] = useState(DEFAULT_REQUEST);
  const [prompt, setPrompt] = useState(STARTER_PROMPT);
  const [entryResponse, setEntryResponse] = useState(null);
  const [agentOpen, setAgentOpen] = useState(false);
  const [messages, setMessages] = useState([
    {
      id: "welcome",
      role: "assistant",
      text: "Tell me where you are going and what kind of site visit you are planning. I will ask for missing critical details, run tools, and return a RAMS-style review pack for human review.",
    },
  ]);
  const [uploads, setUploads] = useState([]);
  const [run, setRun] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const ui = entryResponse?.uiState || runToUiState(run);
  const runtime = entryResponse?.runtime || run?.runtime || {};
  const safetyTone = ui.safety?.allowed === false ? "blocked" : ui.safety?.level === "needs_input" ? "warning" : "allowed";

  async function sendToFieldBrief(nextPrompt = prompt, appendMessage = true) {
    const submittedText = nextPrompt.trim();
    if (!submittedText || loading) return;
    if (appendMessage) {
      setMessages((current) => [
        ...current,
        {
          id: `user-${Date.now()}`,
          role: "user",
          text: submittedText,
        },
      ]);
      setPrompt("");
    }
    setLoading(true);
    setError("");
    try {
      const response = await fetch(LOCAL_ASIONE_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          localAsiOne: true,
          sessionId: "local-demo-session",
          conversationId: "local-demo-session",
          message: submittedText,
          confirmedByUser: true,
          runtimeOptions: {
            ...request,
            materials: uploads.map((upload) => ({
              type: upload.type,
              label: upload.label,
              summary: upload.summary,
            })),
          },
        }),
      });
      if (!response.ok) throw new Error(`Agent run failed (${response.status})`);
      const payload = await response.json();
      const nextEntryResponse = payload.output?.localAsiOne || null;
      setEntryResponse(nextEntryResponse);
      if (nextEntryResponse) {
        setMessages((current) => [
          ...current,
          {
            id: nextEntryResponse.runId || `assistant-${Date.now()}`,
            role: "assistant",
            text: nextEntryResponse.assistantMessage,
            questions: nextEntryResponse.clarifyingQuestions || [],
          },
        ]);
      }
      if (nextEntryResponse?.needsClarification || nextEntryResponse?.needsConfirmation) {
        setAgentOpen(true);
        setRun(null);
        return;
      }
      const nextRun = nextEntryResponse?.run || payload.output?.run;
      if (!nextRun) throw new Error("Local ASI:ONE response did not include a supervisor run");
      setRun(nextRun);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  function sendMessage(event) {
    event.preventDefault();
    sendToFieldBrief(prompt, true);
  }

  function registerMockUpload() {
    setUploads((current) => [
      ...current,
      {
        id: `local-upload-${current.length + 1}`,
        type: "application/pdf",
        label: `Test evidence ${current.length + 1}`,
        summary: "Local demo evidence metadata registered by the FieldBrief Agent.",
      },
    ]);
  }

  function resetDemo() {
    setRequest(DEFAULT_REQUEST);
    setPrompt(STARTER_PROMPT);
    setMessages([
      {
        id: "welcome",
        role: "assistant",
        text: "Tell me where you are going and what kind of site visit you are planning. I will ask for missing critical details, run tools, and return a RAMS-style review pack for human review.",
      },
    ]);
    setUploads([]);
    sendToFieldBrief(STARTER_PROMPT, false);
  }

  useEffect(() => {
    sendToFieldBrief(STARTER_PROMPT, false);
  }, []);

  return (
    <main className="app-shell product-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">3D-RAMS Local Agent</p>
          <h1>Pre-Visit FieldBrief Agent</h1>
          <p className="topbar-summary">
            Ask for a site visit review pack in normal language. The agent runs supervisor tools and returns map, evidence, trace, and safety output.
          </p>
        </div>
        <div className="status-stack">
          <button className="secondary" onClick={() => setAgentOpen(true)}>
            <MessageSquare size={16} />
            FieldBrief Agent
          </button>
          <button className="icon-button" aria-label="Reset request" onClick={resetDemo}>
            <RotateCcw size={16} />
          </button>
          <div className={`safety-pill ${safetyTone}`}>
            <ShieldCheck size={16} />
            {ui.safety?.level || "ready"}
          </div>
          <div className="safety-pill pending">
            <Cloud size={16} />
            {runtime.sessionTraceMode || runtime.supervisorRuntime || "local"}
          </div>
        </div>
      </header>

      {agentOpen && (
        <div className="agent-modal-backdrop" role="presentation">
          <section className="agent-modal agent-chat panel" role="dialog" aria-modal="true" aria-labelledby="fieldbrief-title">
            <div className="panel-heading agent-chat-heading">
              <Bot size={18} />
              <h2 id="fieldbrief-title">FieldBrief Agent</h2>
              <button className="icon-button" aria-label="Collapse FieldBrief Agent" onClick={() => setAgentOpen(false)}>
                <X size={16} />
              </button>
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
              <button className="secondary" type="button" onClick={registerMockUpload}>
                <FileUp size={16} />
                Register test PDF/image
              </button>
              <span>{uploads.length ? `${uploads.length} evidence file(s) registered` : "Uploads use S3 when hosted; local mode registers metadata only."}</span>
            </div>
            <form className="composer" onSubmit={sendMessage}>
              <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} />
              <button disabled={loading || !prompt.trim()}>
                <Send size={16} />
                {loading ? "Running" : "Send"}
              </button>
            </form>
          </section>
        </div>
      )}

      {error && <div className="error-banner">{error}</div>}

      <section className="product-grid report-only">
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
        <EvidenceAndTrace evidence={ui.evidence} trace={ui.trace} safety={ui.safety} runtime={runtime} />
      </section>
    </main>
  );
}

export default App;
