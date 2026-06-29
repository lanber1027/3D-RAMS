import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, GitBranch, Play, RotateCcw, ShieldCheck } from "lucide-react";
import * as Cesium from "cesium";
import "cesium/Build/Cesium/Widgets/widgets.css";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "";

const DEFAULT_REQUEST = {
  siteName: "8 Albert Embankment and land to the rear",
  latitude: 51.492099,
  longitude: -0.118712,
  goal: "Pre-visit RAMS scoping pack",
  fixturePack: "public-lambeth-thames",
  includePlanningFixture: true,
  simulateMapFailure: false,
  useBedrock: true,
  agentMode: "llm-planner",
  additionalRequest: "",
};

function toList(value) {
  return Array.isArray(value) ? value : [];
}

function summarizePlanText(run) {
  const explicitPlan =
    run?.llmPlan?.summary ||
    run?.llmPlan?.text ||
    run?.llmPlan?.plan ||
    run?.architecture?.llmFlow?.planSummary;

  if (explicitPlan) return explicitPlan;

  const modelStep = toList(run?.trace).find((step) => step.type === "model" || step.output?.modelId);
  return modelStep?.summary || "Planner detail not returned in this run.";
}

function deriveModelCalls(run) {
  if (Array.isArray(run?.modelCalls) && run.modelCalls.length) return run.modelCalls;

  return toList(run?.trace)
    .filter((step) => step.type === "model" || step.output?.modelId)
    .map((step, index) => ({
      id: step.id || `model-${index}`,
      modelId: step.output?.modelId || run?.runtime?.modelId || "model not reported",
      status: step.status || "unknown",
      latencyMs: step.output?.latencyMs,
      summary: step.summary,
      tokenUsage: step.output?.tokenUsage || run?.tokenUsage,
    }));
}

function deriveToolCalls(run) {
  if (Array.isArray(run?.llmToolCalls) && run.llmToolCalls.length) return run.llmToolCalls;

  return toList(run?.trace)
    .filter((step) => step.type !== "model")
    .map((step, index) => ({
      id: step.id || `tool-${index}`,
      name: step.name || `Tool ${index + 1}`,
      status: step.status || "unknown",
      summary: step.summary,
      allowlisted: step.allowlisted ?? true,
      evidenceIds: toList(step.evidenceIds),
      sourceIds: toList(step.sourceIds),
      fallbackReason: step.fallbackReason,
    }));
}

function deriveFallback(run) {
  return (
    run?.fallback ||
    run?.runtime?.fallback ||
    run?.architecture?.llmFlow?.fallback ||
    toList(run?.trace).find((step) => step.status === "fallback" || step.fallbackReason) || {
      status: run?.runtime?.briefingMode === "fallback" ? "fallback" : "available",
      reason: "Deterministic fallback remains available when the model step is disabled, rejected, or fails.",
    }
  );
}

function deriveRuntimeState(run) {
  const runtime = run?.runtime || {};
  const briefingMode = runtime.briefingMode || "not reported";
  const agentMode =
    runtime.agentMode ||
    run?.agentMode ||
    (briefingMode === "real" ? "llm-first" : briefingMode === "fallback" ? "fallback" : "deterministic");

  return {
    briefingMode,
    agentMode,
    modelId: runtime.modelId || "No live model reported",
    plannerMode: run?.llmPlan ? "model-planned" : briefingMode === "real" ? "llm-assisted" : "deterministic-only",
    tokenUsage: run?.tokenUsage || runtime.tokenUsage || null,
  };
}

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

function LlmFlowVisualizer({ run }) {
  if (!run) return null;

  const runtimeState = deriveRuntimeState(run);
  const modelCalls = deriveModelCalls(run);
  const toolCalls = deriveToolCalls(run);
  const fallback = deriveFallback(run);
  const evidenceCount = toList(run.evidence).length;
  const safetyAllowed = Boolean(run.safety?.allowed);
  const planText = summarizePlanText(run);
  const plannerBadgeTone = runtimeState.agentMode === "llm-first" || runtimeState.briefingMode === "real" ? "real" : "future";
  const tokenSummary = runtimeState.tokenUsage
    ? [
        runtimeState.tokenUsage.inputTokens ?? runtimeState.tokenUsage.input ?? null,
        runtimeState.tokenUsage.outputTokens ?? runtimeState.tokenUsage.output ?? null,
        runtimeState.tokenUsage.totalTokens ?? runtimeState.tokenUsage.total ?? null,
      ]
        .filter((value) => value !== null && value !== undefined)
        .join(" / ")
    : "";

  const stages = [
    {
      title: "Model Plan",
      status: plannerBadgeTone,
      body: planText,
      meta: `Mode: ${runtimeState.agentMode} | ${runtimeState.plannerMode}`,
    },
    {
      title: "Allowlisted Tool Calls",
      status: toolCalls.some((item) => item.status === "fallback") ? "fallback" : "ok",
      body:
        toolCalls.length > 0
          ? `${toolCalls.length} tool step${toolCalls.length === 1 ? "" : "s"} returned to the planner/runtime.`
          : "No tool-call detail returned in this run.",
      meta: toolCalls.length > 0 ? toolCalls.map((item) => item.name).slice(0, 4).join(", ") : "Deterministic internal steps only",
    },
    {
      title: "Evidence + Results",
      status: evidenceCount > 0 ? "ok" : "warning",
      body: `${evidenceCount} evidence item${evidenceCount === 1 ? "" : "s"} linked into the briefing and annotations.`,
      meta: toList(run.sources).length > 0 ? `${toList(run.sources).length} source register entries` : "Source register detail not returned",
    },
    {
      title: "Synthesis",
      status: run.briefing ? "ok" : "warning",
      body: run.briefing?.headline || "Briefing payload not returned.",
      meta: modelCalls[0]?.modelId || runtimeState.modelId,
    },
    {
      title: "Safety Gate",
      status: safetyAllowed ? "ok" : "blocked",
      body: run.safety?.message || run.safety?.level || "Safety result not returned.",
      meta: safetyAllowed ? "Human review still required" : "Unsafe claim blocked",
    },
    {
      title: "Deterministic Fallback",
      status: fallback.status || "future",
      body: fallback.reason || fallback.summary || "Fallback detail not returned.",
      meta: fallback.trigger || fallback.fallbackReason || "Available when model path is disabled or fails",
    },
  ];

  return (
    <section className="panel llm-panel">
      <div className="panel-heading">
        <GitBranch size={18} />
        <h2>LLM-First Runtime</h2>
      </div>

      <div className="llm-runtime-strip">
        <article>
          <span>Runtime mode</span>
          <strong>{runtimeState.agentMode}</strong>
          <small>{runtimeState.briefingMode} briefing mode</small>
        </article>
        <article>
          <span>Planner</span>
          <strong>{runtimeState.plannerMode}</strong>
          <small>{runtimeState.modelId}</small>
        </article>
        <article>
          <span>Model calls</span>
          <strong>{modelCalls.length}</strong>
          <small>{tokenSummary || "Token usage not reported"}</small>
        </article>
        <article>
          <span>Fallback</span>
          <strong>{fallback.status || "available"}</strong>
          <small>deterministic path remains public-safe</small>
        </article>
      </div>

      <div className="llm-stage-grid">
        {stages.map((stage) => (
          <article key={stage.title} className="llm-stage-card">
            <div className="llm-stage-top">
              <h3>{stage.title}</h3>
              <em className={`status ${stage.status}`}>{stage.status}</em>
            </div>
            <p>{stage.body}</p>
            <small>{stage.meta}</small>
          </article>
        ))}
      </div>

      <div className="llm-detail-grid">
        <article>
          <h3>Planner + Model Trace</h3>
          <div className="llm-detail-list">
            {modelCalls.length > 0 ? (
              modelCalls.map((call) => (
                <div key={call.id} className="llm-detail-row">
                  <strong>{call.modelId}</strong>
                  <em className={`status ${call.status}`}>{call.status}</em>
                  <small>{call.summary || "Model call returned no summary."}</small>
                </div>
              ))
            ) : (
              <div className="llm-detail-row">
                <strong>Deterministic only</strong>
                <small>No model call metadata returned for this run.</small>
              </div>
            )}
          </div>
        </article>
        <article>
          <h3>Allowlisted Tool Results</h3>
          <div className="llm-detail-list">
            {toolCalls.map((call) => (
              <div key={call.id} className="llm-detail-row">
                <strong>{call.name}</strong>
                <em className={`status ${call.status}`}>{call.status}</em>
                <small>
                  {call.summary || "No summary returned."}
                  {call.allowlisted === false ? " Not allowlisted." : " Allowlisted."}
                </small>
              </div>
            ))}
          </div>
        </article>
      </div>
    </section>
  );
}

function WorkflowVisualizer({ architecture }) {
  if (!architecture) return null;
  const overview = architecture.runOverview || {};
  const sources = toList(architecture.sources);
  const currentTrace = toList(architecture.currentTrace);
  const evidenceFlow = toList(architecture.evidenceFlow);
  const awsPath = toList(architecture.awsPath);
  const sourceById = Object.fromEntries(sources.map((source) => [source.id, source]));

  return (
    <section className="panel visualizer">
      <div className="panel-heading">
        <GitBranch size={18} />
        <h2>Architecture + Workflow</h2>
      </div>

      <div className="run-overview">
        <div>
          <span>Query</span>
          <strong>{overview.goal || "Goal not returned"}</strong>
          <small>{overview.siteName || "Site not returned"}</small>
        </div>
        <div>
          <span>Coordinate</span>
          <strong>{overview.coordinate || "Coordinate not returned"}</strong>
          <small>{overview.fixturePack || "fixture unknown"}, {overview.planningFixture || "planning unknown"} planning, {overview.mapMode || "map unknown"} map</small>
        </div>
        <div>
          <span>Safety</span>
          <strong>{overview.safetyLevel || "not returned"}</strong>
          <small>human review required before use</small>
        </div>
        <div>
          <span>Briefing Mode</span>
          <strong>{overview.briefingMode || "not returned"}</strong>
          <small>{architecture.runtime?.modelId || "deterministic fallback available"}</small>
        </div>
      </div>

      <h3 className="visualizer-label">Tool Timeline</h3>
      <div className="tool-timeline">
        {currentTrace.map((step, index) => (
          <article className="tool-card" key={step.id || `${step.name}-${index}`}>
            <div>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <strong>{step.name}</strong>
              <em className={`status ${step.status}`}>{step.status}</em>
            </div>
            <p>{step.summary}</p>
            <small>
              Sources: {toList(step.sourceIds).map((id) => sourceById[id]?.label || id).join(", ") || "internal"}
            </small>
            <small>Evidence: {toList(step.evidenceIds).join(", ") || "none"}</small>
            {step.fallbackReason && <small className="warning-note">{step.fallbackReason}</small>}
            {step.output?.modelId && <small>Model: {step.output.modelId}</small>}
            {step.output?.latencyMs !== undefined && <small>Latency: {step.output.latencyMs} ms</small>}
          </article>
        ))}
      </div>

      <h3 className="visualizer-label">Source + Evidence Map</h3>
      <div className="source-grid">
        {sources.map((source) => (
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
        {evidenceFlow.map((item) => (
          <article key={item.id}>
            <strong>{item.title}</strong>
            <em className={`status ${item.status}`}>{item.status}</em>
            <small>Feeds: {toList(item.feeds).join(", ")}</small>
          </article>
        ))}
      </div>

      <div className="decision-grid">
        <article>
          <h3>Safety Gate</h3>
          <strong>{architecture.safetyGate?.level || "not returned"}</strong>
          <p>{architecture.safetyGate?.message || "Safety gate detail not returned."}</p>
          <small>
            Rules: {toList(architecture.safetyGate?.triggeredRules).length ? toList(architecture.safetyGate?.triggeredRules).join(", ") : "none triggered"}
          </small>
          <small>{architecture.safetyGate?.awsMapping || "Local rules today, Guardrails/human review later"}</small>
        </article>
        <article>
          <h3>Future AWS Mapping</h3>
          <ul>
            {awsPath.map((item) => (
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
  const [run, setRun] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const safetyTone = useMemo(() => {
    if (!run) return "pending";
    return run.safety.allowed ? "allowed" : "blocked";
  }, [run]);

  const runtimeTone = useMemo(() => {
    if (!run) return "pending";
    if (run.runtime?.briefingMode === "real") return "allowed";
    if (run.runtime?.briefingMode === "fallback") return "warning";
    return "pending";
  }, [run]);

  const runtimeState = useMemo(() => deriveRuntimeState(run), [run]);

  async function runAgent(nextRequest = request) {
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE_URL}/api/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(nextRequest),
      });
      if (!response.ok) throw new Error(`API returned ${response.status}`);
      setRun(await response.json());
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    runAgent(DEFAULT_REQUEST);
  }, []);

  function updateRequest(field, value) {
    setRequest((current) => ({ ...current, [field]: value }));
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">3D-RAMS Demo1</p>
          <h1>Pre-Visit Field Briefing Agent</h1>
          <p className="topbar-summary">
            LLM-first when live Bedrock is enabled, deterministic fallback when it is not.
          </p>
        </div>
        <div className="status-stack">
          <div className={`safety-pill ${safetyTone}`}>
            <ShieldCheck size={16} />
            {run ? run.safety.level : "not run"}
          </div>
          <div className={`safety-pill ${runtimeTone}`}>
            <GitBranch size={16} />
            {run ? runtimeState.briefingMode : "not run"}
          </div>
        </div>
      </header>

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
            onChange={(event) => {
              const enabled = event.target.checked;
              setRequest((current) => ({
                ...current,
                useBedrock: enabled,
                agentMode: enabled ? "llm-planner" : "deterministic",
              }));
            }}
          />
          Live Bedrock
        </label>
        <div className="mode-callout">
          <span>Runtime mode</span>
          <strong>{request.useBedrock ? "LLM-first if backend allows it" : "Deterministic only"}</strong>
          <small>Live Bedrock remains maintainer-only and falls back locally if unavailable.</small>
        </div>
        <button onClick={() => runAgent()} disabled={loading}>
          <Play size={16} />
          {loading ? "Running" : "Run"}
        </button>
        <button
          className="secondary"
          onClick={() => {
            const unsafe = {
              ...request,
              additionalRequest: "Please certify RAMS and approve work today.",
            };
            setRequest(unsafe);
            runAgent(unsafe);
          }}
        >
          <AlertTriangle size={16} />
          Safety test
        </button>
        <button
          className="icon-button"
          aria-label="Reset request"
          onClick={() => {
            setRequest(DEFAULT_REQUEST);
            runAgent(DEFAULT_REQUEST);
          }}
        >
          <RotateCcw size={16} />
        </button>
      </section>

      {error && <div className="error-banner">Backend unavailable: {error}</div>}

      {run && <LlmFlowVisualizer run={run} />}

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
                {toList(run.briefing.summary).map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
              <h4>Priority Checks</h4>
              <ul>
                {toList(run.briefing.priority_checks).map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
              <h4>Limitations</h4>
              <ul>
                {toList(run.briefing.limitations).map((item) => (
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
              {toList(run.evidence).map((item) => (
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
              {toList(run.trace).map((step, index) => (
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
