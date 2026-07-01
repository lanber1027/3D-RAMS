import { useEffect, useRef, useState } from "react";
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
import RunProgressPanel from "./components/RunProgressPanel.jsx";
import SiteSceneViewer from "./components/SiteSceneViewer.jsx";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "";
const STARTER_PROMPT =
  "I want to visit 8 Albert Embankment tomorrow for a survey. Please prepare a pre-visit RAMS-style review pack.";

function toList(value) {
  return Array.isArray(value) ? value : [];
}

function displayValue(value, fallback = "not available") {
  if (value === null || value === undefined || value === "") return fallback;
  if (typeof value === "boolean") return value ? "yes" : "no";
  return String(value);
}

function statusClass(value) {
  return displayValue(value, "unknown").toLowerCase().replace(/[^a-z0-9]+/g, "-");
}

function shortId(value) {
  const text = displayValue(value, "");
  if (!text) return "none";
  return text.length > 18 ? `${text.slice(0, 18)}...` : text;
}

function latestConversationRoute(turns) {
  for (let index = turns.length - 1; index >= 0; index -= 1) {
    const route = turns[index]?.metadata?.route;
    if (route) return route;
  }
  return null;
}

function pendingActionCopy(action) {
  const mapping = {
    confirm_or_correct_location: "Confirm the candidate card or send a corrected postcode/coordinate.",
    provide_corrected_location: "Send a corrected postcode, coordinate, OS grid reference, nearest road/town, or public evidence.",
    provide_location_detail: "Provide a trusted postcode, latitude/longitude, or source evidence.",
    provide_new_site_request: "Send a new site request with location evidence.",
    answer_clarifying_question: "Answer the agent's clarification question before tools run.",
    wait_for_agent_run: "The backend is running the current review workflow.",
  };
  return mapping[action] || "No user action is pending.";
}

function AgentStatePanel({ sessionState, runStatus, run, conversationDebug }) {
  const memory = sessionState?.workingMemory || {};
  const turns = toList(sessionState?.conversationTurns);
  const recentTurns = turns.slice(-5);
  const route = memory.latestRoute || latestConversationRoute(turns) || "not routed yet";
  const pendingAction = memory.pendingUserAction || (runStatus?.status === "waiting_for_location_confirmation" ? "confirm_or_correct_location" : null);
  const latestEvaluation = run?.evaluation || run?.uiState?.evaluation || runStatus?.result?.evaluation || runStatus?.finalUiState?.evaluation || null;
  const evaluationScores = latestEvaluation?.scores || {};
  const latestRunSummary = memory.latestReviewSummary || {};

  return (
    <section className="agent-state-panel" aria-live="polite">
      <div className="agent-state-header">
        <div>
          <p className="eyebrow">Agent state</p>
          <h2>Memory, routing, and quality loop</h2>
        </div>
        <span className={`status ${statusClass(pendingAction || "ready")}`}>
          {pendingAction ? "action pending" : "ready"}
        </span>
      </div>

      <div className="agent-state-grid">
        <article>
          <span>Latest route</span>
          <strong>{displayValue(route)}</strong>
          <p>{pendingActionCopy(pendingAction)}</p>
        </article>
        <article>
          <span>Active run</span>
          <strong>{shortId(memory.activeRunId || runStatus?.runId || run?.runId)}</strong>
          <p>
            Status: {displayValue(memory.latestRunStatus || runStatus?.status || latestRunSummary.status, "idle")}
          </p>
        </article>
        <article>
          <span>Storage</span>
          <strong>{displayValue(sessionState?.storageMode || run?.runtime?.sessionTraceMode || "memory")}</strong>
          <p>Shows bounded chat turns and trace metadata for this test session; uploaded file contents are not shown here.</p>
        </article>
        <article>
          <span>Quality gate</span>
          <strong>{latestEvaluation ? (latestEvaluation.passed ? "passed" : "needs repair / limited") : "not run yet"}</strong>
          <p>
            Loop: {displayValue(latestEvaluation?.loop, "0")} / stop: {displayValue(latestEvaluation?.evaluationStopReason, "pending")}
          </p>
        </article>
      </div>

      {latestEvaluation && (
        <div className="agent-evaluation-strip">
          {["grounding", "relevance", "completeness", "safety"].map((key) => (
            <div key={key}>
              <span>{key}</span>
              <strong>{displayValue(evaluationScores[key], "n/a")}</strong>
            </div>
          ))}
        </div>
      )}

      {conversationDebug && (
        <div className="conversation-observability">
          <div>
            <span>Current activity</span>
            <strong>{displayValue(conversationDebug.conversationState?.intent || conversationDebug.observability?.phase || conversationDebug.route)}</strong>
            <p>{displayValue(conversationDebug.observability?.noToolReason, "Tools may be running in the active run trace.")}</p>
          </div>
          <div>
            <span>Tools started</span>
            <strong>{conversationDebug.observability?.toolsStarted ? "yes" : "no"}</strong>
            <p>Route: {displayValue(conversationDebug.route)} / model calls: {displayValue(conversationDebug.observability?.modelCalls, "0")}</p>
          </div>
          <div>
            <span>Next action</span>
            <strong>{displayValue(conversationDebug.conversationState?.allowedNextAction || conversationDebug.trace?.[0]?.name, "conversation")}</strong>
            <p>{displayValue(conversationDebug.conversationState?.locationStatus || conversationDebug.trace?.[0]?.output?.orchestratorReason, "No extra model reason returned.")}</p>
          </div>
        </div>
      )}

      <div className="agent-turns">
        <h3>Recent bounded memory</h3>
        {recentTurns.length ? (
          recentTurns.map((turn, index) => (
            <div className="agent-turn" key={`${turn.role}-${turn.createdAt || index}-${index}`}>
              <span>{turn.role}</span>
              <strong>{displayValue(turn.metadata?.route || (turn.metadata?.routeInput ? "user_input" : "memory"))}</strong>
              <p>{displayValue(turn.text).slice(0, 220)}</p>
            </div>
          ))
        ) : (
          <p className="empty-copy">Session memory will appear after the first message.</p>
        )}
      </div>
    </section>
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

function LocationConfirmationPanel({ resolution, onConfirm, onReject, onManual, loading, confirmingLocation }) {
  if (!resolution?.siteName && !toList(resolution?.locationCandidates).length) return null;
  const candidates = toList(resolution.locationCandidates);
  const primaryCandidate = candidates[0];
  const hasCandidates = candidates.length > 0;
  const intent = resolution.intent || {};
  const locationLabel = resolution.siteName || intent.placeHint || intent.areaHint || "the described location";
  return (
    <section className="panel location-confirmation-panel">
      <div className="panel-heading">
        <MapPinned size={18} />
        <h2>{hasCandidates ? "Confirm Site Location" : "Location Needed"}</h2>
      </div>
      <p className="confirmation-copy">
        {hasCandidates
          ? "The agent found source-labelled candidate locations. Confirm one before map, evidence, risk, or briefing tools run."
          : "The agent has not found a reliable candidate to confirm. Map, evidence, risk, and briefing tools have not started."}
      </p>
      <CandidateMapPreview candidate={primaryCandidate} />
      {hasCandidates ? (
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
                  {confirmingLocation ? "Starting site review..." : "Confirm this site"}
                </button>
                <button className="secondary" type="button" onClick={onReject} disabled={loading}>
                  Not this site
                </button>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <div className="location-needed">
          <p className="empty-copy">
            I captured {locationLabel}, but I need a trusted location before producing site-specific output.
          </p>
          <div className="location-needed-actions">
            <article>
              <strong>Best</strong>
              <span>Send a full UK postcode.</span>
            </article>
            <article>
              <strong>Precise</strong>
              <span>Send latitude/longitude.</span>
            </article>
            <article>
              <strong>Alternative</strong>
              <span>Give a specific park/site name, nearest road, or public source.</span>
            </article>
          </div>
        </div>
      )}
      <button className="secondary" type="button" onClick={onManual} disabled={loading}>
        Enter coordinates manually
      </button>
    </section>
  );
}

function locationNeededResolutionFromConversation(conversationState) {
  if (!conversationState) return null;
  const intent = conversationState.intent;
  const locationStatus = conversationState.locationStatus;
  if (intent !== "location_discovery" && !["vague", "needs_evidence"].includes(locationStatus)) {
    return null;
  }
  const known = conversationState.knownDetails || {};
  const placeHint = known.placeHint || "";
  const areaHint = known.areaHint || "";
  const siteName =
    placeHint && areaHint
      ? `${placeHint} near ${areaHint}`
      : placeHint || areaHint || known.siteName || "the described location";
  return {
    siteName,
    intent: {
      placeHint: placeHint || null,
      areaHint: areaHint || null,
      activities: known.activity ? [known.activity] : [],
      postcode: known.postcode || null,
      coordinate: known.coordinate || null,
    },
    needsLocationConfirmation: false,
    locationCandidates: [],
    confirmedLocation: null,
    nextStage: "provide_location_detail",
    resolverMode: "conversation-location-needed",
    minimumEvidenceMet: false,
    message: "No reliable candidate is available yet. Ask for postcode, latitude/longitude, a specific site name, nearest road, or public evidence.",
    provisionalRisks: [],
  };
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
              <strong>{String(index + 1).padStart(2, "0")} - {step.name || step.currentStep || step.phase || "step"}</strong>
              <span>{step.summary || step.message || "Checkpoint recorded."}</span>
              <small>{step.status || "pending"}</small>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

function ArchitectureVisualizer({ architecture, ui, runtime, runStatus }) {
  const overview = architecture?.runOverview || {
    siteName: ui?.location?.label,
    goal: runStatus?.request?.message || "chat-first review pack",
    coordinate: ui?.location
      ? [ui.location.latitude, ui.location.longitude].filter((value) => value !== undefined).join(", ")
      : "pending confirmed location",
    fixturePack: runtime?.fixturePack || runtime?.fixturePackMode,
    briefingMode: runtime?.briefingMode,
    safetyLevel: ui?.safety?.level,
  };
  const trace = toList(architecture?.currentTrace).length
    ? toList(architecture.currentTrace)
    : toList(ui?.trace);
  const sources = toList(architecture?.sources).length
    ? toList(architecture.sources)
    : toList(ui?.sources);
  const evidenceFlow = toList(architecture?.evidenceFlow).length
    ? toList(architecture.evidenceFlow)
    : toList(ui?.evidence).map((item) => ({
        id: item.id,
        title: item.title,
        status: item.status,
        feeds: ["briefing", "trace"],
      }));
  const safetyGate = architecture?.safetyGate || ui?.safety || {};
  const awsPath = toList(architecture?.awsPath);
  const realVsMocked = toList(architecture?.realVsMocked);
  const visualRuntime = architecture?.runtime || runtime || {};

  if (!architecture && !trace.length && !sources.length && !runStatus) return null;

  return (
    <section className="panel architecture-visualizer">
      <div className="panel-heading">
        <GitBranch size={18} />
        <h2>Architecture + Workflow Visualizer</h2>
      </div>

      <div className="architecture-overview">
        <article>
          <span>Site</span>
          <strong>{displayValue(overview.siteName, "pending")}</strong>
        </article>
        <article>
          <span>Coordinate</span>
          <strong>{displayValue(overview.coordinate, "pending")}</strong>
        </article>
        <article>
          <span>Run</span>
          <strong>{displayValue(runStatus?.status, "ready")}</strong>
        </article>
        <article>
          <span>Mode</span>
          <strong>{displayValue(visualRuntime.activeAgentMode || visualRuntime.agentMode, "not run")}</strong>
        </article>
        <article>
          <span>Briefing</span>
          <strong>{displayValue(overview.briefingMode || visualRuntime.briefingMode, "not run")}</strong>
        </article>
        <article>
          <span>Safety</span>
          <strong>{displayValue(overview.safetyLevel || safetyGate.level, "not run")}</strong>
        </article>
      </div>

      <div className="architecture-grid">
        <div className="architecture-section wide">
          <div className="section-title">
            <Bot size={16} />
            <h3>Tool Loop</h3>
          </div>
          <div className="tool-flow">
            {trace.slice(0, 10).map((step, index) => (
              <article key={step.id || `${step.name || step.currentStep}-${index}`}>
                <span>{String(index + 1).padStart(2, "0")}</span>
                <strong>{step.name || step.currentStep || step.phase || "step"}</strong>
                <em className={`status ${statusClass(step.status)}`}>{displayValue(step.status, "pending")}</em>
                <small>{step.durationMs !== undefined ? `${step.durationMs} ms` : displayValue(step.summary || step.message, "checkpoint")}</small>
                {(step.fallbackReason || toList(step.evidenceIds).length > 0) && (
                  <p>
                    {[step.fallbackReason, toList(step.evidenceIds).join(", ")]
                      .filter(Boolean)
                      .join(" | ")}
                  </p>
                )}
              </article>
            ))}
            {!trace.length && <p className="empty-copy">Tool trace appears after the run starts.</p>}
          </div>
        </div>

        <div className="architecture-section">
          <div className="section-title">
            <FileUp size={16} />
            <h3>Sources</h3>
          </div>
          <div className="source-list">
            {sources.slice(0, 8).map((source) => (
              <article key={source.id || source.label || source.title}>
                <strong>{source.label || source.title || source.id}</strong>
                <span>{source.origin || source.source || source.kind || "source register"}</span>
                <em className={`status ${statusClass(source.status || source.dataMode)}`}>
                  {displayValue(source.status || source.dataMode, "registered")}
                </em>
              </article>
            ))}
            {!sources.length && <p className="empty-copy">Source register appears after location confirmation.</p>}
          </div>
        </div>

        <div className="architecture-section">
          <div className="section-title">
            <ShieldCheck size={16} />
            <h3>Evidence + Safety</h3>
          </div>
          <div className="evidence-flow-list">
            {evidenceFlow.slice(0, 6).map((item) => (
              <article key={item.id || item.title}>
                <strong>{item.title || item.id}</strong>
                <span>feeds {toList(item.feeds).join(", ") || "review pack"}</span>
                <em className={`status ${statusClass(item.status)}`}>{displayValue(item.status, "evidence")}</em>
              </article>
            ))}
            {!evidenceFlow.length && <p className="empty-copy">Evidence links appear once tools complete.</p>}
          </div>
          <div className="safety-gate-card">
            <strong>{displayValue(safetyGate.level, "safety not run")}</strong>
            <span>{displayValue(safetyGate.message, "Safety gate runs before output is trusted.")}</span>
            {toList(safetyGate.triggeredRules).length > 0 && (
              <small>{toList(safetyGate.triggeredRules).join(", ")}</small>
            )}
          </div>
        </div>

        <div className="architecture-section wide">
          <div className="section-title">
            <Cloud size={16} />
            <h3>AWS Path</h3>
          </div>
          <div className="aws-map-grid">
            {awsPath.map((item) => (
              <article key={`${item.current}-${item.hosted || item.future}`}>
                <strong>{item.current}</strong>
                <span>{item.hosted || item.future}</span>
              </article>
            ))}
            {!awsPath.length && (
              <>
                <article>
                  <strong>Trace response</strong>
                  <span>Hosted path maps structured run events to CloudWatch when configured</span>
                </article>
                <article>
                  <strong>Evidence register</strong>
                  <span>Hosted path maps upload metadata and evidence packs to private S3 when configured</span>
                </article>
              </>
            )}
          </div>
        </div>

        <div className="architecture-section wide">
          <div className="section-title">
            <AlertTriangle size={16} />
            <h3>Real Vs Mocked</h3>
          </div>
          <div className="badge-grid">
            {realVsMocked.map((item) => (
              <article key={item.component}>
                <strong>{item.component}</strong>
                <em className={`status ${statusClass(item.status)}`}>{item.status}</em>
              </article>
            ))}
            {!realVsMocked.length && <p className="empty-copy">Real-vs-mocked status is included with completed run architecture.</p>}
          </div>
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
  const [sessionState, setSessionState] = useState(null);
  const [conversationDebug, setConversationDebug] = useState(null);
  const [uploads, setUploads] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [confirmingLocation, setConfirmingLocation] = useState(false);
  const completedRunsRef = useRef(new Set());

  const ui = run?.uiState || {};
  const accessLabel = session?.accessLabel || "not started";
  const runtime = run?.runtime || {};
  const locationResolution = run?.locationResolution || ui.locationResolution || null;
  const reviewMode = ui.reviewMode || (runStatus && ["queued", "running"].includes(runStatus.status) ? "new run in progress" : null);
  const safetyTone = ui.safety?.allowed === false ? "blocked" : ui.safety?.level === "needs_input" ? "warning" : "allowed";

  async function refreshSessionState(sessionId = session?.sessionId) {
    if (!sessionId) return null;
    const response = await fetch(`${API_BASE_URL}/api/session/${sessionId}`);
    if (!response.ok) return null;
    const nextSessionState = await response.json();
    setSessionState(nextSessionState);
    return nextSessionState;
  }

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
      setSessionState({
        ...nextSession,
        runs: [],
        uploads: [],
        conversationTurns: [],
        workingMemory: {},
        storageMode: nextSession.runtime?.sessionTraceMode || "memory",
      });
      localStorage.setItem("3drams-session", JSON.stringify(nextSession));
      await refreshSessionState(nextSession.sessionId);
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
    setConversationDebug({
      route: "pending",
      observability: {
        phase: "sending_to_backend",
        toolsStarted: false,
        modelCalls: 0,
        noToolReason: "Waiting for the server-side conversation router to classify this turn.",
      },
      trace: [],
    });
    setRun({
      runId: "pending",
      assistantMessage: "Message sent to the server-side agent router.",
      uiState: {
        location: null,
        scene: null,
        annotations: [],
        mapFeatures: [],
        liveFeatureStatus: null,
        hazards: [],
        evidence: [],
        sources: [],
        briefing: null,
        safety: { allowed: true, level: "routing", message: "Conversation router is deciding whether tools should run." },
        trace: [],
        architecture: null,
        locationResolution: null,
        reviewMode: "conversation routing in progress",
      },
      runtime: { activeAgentMode: "conversation-router", briefingMode: "not-run" },
      trace: [],
      evidence: [],
      scene: null,
      annotations: [],
      mapFeatures: [],
      liveFeatureStatus: null,
      briefing: null,
      safety: { allowed: true, level: "routing", message: "Conversation router is deciding whether tools should run." },
    });
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE_URL}/api/conversation/message`, {
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
      if (!response.ok) throw new Error(`Agent message failed (${response.status})`);
      const result = await response.json();
      if (result.run) {
        const runToolCount = Array.isArray(result.run.toolResults) ? result.run.toolResults.length : 0;
        const runToolsStarted = runToolCount > 0;
        const runPhase =
          result.run.status === "waiting_for_location_confirmation"
            ? "waiting_for_location_confirmation"
            : runToolsStarted
              ? "durable_run_tools_started"
              : "durable_run_started";
        setConversationDebug({
          route: result.route,
          conversationState: result.conversationState,
          observability: {
            phase: runPhase,
            toolsStarted: runToolsStarted,
            modelCalls: result.run.modelCallsUsed ?? 0,
            noToolReason: runToolsStarted
              ? null
              : "Durable run accepted, but map/evidence/risk/briefing tools have not started yet.",
          },
          trace: result.run.steps || result.trace || [],
        });
        localStorage.setItem("3drams-latest-run", result.run.runId);
        applyRunStatus(result.run);
        await refreshSessionState(session.sessionId);
      } else {
        const locationNeededResolution = locationNeededResolutionFromConversation(result.conversationState);
        const nextConversationDebug = {
          route: result.route,
          conversationState: result.conversationState,
          observability: result.observability || {
            phase: "conversation_only",
            toolsStarted: false,
            modelCalls: 0,
            noToolReason: "No durable run was started for this turn.",
          },
          trace: result.trace || [],
          modelCalls: result.modelCalls || [],
        };
        setConversationDebug(nextConversationDebug);
        setRunStatus(null);
        setMessages((current) => [
          ...current,
          {
            id: `assistant-${Date.now()}`,
            role: "assistant",
            text: result.assistantMessage || "I answered from the current session context.",
          },
        ]);
        setRun((current) => ({
          ...(current || {}),
          assistantMessage: result.assistantMessage || "I answered from the current session context.",
          uiState: {
            ...(current?.uiState || {}),
            ...(locationNeededResolution
              ? {
                  location: null,
                  scene: null,
                  annotations: [],
                  mapFeatures: [],
                  liveFeatureStatus: null,
                  hazards: [],
                  evidence: [],
                  sources: [],
                  briefing: null,
                  architecture: null,
                }
              : {}),
            safety: { allowed: true, level: "conversation", message: "No site-review tools ran for this chat turn." },
            trace: result.trace || [],
            locationResolution: locationNeededResolution || current?.uiState?.locationResolution || null,
            reviewMode: locationNeededResolution ? "location needed" : "conversation only",
          },
          trace: result.trace || [],
          evidence: locationNeededResolution ? [] : current?.evidence,
          scene: locationNeededResolution ? null : current?.scene,
          annotations: locationNeededResolution ? [] : current?.annotations,
          modelCalls: result.modelCalls || [],
          runtime: {
            ...(current?.runtime || {}),
            ...(result.runtime || {}),
            activeAgentMode: result.runtime?.agentRuntimeTarget || "conversation-router",
            briefingMode: "conversation-only",
          },
        }));
        await refreshSessionState(session.sessionId);
        setLoading(false);
      }
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
      mapFeatures: status.partialUiState?.mapFeatures || [],
      liveFeatureStatus: status.partialUiState?.liveFeatureStatus || null,
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
      const status = await fetchRunStatus(runId);
      applyRunStatus(status);
      await refreshSessionState(status.sessionId || session?.sessionId);
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
      const status = await response.json();
      applyRunStatus(status);
      await refreshSessionState(status.sessionId || session?.sessionId);
    } catch (err) {
      setError(err.message);
    }
  }

  async function confirmLocation(candidateId) {
    if (!runStatus?.runId) return;
    const confirmedCandidate = toList(locationResolution?.locationCandidates).find((candidate) => candidate.candidateId === candidateId);
    const candidateLabel = confirmedCandidate?.name || "the selected site";
    setLoading(true);
    setConfirmingLocation(true);
    setError("");
    setMessages((current) => [
      ...current,
      {
        id: `confirm-${Date.now()}`,
        role: "assistant",
        text: `Confirmation submitted for ${candidateLabel}. I am starting the site review and will show planning, evidence, risk reasoning, and safety checks as the backend accepts and returns them.`,
      },
    ]);
    try {
      const response = await fetch(`${API_BASE_URL}/api/runs/${runStatus.runId}/confirm-location`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ candidateId }),
      });
      if (!response.ok) throw new Error(`Location confirmation failed (${response.status})`);
      applyRunStatus(await response.json());
      await refreshSessionState(session.sessionId);
    } catch (err) {
      setError(err.message);
      setLoading(false);
    } finally {
      setConfirmingLocation(false);
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
      await refreshSessionState(session.sessionId);
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
        const parsedSession = JSON.parse(cachedSession);
        setSession(parsedSession);
        setSessionState(parsedSession);
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
    if (!session?.sessionId) return undefined;
    let cancelled = false;
    refreshSessionState(session.sessionId)
      .then((nextSessionState) => {
        if (!cancelled && nextSessionState) setSessionState(nextSessionState);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [session?.sessionId]);

  useEffect(() => {
    if (!runStatus?.runId || !["queued", "running"].includes(runStatus.status)) return undefined;
    const timer = window.setInterval(async () => {
      try {
        const status = await fetchRunStatus(runStatus.runId);
        applyRunStatus(status);
        if (!["queued", "running"].includes(status.status)) {
          await refreshSessionState(status.sessionId || session?.sessionId);
        }
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
      <RunProgressPanel
        runStatus={runStatus}
        loading={loading}
        confirmingLocation={confirmingLocation}
        run={run}
      />
      <AgentStatePanel
        sessionState={sessionState}
        runStatus={runStatus}
        run={run}
        conversationDebug={conversationDebug}
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
          <SiteSceneViewer
            scene={ui.scene}
            annotations={ui.annotations}
            location={ui.location}
            mapFeatures={ui.mapFeatures}
            liveFeatureStatus={ui.liveFeatureStatus}
            safety={ui.safety}
          />
        </section>
      </section>

      <LocationConfirmationPanel
        resolution={locationResolution}
        onConfirm={confirmLocation}
        onReject={rejectLocationCandidate}
        onManual={enterCoordinatesManually}
        loading={loading}
        confirmingLocation={confirmingLocation}
      />

      <section className="insight-grid">
        <RiskCards hazards={ui.hazards} briefing={ui.briefing} reviewMode={reviewMode} />
        <EvidenceAndTrace evidence={ui.evidence} trace={ui.trace} safety={ui.safety} runtime={runtime} runStatus={runStatus} />
      </section>

      <ArchitectureVisualizer architecture={ui.architecture} ui={ui} runtime={runtime} runStatus={runStatus} />
    </main>
  );
}

export default App;
