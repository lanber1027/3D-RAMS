import { useEffect, useMemo, useRef, useState } from "react";
import { Bot, FileUp, GitBranch, MessageSquare, Play, RotateCcw, Send, ShieldCheck, X } from "lucide-react";
import * as Cesium from "cesium";
import "cesium/Build/Cesium/Widgets/widgets.css";

const AGENTCORE_URL = import.meta.env.VITE_AGENTCORE_URL || "/agentcore/invocations";
const LOCAL_ASIONE_URL = import.meta.env.VITE_LOCAL_ASIONE_URL || AGENTCORE_URL;

const DEFAULT_MESSAGE =
  "Please prepare a pre-visit site review near 8 Albert Embankment, Lambeth within an 800 metre area for flood context, access, and public interface constraints.";

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

function SceneViewer({ run }) {
  const containerRef = useRef(null);
  const overlayPoints = useMemo(
    () =>
      (run?.annotations || []).slice(0, 6).map((annotation, index) => ({
        annotation,
        left: `${18 + ((index * 13) % 58)}%`,
        top: `${24 + ((index * 17) % 44)}%`,
      })),
    [run],
  );

  useEffect(() => {
    if (!containerRef.current || !run) return undefined;

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

    viewer.scene.globe.baseColor = Cesium.Color.fromCssColorString("#e8eee9");
    viewer.scene.skyAtmosphere.show = false;
    viewer.scene.fog.enabled = false;

    const center = run.scene.center;
    const sitePolygon = [
      center.longitude - 0.006,
      center.latitude - 0.004,
      center.longitude + 0.006,
      center.latitude - 0.004,
      center.longitude + 0.006,
      center.latitude + 0.004,
      center.longitude - 0.006,
      center.latitude + 0.004,
    ];
    viewer.entities.add({
      name: "Review area",
      polygon: {
        hierarchy: Cesium.Cartesian3.fromDegreesArray(sitePolygon),
        height: 0,
        material: Cesium.Color.fromCssColorString("#87b7a7").withAlpha(0.38),
        outline: true,
        outlineColor: Cesium.Color.fromCssColorString("#0b6f65"),
      },
    });
    viewer.entities.add({
      name: "Indicative access route",
      polyline: {
        positions: Cesium.Cartesian3.fromDegreesArray([
          center.longitude - 0.007,
          center.latitude - 0.003,
          center.longitude - 0.002,
          center.latitude,
          center.longitude + 0.004,
          center.latitude + 0.002,
        ]),
        width: 4,
        material: Cesium.Color.fromCssColorString("#273549"),
      },
    });
    viewer.entities.add({
      name: "Indicative watercourse",
      polyline: {
        positions: Cesium.Cartesian3.fromDegreesArray([
          center.longitude - 0.006,
          center.latitude + 0.003,
          center.longitude - 0.001,
          center.latitude + 0.001,
          center.longitude + 0.006,
          center.latitude + 0.003,
        ]),
        width: 3,
        material: Cesium.Color.fromCssColorString("#1d4ed8"),
      },
    });
    viewer.entities.add({
      name: run.location.label,
      position: Cesium.Cartesian3.fromDegrees(center.longitude, center.latitude, 30),
      point: { pixelSize: 14, color: Cesium.Color.fromCssColorString("#0b6f65") },
      label: {
        text: "Site",
        font: "14px sans-serif",
        fillColor: Cesium.Color.WHITE,
        outlineColor: Cesium.Color.BLACK,
        outlineWidth: 2,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        pixelOffset: new Cesium.Cartesian2(0, -24),
      },
    });

    run.annotations.forEach((annotation) => {
      const color = annotation.confidence === "low" ? "#d97706" : "#1d4ed8";
      viewer.entities.add({
        name: annotation.title,
        position: Cesium.Cartesian3.fromDegrees(annotation.longitude, annotation.latitude, 24),
        point: {
          pixelSize: annotation.confidence === "low" ? 11 : 10,
          color: Cesium.Color.fromCssColorString(color),
          outlineColor: Cesium.Color.WHITE,
          outlineWidth: 2,
        },
        label: {
          text: annotation.title,
          font: "12px sans-serif",
          fillColor: Cesium.Color.fromCssColorString("#111827"),
          showBackground: true,
          backgroundColor: Cesium.Color.WHITE.withAlpha(0.82),
          pixelOffset: new Cesium.Cartesian2(0, -22),
        },
      });
    });

    viewer.camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(center.longitude, center.latitude, 1500),
      orientation: {
        heading: Cesium.Math.toRadians(run.scene.camera.headingDegrees),
        pitch: Cesium.Math.toRadians(run.scene.camera.pitchDegrees),
      },
      duration: 0,
    });

    return () => {
      if (!viewer.isDestroyed()) viewer.destroy();
    };
  }, [run]);

  return (
    <div className="scene-shell" aria-label="3D site scene">
      <div ref={containerRef} className="scene-viewer" />
      <div className="scene-overlay" aria-hidden="true">
        <div className="review-area" />
        <div className="route-line" />
        <div className="water-line" />
        <div className="scene-label site-label">Site</div>
        <div className="scene-label route-label">Access route</div>
        <div className="scene-label water-label">Watercourse</div>
        {overlayPoints.map(({ annotation, left, top }) => (
          <div
            className={`hazard-marker ${annotation.confidence}`}
            key={annotation.id}
            style={{ left, top }}
            title={`${annotation.title}: ${annotation.confidence} confidence`}
          >
            <span>{annotation.title}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function WorkflowVisualizer({ architecture }) {
  if (!architecture) return null;
  const overview = architecture.runOverview;
  const sourceById = Object.fromEntries((architecture.sources || []).map((source) => [source.id, source]));

  return (
    <section className="panel visualizer">
      <div className="panel-heading">
        <GitBranch size={18} />
        <h2>Architecture + Workflow</h2>
      </div>

      <div className="run-overview">
        <div>
          <span>Query</span>
          <strong>{overview.goal}</strong>
          <small>{overview.siteName}</small>
        </div>
        <div>
          <span>Coordinate</span>
          <strong>{overview.coordinate}</strong>
          <small>{overview.fixturePack}, {overview.planningFixture} planning, {overview.mapMode} map</small>
        </div>
        <div>
          <span>Safety</span>
          <strong>{overview.safetyLevel}</strong>
          <small>human review required before use</small>
        </div>
        <div>
          <span>Briefing Mode</span>
          <strong>{overview.briefingMode}</strong>
          <small>{architecture.runtime?.modelId || "deterministic fallback available"}</small>
        </div>
      </div>

      <h3 className="visualizer-label">Tool Timeline</h3>
      <div className="tool-timeline">
        {architecture.currentTrace.map((step, index) => (
          <article className="tool-card" key={step.id || `${step.name}-${index}`}>
            <div>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <strong>{step.name}</strong>
              <em className={`status ${step.status}`}>{step.status}</em>
            </div>
            <p>{step.summary}</p>
            <small>
              Sources: {step.sourceIds.map((id) => sourceById[id]?.label || id).join(", ") || "internal"}
            </small>
            <small>Evidence: {step.evidenceIds.join(", ") || "none"}</small>
            {step.fallbackReason && <small className="warning-note">{step.fallbackReason}</small>}
            {step.output?.modelId && <small>Model: {step.output.modelId}</small>}
            {step.output?.latencyMs !== undefined && <small>Latency: {step.output.latencyMs} ms</small>}
          </article>
        ))}
      </div>

      <h3 className="visualizer-label">Source + Evidence Map</h3>
      <div className="source-grid">
        {architecture.sources.map((source) => (
          <article key={source.id}>
            <div>
              <strong>{source.label}</strong>
              <em className={`status ${source.status}`}>{source.status}</em>
            </div>
            <span>{source.kind}</span>
            <small>{source.origin}</small>
            <small>{source.trustBoundary}</small>
          </article>
        ))}
      </div>
      <div className="evidence-flow">
        {architecture.evidenceFlow.map((item) => (
          <article key={item.id}>
            <strong>{item.title}</strong>
            <em className={`status ${item.status}`}>{item.status}</em>
            <small>Feeds: {item.feeds.join(", ")}</small>
          </article>
        ))}
      </div>

      <div className="decision-grid">
        <article>
          <h3>Safety Gate</h3>
          <strong>{architecture.safetyGate.level}</strong>
          <p>{architecture.safetyGate.message}</p>
          <small>
            Rules: {architecture.safetyGate.triggeredRules.length ? architecture.safetyGate.triggeredRules.join(", ") : "none triggered"}
          </small>
          <small>{architecture.safetyGate.awsMapping}</small>
        </article>
        <article>
          <h3>Future AWS Mapping</h3>
          <ul>
            {architecture.awsPath.map((item) => (
              <li key={item.local}>
                <strong>{item.local}</strong>
                <span>{item.future}</span>
              </li>
            ))}
          </ul>
        </article>
      </div>
    </section>
  );
}

function App() {
  const [request, setRequest] = useState(DEFAULT_REQUEST);
  const [entryMessage, setEntryMessage] = useState(DEFAULT_MESSAGE);
  const [entryResponse, setEntryResponse] = useState(null);
  const [agentOpen, setAgentOpen] = useState(false);
  const [agentMessages, setAgentMessages] = useState([
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

  const safetyTone = useMemo(() => {
    if (!run) return "pending";
    return run.safety.allowed ? "allowed" : "blocked";
  }, [run]);

  const runtimeTone = useMemo(() => {
    if (!run) return "pending";
    if (run.runtime.briefingMode === "real") return "allowed";
    if (run.runtime.briefingMode === "fallback") return "warning";
    return "pending";
  }, [run]);

  async function runAgent(nextRequest = request, nextMessage = entryMessage, confirmedByUser = true, appendMessage = true) {
    const submittedText = nextMessage.trim();
    if (appendMessage && submittedText) {
      setAgentMessages((current) => [
        ...current,
        {
          id: `user-${Date.now()}`,
          role: "user",
          text: submittedText,
        },
      ]);
      setEntryMessage("");
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
          message: nextMessage,
          confirmedByUser,
          runtimeOptions: {
            ...nextRequest,
            materials: uploads.map((upload) => ({
              type: upload.type,
              label: upload.label,
              summary: upload.summary,
            })),
          },
        }),
      });
      if (!response.ok) throw new Error(`API returned ${response.status}`);
      const payload = await response.json();
      const nextEntryResponse = payload.output?.localAsiOne || null;
      setEntryResponse(nextEntryResponse);
      if (nextEntryResponse) {
        setAgentMessages((current) => [
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

  useEffect(() => {
    runAgent(DEFAULT_REQUEST, DEFAULT_MESSAGE, true, false);
  }, []);

  function sendFieldBriefMessage(event) {
    event.preventDefault();
    if (!entryMessage.trim() || loading) return;
    runAgent(request, entryMessage, true, true);
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

  function updateRequest(field, value) {
    setRequest((current) => ({ ...current, [field]: value }));
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">3D-RAMS Demo1</p>
          <h1>Supervisor Runtime + Site Visualization</h1>
        </div>
        <div className="status-stack">
          <button className="secondary" onClick={() => setAgentOpen(true)}>
            <MessageSquare size={16} />
            FieldBrief Agent
          </button>
          <div className={`safety-pill ${safetyTone}`}>
            <ShieldCheck size={16} />
            {run ? run.safety.level : "not run"}
          </div>
          <div className={`safety-pill ${runtimeTone}`}>
            <GitBranch size={16} />
            {run ? run.runtime.briefingMode : "not run"}
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
              {agentMessages.map((message) => (
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
              {entryResponse?.needsConfirmation && entryResponse?.confirmation?.summary && (
                <article className="message assistant">
                  <span>3D-RAMS Agent</span>
                  <p>{entryResponse.confirmation.summary}</p>
                </article>
              )}
            </div>
            <div className="upload-strip">
              <button className="secondary" type="button" onClick={registerMockUpload}>
                <FileUp size={16} />
                Register test PDF/image
              </button>
              <span>{uploads.length ? `${uploads.length} evidence file(s) registered` : "Uploads use S3 when hosted; local mode registers metadata only."}</span>
            </div>
            <form className="composer" onSubmit={sendFieldBriefMessage}>
              <textarea value={entryMessage} onChange={(event) => setEntryMessage(event.target.value)} />
              <button disabled={loading || !entryMessage.trim()}>
                <Send size={16} />
                {loading ? "Running" : "Send"}
              </button>
            </form>
          </section>
        </div>
      )}

      <section className="control-strip">
        <label>
          Data pack
          <select
            value={request.fixturePack || ""}
            onChange={(event) => updateRequest("fixturePack", event.target.value || null)}
          >
            <option value="public-lambeth-thames">Lambeth public cache</option>
            <option value="">Synthetic default</option>
          </select>
        </label>
        <label>
          Latitude
          <input
            value={request.latitude}
            onChange={(event) => updateRequest("latitude", Number(event.target.value))}
            inputMode="decimal"
          />
        </label>
        <label>
          Longitude
          <input
            value={request.longitude}
            onChange={(event) => updateRequest("longitude", Number(event.target.value))}
            inputMode="decimal"
          />
        </label>
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={request.includePlanningFixture}
            onChange={(event) => updateRequest("includePlanningFixture", event.target.checked)}
          />
          Planning fixture
        </label>
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={request.simulateMapFailure}
            onChange={(event) => updateRequest("simulateMapFailure", event.target.checked)}
          />
          Map fallback
        </label>
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={request.useBedrock}
            onChange={(event) => updateRequest("useBedrock", event.target.checked)}
          />
          Bedrock
        </label>
        <button onClick={() => setAgentOpen(true)}>
          <MessageSquare size={16} />
          Open FieldBrief
        </button>
        <button
          className="secondary"
          onClick={() => {
            setAgentOpen(true);
            runAgent();
          }}
        >
          <Play size={16} />
          {loading ? "Running" : "Run latest intake"}
        </button>
        <button
          className="icon-button"
          aria-label="Reset request"
          onClick={() => {
            setRequest(DEFAULT_REQUEST);
            setEntryMessage(DEFAULT_MESSAGE);
            setAgentMessages([
              {
                id: "welcome",
                role: "assistant",
                text: "Tell me where you are going and what kind of site visit you are planning. I will ask for missing critical details, run tools, and return a RAMS-style review pack for human review.",
              },
            ]);
            setUploads([]);
            runAgent(DEFAULT_REQUEST, DEFAULT_MESSAGE, true, false);
          }}
        >
          <RotateCcw size={16} />
        </button>
      </section>

      {error && <div className="error-banner">Backend unavailable: {error}</div>}

      <section className="main-grid">
        <div className="scene-panel panel">
          {run ? <SceneViewer run={run} /> : <div className="empty-state">Waiting for agent run</div>}
        </div>

        <aside className="panel brief-panel">
          <div className="panel-heading">
            <ShieldCheck size={18} />
            <h2>Briefing</h2>
          </div>
          {run && (
            <>
              <h3>{run.briefing.headline}</h3>
              <ul>
                {run.briefing.summary.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
              <h4>Priority Checks</h4>
              <ul>
                {run.briefing.priority_checks.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
              <h4>Limitations</h4>
              <ul>
                {run.briefing.limitations.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </>
          )}
        </aside>
      </section>

      {run && (
        <section className="lower-grid">
          <section className="panel">
            <div className="panel-heading">
              <h2>Evidence Register</h2>
            </div>
            <div className="evidence-list">
              {run.evidence.map((item) => (
                <article key={item.id}>
                  <strong>{item.title}</strong>
                  <span>{item.source}</span>
                  <p>{item.why_it_matters}</p>
                  <em>{item.status}</em>
                </article>
              ))}
            </div>
          </section>
          <section className="panel">
            <div className="panel-heading">
              <h2>Agent Trace</h2>
            </div>
            <div className="trace-table">
              {run.trace.map((step, index) => (
                <div className="trace-row" key={`${step.name}-${index}`}>
                  <span>{String(index + 1).padStart(2, "0")}</span>
                  <strong>{step.name}</strong>
                  <em className={`status ${step.status}`}>{step.status}</em>
                  <small>{step.summary}</small>
                </div>
              ))}
            </div>
          </section>
          <WorkflowVisualizer architecture={run.architecture} />
        </section>
      )}
    </main>
  );
}

export default App;
