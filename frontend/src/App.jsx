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
const CLOUD_ENTRY_PROXY_URL = import.meta.env.VITE_CLOUD_ENTRY_PROXY_URL || "";
const USE_LOCAL_ASIONE = import.meta.env.VITE_USE_LOCAL_ASIONE === "true";
const ENTRY_AGENT_URL = USE_LOCAL_ASIONE ? import.meta.env.VITE_LOCAL_ASIONE_URL || AGENTCORE_URL : CLOUD_ENTRY_PROXY_URL;
const REPORT_LOOKUP_URL = USE_LOCAL_ASIONE ? AGENTCORE_URL : ENTRY_AGENT_URL;
const FIELD_BRIEF_LABEL = "FieldBrief ASI Simulation";
const STARTER_PROMPT =
  "I want to visit 8 Albert Embankment tomorrow for a survey within a 2km radius. Please prepare a pre-visit RAMS-style review pack.";
const REPORT_ACCESS_SCHEMA_VERSION = "3d-rams.report-access.v1";
const REPORT_SESSION_STORAGE_KEY = "3d-rams-report-session-id";

const DEFAULT_REQUEST = {
  siteName: "8 Albert Embankment and land to the rear",
  latitude: 51.492099,
  longitude: -0.118712,
  goal: "Pre-visit RAMS scoping pack",
  fixturePack: "public-lambeth-thames",
  includePlanningFixture: true,
  simulateMapFailure: false,
  useBedrock: false,
  additionalRequest: "",
};

function toList(value) {
  return Array.isArray(value) ? value : [];
}

function humanizeToken(value) {
  return String(value || "")
    .replace(/[-_]+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
    .trim();
}

function firstText(value) {
  if (typeof value === "string") return value;
  if (value && typeof value === "object") return value.message || value.summary || value.title || value.id || "";
  return "";
}

function listText(value) {
  return toList(value).map(firstText).filter(Boolean);
}

function riskItemsFromRun(run) {
  const hazards = toList(run?.hazards);
  if (hazards.length) return hazards;
  return toList(run?.structuredReport?.findings);
}

function attachStructuredReport(run, structuredReport, reviewMetadata) {
  if (!run || !structuredReport) return run;
  const reviewGate = reviewMetadata || run.reviewMetadata || run.reviewGate || structuredReport.reviewGate || null;
  return {
    ...run,
    structuredReport,
    ...(reviewGate ? { reviewGate, reviewMetadata: reviewGate } : {}),
  };
}

function reviewGateFromRun(run) {
  return run?.reviewMetadata || run?.reviewGate || run?.structuredReport?.reviewGate || null;
}

function reviewToneFromStatus(status) {
  const normalized = String(status || "").toLowerCase();
  if (normalized.includes("block")) return "blocked";
  if (normalized.includes("pass") || normalized.includes("allow")) return "allowed";
  return "warning";
}

function runToUiState(run) {
  if (!run) return {};
  return {
    location: run.location,
    scene: run.scene,
    annotations: run.annotations,
    hazards: riskItemsFromRun(run),
    evidence: run.evidence,
    briefing: run.briefing,
    safety: run.safety,
    trace: run.trace,
    structuredReport: run.structuredReport,
  };
}

function isConfirmationText(value) {
  const normalized = String(value || "").trim().toLowerCase();
  return (
    ["yes", "yes please", "confirm", "confirmed", "launch", "go", "go ahead", "confirm and launch"].includes(normalized) ||
    normalized.includes("please launch")
  );
}

function buildCloudEntryPayload({ submittedText, request, uploads, pendingEntry }) {
  const isConfirmationTurn = pendingEntry?.status === "confirmation_required" && pendingEntry?.intake;
  const shouldConfirm = isConfirmationTurn && isConfirmationText(submittedText);
  const reportSessionId = frontendReportSessionId();
  const payload = {
    entryTurn: true,
    caller: "frontend",
    conversationId: reportSessionId,
    entryAgentId: "fieldbrief-demo-ui",
    confirmedByUser: Boolean(shouldConfirm),
    message: submittedText,
    materials: uploads.map((upload) => ({
      materialId: upload.materialId || upload.id,
      sourceSystem: upload.sourceSystem || "fieldbrief-dev",
      type: upload.type,
      label: upload.label,
      summary: upload.summary,
      sizeBytes: upload.sizeBytes,
      access: upload.access || { mode: "fieldbrief_mock_reference" },
    })),
    runtimeOptions: {
      fixturePack: request.fixturePack,
      useBedrock: request.useBedrock,
      includePlanningFixture: request.includePlanningFixture,
      simulateMapFailure: request.simulateMapFailure,
    },
    reportAccess: {
      schemaVersion: REPORT_ACCESS_SCHEMA_VERSION,
      mode: "asi_session",
      sessionId: reportSessionId,
    },
  };
  if (shouldConfirm) {
    payload.intake = pendingEntry.intake;
  }
  return payload;
}

function buildLocalAsiOnePayload({ submittedText, request, uploads }) {
  const reportSessionId = frontendReportSessionId();
  return {
    localAsiOne: true,
    sessionId: reportSessionId,
    conversationId: reportSessionId,
    message: submittedText,
    confirmedByUser: true,
    runtimeOptions: {
      ...request,
      materials: uploads.map((upload) => ({
        materialId: upload.materialId || upload.id,
        sourceSystem: upload.sourceSystem || "fieldbrief-dev",
        type: upload.type,
        label: upload.label,
        summary: upload.summary,
        sizeBytes: upload.sizeBytes,
        access: upload.access || { mode: "fieldbrief_mock_reference" },
      })),
    },
  };
}

function caseIdFromPath() {
  const match = window.location.pathname.match(/^\/case\/([^/]+)\/?$/);
  return match ? decodeURIComponent(match[1]) : "";
}

function buildReportLookupPayload(caseId) {
  const reportSessionId = frontendReportSessionId();
  if (USE_LOCAL_ASIONE) {
    return {
      input: {
        operation: "getReport",
        caseId,
        reportAccess: {
          schemaVersion: REPORT_ACCESS_SCHEMA_VERSION,
          mode: "dev_local",
          caseId,
          sessionId: reportSessionId,
          authorizedCaseIds: [caseId],
        },
      },
    };
  }
  return {
    frontendInvoke: true,
    operation: "getReport",
    caseId,
    conversationId: reportSessionId,
    entryAgentId: "fieldbrief-demo-ui",
    reportAccess: {
      schemaVersion: REPORT_ACCESS_SCHEMA_VERSION,
      mode: "asi_session",
      caseId,
      sessionId: reportSessionId,
      authorizedCaseIds: [caseId],
    },
  };
}

function frontendReportSessionId() {
  if (typeof window === "undefined") return "frontend-demo-session";
  const existing = window.sessionStorage.getItem(REPORT_SESSION_STORAGE_KEY);
  if (existing) return existing;
  const generated =
    window.crypto?.randomUUID?.() ||
    `frontend-demo-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
  window.sessionStorage.setItem(REPORT_SESSION_STORAGE_KEY, generated);
  return generated;
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
          items.map((hazard, index) => (
            <article key={hazard.id || hazard.title || hazard.type || `risk-${index}`}>
              <strong>{riskCardTitle(hazard, index)}</strong>
              <em className={`status ${riskCardStatus(hazard)}`}>{riskCardStatus(hazard)}</em>
              <p>{riskCardBody(hazard)}</p>
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

function riskCardTitle(item, index) {
  const title = item.title || item.label || item.name;
  if (title && title !== "unknown-finding") return title;
  const typedTitle = humanizeToken(item.type || item.category);
  if (typedTitle && typedTitle !== "Unspecified") return typedTitle;
  const idTitle = humanizeToken(item.id);
  if (idTitle && idTitle !== "Unknown Finding") return idTitle;
  return `Candidate finding ${index + 1}`;
}

function riskCardStatus(item) {
  return item.confidence || item.severity || item.level || item.type || item.category || "review";
}

function riskCardBody(item) {
  return (
    item.reason ||
    item.summary ||
    item.note ||
    item.description ||
    item.rationale ||
    item.evidence ||
    "Review this item before the site visit."
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

function ReviewAndDataQuality({ report }) {
  const reviewGate = report?.reviewGate || {};
  const dataQuality = report?.dataQuality || {};
  const openWeb = report?.externalSignals?.openWeb || {};
  const reviewState = reviewStateFromReport(report);
  const missingItems = Object.entries(dataQuality.completeness || {})
    .filter(([, present]) => !present)
    .map(([key]) => humanizeCompleteness(key));
  const notes = listText(reviewGate.reviewerNotes);
  const caveats = [
    ...listText(reviewGate.caveats),
    ...listText(reviewGate.issues),
    ...listText(reviewGate.requiredRevisions),
  ];
  const gaps = listText(dataQuality.gaps);
  const warnings = listText(dataQuality.warnings);

  return (
    <section className="panel assurance-panel">
      <div className="panel-heading">
        <ShieldCheck size={18} />
        <h2>Review + Data Quality</h2>
      </div>
      <div className="review-summary">
        <article>
          <span>Review gate</span>
          <strong>{reviewState.label}</strong>
          <em className={`status ${reviewState.tone}`}>{reviewState.label}</em>
          <p>{reviewGate.message || "Review status appears after the supervisor returns a structured report."}</p>
        </article>
        <article>
          <span>Safety boundary</span>
          <strong>{reviewGate.requiresHumanReview === false ? "Human review not flagged" : "Human review required"}</strong>
          <p>Non-certified pre-visit review pack. Not RAMS certification, emergency guidance, or approval to work.</p>
        </article>
        <article>
          <span>Open-web signals</span>
          <strong>{humanizeToken(openWeb.status || "not_configured")}</strong>
          <p>{toList(openWeb.items).length ? `${toList(openWeb.items).length} signal(s) included as context.` : "No open-web signals are included."}</p>
        </article>
      </div>
      <div className="assurance-grid">
        <div>
          <h3>Report Sections</h3>
          {toList(report?.sections).map((section) => (
            <article className="compact-row section-row" key={section.id || section.title}>
              <strong>{section.title || humanizeToken(section.id)}</strong>
              <span>{firstText(toList(section.body)[0])}</span>
              <small className={`status ${section.status || "review_required"}`}>{humanizeToken(section.status || "review_required")}</small>
            </article>
          ))}
        </div>
        <div>
          <h3>Limitations</h3>
          <article className="compact-row">
            <strong>{dataQuality.dataMode || "unknown data mode"}</strong>
            <span>{missingItems.length ? `Missing: ${missingItems.join(", ")}` : "Completeness flags are satisfied."}</span>
          </article>
          {[...caveats, ...notes, ...gaps, ...warnings].slice(0, 8).map((item) => (
            <article className="compact-row" key={item}>
              <span>{item}</span>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

function reviewStateFromReport(report) {
  const reviewGate = report?.reviewGate || {};
  const raw = String(reviewGate.decision || reviewGate.status || report?.status || "review_required").toLowerCase();
  if (["pass", "passed", "review_passed"].includes(raw)) return { label: "Passed", tone: "passed" };
  if (["pass_with_caveats", "passed_with_caveats"].includes(raw)) return { label: "Passed with caveats", tone: "caveats" };
  if (["block", "blocked"].includes(raw)) return { label: "Blocked", tone: "blocked" };
  return { label: "Review required", tone: "review_required" };
}

function humanizeCompleteness(key) {
  return humanizeToken(String(key).replace(/^has/, "").replace(/([a-z])([A-Z])/g, "$1 $2"));
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
  const [caseId, setCaseId] = useState(caseIdFromPath());
  const [persistence, setPersistence] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const composerRef = useRef(null);

  const ui = entryResponse?.uiState || runToUiState(run);
  const runtime = entryResponse?.runtime || run?.runtime || {};
  const reviewGate = reviewGateFromRun(run);
  const reviewStatus = reviewGate?.status || reviewGate?.decision || "";
  const reviewTone = reviewToneFromStatus(reviewStatus);
  const safetyTone = ui.safety?.allowed === false ? "blocked" : ui.safety?.level === "needs_input" ? "warning" : "allowed";
  const pendingConfirmation = entryResponse?.status === "confirmation_required" && entryResponse?.intake;

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
      if (!ENTRY_AGENT_URL) {
        throw new Error("Cloud entry proxy is not configured. Set VITE_CLOUD_ENTRY_PROXY_URL, or set VITE_USE_LOCAL_ASIONE=true for explicit local testing.");
      }
      const requestPayload = USE_LOCAL_ASIONE
        ? buildLocalAsiOnePayload({ submittedText, request, uploads })
        : buildCloudEntryPayload({ submittedText, request, uploads, pendingEntry: entryResponse });
      const response = await fetch(ENTRY_AGENT_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(requestPayload),
      });
      if (!response.ok) throw new Error(`Agent run failed (${response.status})`);
      const payload = await response.json();
      const output = payload.output || {};
      const nextEntryResponse = payload.output?.localAsiOne || payload.output?.entryAgent || null;
      setEntryResponse(nextEntryResponse);
      setPersistence(output.persistence || nextEntryResponse?.agentcoreOutput?.persistence || null);
      if (nextEntryResponse) {
        setMessages((current) => [
          ...current,
          {
            id: nextEntryResponse.runId || `assistant-${Date.now()}`,
            role: "assistant",
            text: nextEntryResponse.assistantMessage || payload.output?.delivery?.customerSummary?.headline || "Supervisor workflow completed.",
            questions: nextEntryResponse.clarifyingQuestions || [],
            confirmationSummary: nextEntryResponse.confirmation?.summary || "",
          },
        ]);
      }
      if (["clarification_required", "confirmation_required"].includes(nextEntryResponse?.status)) {
        setAgentOpen(true);
        setRun(null);
        return;
      }
      const nextRun = attachStructuredReport(
        nextEntryResponse?.run || payload.output?.run,
        output.structuredReport,
        output.reviewMetadata || output.reviewGate,
      );
      if (!nextRun) throw new Error("Entry agent response did not include a supervisor run");
      const nextCaseId = output.caseId || nextEntryResponse?.caseId || nextRun.caseId || "";
      setCaseId(nextCaseId);
      if (nextCaseId && output.persistence?.status === "stored") {
        window.history.replaceState(null, "", `/case/${encodeURIComponent(nextCaseId)}`);
      }
      setRun(nextRun);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function loadCaseReport(nextCaseId) {
    if (!nextCaseId || loading) return;
    setLoading(true);
    setError("");
    try {
      if (!REPORT_LOOKUP_URL) {
        throw new Error("Report lookup is not configured. Set VITE_CLOUD_ENTRY_PROXY_URL, or use local ASI:ONE mode with the AgentCore proxy.");
      }
      const response = await fetch(REPORT_LOOKUP_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildReportLookupPayload(nextCaseId)),
      });
      if (!response.ok) throw new Error(`Report lookup failed (${response.status})`);
      const payload = await response.json();
      const output = payload.output || {};
      setPersistence(output.persistence || null);
      if (!output.run) {
        throw new Error(`No stored report found for ${nextCaseId}.`);
      }
      setEntryResponse(null);
      setCaseId(output.caseId || nextCaseId);
      setRun(attachStructuredReport(output.run, output.structuredReport, output.reviewMetadata || output.reviewGate));
      setMessages([
        {
          id: `case-${nextCaseId}`,
          role: "assistant",
          text: output.structuredReport?.executiveSummary?.headline || "Stored report loaded.",
        },
      ]);
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

  function revisePendingIntake() {
    setEntryResponse(null);
    setPrompt("");
    composerRef.current?.focus();
  }

  function registerMockUpload() {
    setUploads((current) => [
      ...current,
      {
        id: `local-upload-${current.length + 1}`,
        materialId: `fieldbrief_mock_material_${current.length + 1}`,
        sourceSystem: "fieldbrief-dev",
        type: "application/pdf",
        label: `Test evidence ${current.length + 1}`,
        summary: "Local demo evidence metadata registered by the FieldBrief ASI simulation.",
        sizeBytes: 1024,
        access: { mode: "fieldbrief_mock_reference" },
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
    setRun(null);
    setEntryResponse(null);
    setCaseId("");
    setPersistence(null);
    if (window.location.pathname.startsWith("/case/")) {
      window.history.replaceState(null, "", "/");
    }
    sendToFieldBrief(STARTER_PROMPT, false);
  }

  useEffect(() => {
    const routeCaseId = caseIdFromPath();
    if (routeCaseId) {
      loadCaseReport(routeCaseId);
      return;
    }
    sendToFieldBrief(STARTER_PROMPT, false);
  }, []);

  return (
    <main className="app-shell product-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">3D-RAMS AgentCore Workflow</p>
          <h1>Pre-Visit FieldBrief ASI Simulation</h1>
          <p className="topbar-summary">
            Development view for the ASI/ASI:ONE entry path. The entry agent confirms intake before the supervisor returns map, evidence, trace, and safety output.
          </p>
        </div>
        <div className="status-stack">
          <button className="secondary" onClick={() => setAgentOpen(true)}>
            <MessageSquare size={16} />
            {FIELD_BRIEF_LABEL}
          </button>
          <button className="icon-button" aria-label="Reset request" onClick={resetDemo}>
            <RotateCcw size={16} />
          </button>
          <div className={`safety-pill ${safetyTone}`}>
            <ShieldCheck size={16} />
            {ui.safety?.level || "ready"}
          </div>
          {reviewStatus && (
            <div className={`safety-pill ${reviewTone}`} title={reviewGate?.message || "review status"}>
              <ShieldCheck size={16} />
              Review {humanizeToken(reviewStatus)}
            </div>
          )}
          <div className="safety-pill pending">
            <Cloud size={16} />
            {runtime.subagentExecutionMode || runtime.supervisorRuntime || (USE_LOCAL_ASIONE ? "local" : "cloud")}
          </div>
          <div className={`safety-pill ${request.useBedrock ? "warning" : "allowed"}`}>
            <GitBranch size={16} />
            Bedrock {request.useBedrock ? "on" : "off"}
          </div>
          {caseId && (
            <div className="safety-pill pending" title={persistence?.status || "case id"}>
              {caseId}
            </div>
          )}
        </div>
      </header>

      {agentOpen && (
        <div className="agent-modal-backdrop" role="presentation">
          <section className="agent-modal agent-chat panel" role="dialog" aria-modal="true" aria-labelledby="fieldbrief-title">
            <div className="panel-heading agent-chat-heading">
              <Bot size={18} />
              <h2 id="fieldbrief-title">{FIELD_BRIEF_LABEL}</h2>
              <button className="icon-button" aria-label={`Collapse ${FIELD_BRIEF_LABEL}`} onClick={() => setAgentOpen(false)}>
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
                  {message.confirmationSummary && <p className="confirmation-summary">{message.confirmationSummary}</p>}
                </article>
              ))}
            </div>
            {pendingConfirmation && (
              <div className="confirmation-actions" aria-label="Pending confirmation">
                <button type="button" onClick={() => sendToFieldBrief("Confirm and launch", true)} disabled={loading}>
                  <ShieldCheck size={16} />
                  Confirm launch
                </button>
                <button className="secondary" type="button" onClick={revisePendingIntake} disabled={loading}>
                  <RotateCcw size={16} />
                  Revise details
                </button>
              </div>
            )}
            <div className="upload-strip">
              <button className="secondary" type="button" onClick={registerMockUpload}>
                <FileUp size={16} />
                Register test PDF/image
              </button>
              <label className="toggle-control">
                <input
                  type="checkbox"
                  checked={request.useBedrock}
                  onChange={(event) => setRequest((current) => ({ ...current, useBedrock: event.target.checked }))}
                />
                <span>Use Bedrock</span>
              </label>
              <span>{uploads.length ? `${uploads.length} evidence file(s) registered` : "Uploads use S3 when hosted; local testing registers metadata only."}</span>
            </div>
            <form className="composer" onSubmit={sendMessage}>
              <textarea ref={composerRef} value={prompt} onChange={(event) => setPrompt(event.target.value)} />
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
        <ReviewAndDataQuality report={ui.structuredReport} />
        <EvidenceAndTrace evidence={ui.evidence} trace={ui.trace} safety={ui.safety} runtime={runtime} />
      </section>
    </main>
  );
}

export default App;
