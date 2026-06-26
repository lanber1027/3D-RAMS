import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, GitBranch, Play, RotateCcw, ShieldCheck } from "lucide-react";
import * as Cesium from "cesium";
import "cesium/Build/Cesium/Widgets/widgets.css";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

const DEFAULT_REQUEST = {
  siteName: "Demo rural field fixture",
  latitude: 52.2053,
  longitude: -1.6022,
  goal: "Pre-visit RAMS scoping pack",
  includePlanningFixture: true,
  simulateMapFailure: false,
  additionalRequest: "",
};

function SceneViewer({ run }) {
  const containerRef = useRef(null);

  useEffect(() => {
    if (!containerRef.current || !run) return undefined;

    const viewer = new Cesium.Viewer(containerRef.current, {
      animation: false,
      timeline: false,
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

  return <div ref={containerRef} className="scene-viewer" aria-label="3D site scene" />;
}

function WorkflowVisualizer({ architecture }) {
  if (!architecture) return null;

  return (
    <section className="panel visualizer">
      <div className="panel-heading">
        <GitBranch size={18} />
        <h2>Architecture + Workflow</h2>
      </div>
      <div className="graph-row">
        {architecture.nodes.map((node) => (
          <div className="graph-node" key={node.id}>
            <strong>{node.label}</strong>
            <span>{node.boundary}</span>
          </div>
        ))}
      </div>
      <div className="trace-table">
        {architecture.currentTrace.map((step, index) => (
          <div className="trace-row" key={`${step.name}-${index}`}>
            <span>{String(index + 1).padStart(2, "0")}</span>
            <strong>{step.name}</strong>
            <em className={`status ${step.status}`}>{step.status}</em>
          </div>
        ))}
      </div>
      <div className="boundary-grid">
        {architecture.realVsMocked.map((item) => (
          <div key={item.component}>
            <strong>{item.component}</strong>
            <span>{item.status}</span>
          </div>
        ))}
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
        </div>
        <div className={`safety-pill ${safetyTone}`}>
          <ShieldCheck size={16} />
          {run ? run.safety.level : "not run"}
        </div>
      </header>

      <section className="control-strip">
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

