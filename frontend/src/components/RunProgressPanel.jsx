import {
  AlertTriangle,
  Check,
  Circle,
  Clock3,
  Loader2,
  PauseCircle,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import "./run-progress.css";

const STAGES = [
  {
    key: "location_confirmation",
    label: "Location confirmed",
    matches: ["location_confirmation"],
  },
  {
    key: "planner",
    label: "Planning tool calls",
    matches: ["planner", "planner_model_call", "planner_invalid_plan", "planner_model_budget_exhausted"],
  },
  {
    key: "tool_loop",
    label: "Running site/context tools",
    matches: ["tool_loop"],
    matchPrefix: ["tool:"],
  },
  {
    key: "risk_reasoner",
    label: "Reasoning over risks",
    matches: ["risk_reasoner", "reasoner_model_call", "reasoner_model_budget_exhausted"],
  },
  {
    key: "compiler",
    label: "Compiling review pack",
    matches: ["compiler", "compiler_model_call", "compiler_model_budget_exhausted"],
  },
  {
    key: "output_evaluation",
    label: "Quality review / repair",
    matches: [
      "output_evaluation",
      "evaluate_output_quality",
      "output_improvement_loop",
      "output_evaluation_stop",
      "output_evaluator_model_call",
      "output_evaluator_model_budget_exhausted",
    ],
  },
  {
    key: "safety_gate",
    label: "Safety gate",
    matches: ["safety_gate"],
    matchPrefix: ["tool:safety_gate"],
  },
  {
    key: "completed",
    label: "Complete",
    matches: ["completed"],
  },
];

const TERMINAL_STATUSES = new Set(["completed", "failed", "cancelled"]);
const WAITING_STATUSES = new Set([
  "waiting_for_location_confirmation",
  "waiting_for_clarification",
  "waiting_for_approval",
]);

const TOOL_STEP_NAMES = new Set([
  "resolve_location",
  "load_geospatial_features",
  "build_scene_config",
  "load_planning_context",
  "extract_hazard_notes",
  "rank_risks",
  "create_annotations",
  "compile_review_pack",
  "output_evaluation",
  "evaluate_output_quality",
  "output_improvement_loop",
  "output_evaluator_model_call",
  "safety_gate",
  "llm_planner_tool_call",
]);

function toList(value) {
  return Array.isArray(value) ? value : [];
}

function cleanName(value) {
  return typeof value === "string" ? value.trim() : "";
}

function humanize(value) {
  const name = cleanName(value);
  if (!name) return "not started";
  return name.replace(/^tool:/, "").replaceAll("_", " ");
}

function stepKey(step) {
  return [step?.id, step?.name, step?.status, step?.timestamp, step?.summary].filter(Boolean).join("|");
}

function collectSteps(runStatus, run, latestRun) {
  const sources = [
    runStatus?.steps,
    runStatus?.partialUiState?.trace,
    runStatus?.finalUiState?.trace,
    runStatus?.result?.trace,
    run?.trace,
    run?.uiState?.trace,
    latestRun?.trace,
    latestRun?.uiState?.trace,
  ];
  const seen = new Set();
  const steps = [];
  sources.flatMap(toList).forEach((step) => {
    if (!step || typeof step !== "object") return;
    const key = stepKey(step);
    if (seen.has(key)) return;
    seen.add(key);
    steps.push(step);
  });
  return steps;
}

function stageMatchesName(stage, name) {
  const clean = cleanName(name);
  if (!clean) return false;
  return stage.matches.includes(clean) || toList(stage.matchPrefix).some((prefix) => clean.startsWith(prefix));
}

function stageIndexForName(name) {
  return STAGES.findIndex((stage) => stageMatchesName(stage, name));
}

function latestMatchingStep(steps, predicate) {
  for (let index = steps.length - 1; index >= 0; index -= 1) {
    if (predicate(steps[index])) return steps[index];
  }
  return null;
}

function hasConfirmedLocation(runStatus, steps) {
  if (runStatus?.confirmedLocation || runStatus?.locationResolution?.confirmedLocation) return true;
  return steps.some((step) => cleanName(step.name) === "location_confirmation" && step.status === "ok");
}

function lastReachedStageIndex(steps) {
  return steps.reduce((latest, step) => {
    const index = stageIndexForName(step?.name);
    return index > latest ? index : latest;
  }, -1);
}

function deriveActiveIndex(runStatus, steps, confirmingLocation) {
  if (confirmingLocation) return 0;
  if (!runStatus) return -1;
  if (runStatus.status === "completed") return STAGES.length - 1;
  if (runStatus.status === "cancelled" || runStatus.status === "failed") {
    const currentIndex = stageIndexForName(runStatus.currentStep);
    return currentIndex >= 0 ? currentIndex : Math.max(lastReachedStageIndex(steps), 0);
  }
  if (runStatus.status === "waiting_for_location_confirmation") return 0;
  const currentIndex = stageIndexForName(runStatus.currentStep);
  if (currentIndex >= 0) return currentIndex;
  return lastReachedStageIndex(steps);
}

function stageState(stageIndex, activeIndex, runStatus, steps, confirmingLocation) {
  const status = runStatus?.status || "idle";
  const stage = STAGES[stageIndex];
  const reachedIndex = Math.max(activeIndex, lastReachedStageIndex(steps));

  if (status === "completed") return "complete";
  if (stage.key === "location_confirmation" && hasConfirmedLocation(runStatus, steps)) return "complete";
  if (stageIndex < reachedIndex) return "complete";
  if (stageIndex > reachedIndex && !confirmingLocation) return "upcoming";
  if (status === "failed" && stageIndex === activeIndex) return "failed";
  if (status === "cancelled" && stageIndex === activeIndex) return "cancelled";
  if (confirmingLocation && stageIndex === 0) return "active";
  if (WAITING_STATUSES.has(status) && stageIndex === activeIndex) return "waiting";
  if (["queued", "running"].includes(status) && stageIndex === activeIndex) return "active";
  return stageIndex <= reachedIndex ? "complete" : "upcoming";
}

function statusCopy(status, confirmingLocation, loading) {
  if (confirmingLocation) return "Confirm request sent";
  if (loading && !status) return "Starting";
  if (!status) return "Ready";
  if (status === "waiting_for_location_confirmation") return "Waiting for site confirmation";
  if (status === "waiting_for_clarification") return "Waiting for clarification";
  if (status === "waiting_for_approval") return "Waiting for approval";
  return humanize(status);
}

function latestToolStep(runStatus, steps) {
  const toolResult = latestMatchingStep(toList(runStatus?.toolResults), (item) => cleanName(item.toolName));
  if (toolResult) {
    return {
      name: toolResult.toolName,
      status: toolResult.status,
      summary: "Latest recorded tool result.",
    };
  }
  return latestMatchingStep(steps, (step) => {
    const name = cleanName(step.name);
    return name.startsWith("tool:") || step.output?.toolName || TOOL_STEP_NAMES.has(name);
  });
}

function currentSummary(runStatus, steps, confirmingLocation) {
  if (confirmingLocation) {
    return "Confirming the selected candidate location before review tools continue.";
  }
  if (!runStatus) return "No run has started yet.";
  if (runStatus.errorSummary?.message) return runStatus.errorSummary.message;
  const currentStep = cleanName(runStatus.currentStep);
  const current = latestMatchingStep(steps, (step) => cleanName(step.name) === currentStep);
  if (current?.summary) return current.summary;
  if (runStatus.status === "waiting_for_location_confirmation") {
    return "Review tools are paused until a human confirms the site.";
  }
  if (runStatus.status === "queued") return "Run is queued with the backend.";
  if (runStatus.status === "cancelled") return "Run was cancelled before a complete review pack was available.";
  if (runStatus.status === "failed") return "Run failed before a complete review pack was available.";
  if (runStatus.status === "completed") return "Review pack is complete and ready for human review.";
  return "Run progress will update as the backend records steps.";
}

function StageIcon({ state }) {
  if (state === "complete") return <Check size={16} aria-hidden="true" />;
  if (state === "active") return <Loader2 className="run-progress-spin" size={16} aria-hidden="true" />;
  if (state === "waiting") return <PauseCircle size={16} aria-hidden="true" />;
  if (state === "failed") return <XCircle size={16} aria-hidden="true" />;
  if (state === "cancelled") return <AlertTriangle size={16} aria-hidden="true" />;
  return <Circle size={16} aria-hidden="true" />;
}

export function RunProgressPanel({
  runStatus = null,
  loading = false,
  confirmingLocation = false,
  latestRun = null,
  run = null,
}) {
  const steps = collectSteps(runStatus, run, latestRun);
  const activeIndex = deriveActiveIndex(runStatus, steps, confirmingLocation);
  const status = runStatus?.status || "";
  const modelCallsUsed = runStatus?.modelCallsUsed ?? run?.runtime?.modelCallCount ?? 0;
  const maxModelCalls = runStatus?.maxModelCalls ?? run?.runtime?.maxModelCalls ?? 0;
  const currentStep = confirmingLocation ? "location_confirmation" : runStatus?.currentStep;
  const latestTool = latestToolStep(runStatus, steps);
  const currentBackendStep = humanize(currentStep);
  const isTerminal = TERMINAL_STATUSES.has(status);

  return (
    <section
      className={`run-progress-panel ${isTerminal ? `run-progress-terminal run-progress-terminal-${status}` : ""}`}
      aria-live={["queued", "running"].includes(status) || confirmingLocation ? "polite" : "off"}
    >
      <div className="run-progress-header">
        <div>
          <p className="run-progress-eyebrow">Run progress</p>
          <h2>{statusCopy(status, confirmingLocation, loading)}</h2>
        </div>
        <div className="run-progress-budget" aria-label="Model-call count">
          <ShieldCheck size={16} aria-hidden="true" />
          <span>Model calls</span>
          <strong>{modelCallsUsed}/{maxModelCalls}</strong>
        </div>
      </div>

      <ol className="run-progress-stepper" aria-label="Review workflow progress">
        {STAGES.map((stage, index) => {
          const state = stageState(index, activeIndex, runStatus, steps, confirmingLocation);
          return (
            <li className={`run-progress-step is-${state}`} key={stage.key}>
              <span className="run-progress-step-icon">
                <StageIcon state={state} />
              </span>
              <span className="run-progress-step-label">{stage.label}</span>
            </li>
          );
        })}
      </ol>

      <div className="run-progress-details">
        <article>
          <span>Backend step</span>
          <strong>{currentBackendStep}</strong>
          <p>{currentSummary(runStatus, steps, confirmingLocation)}</p>
        </article>
        <article>
          <span>Latest tool step</span>
          {latestTool ? (
            <>
              <strong>{humanize(latestTool.output?.toolName || latestTool.toolName || latestTool.name)}</strong>
              <p>{latestTool.summary || humanize(latestTool.status) || "Tool step recorded."}</p>
            </>
          ) : (
            <>
              <strong>No tool step yet</strong>
              <p>Tool details will appear after the backend records an allowlisted tool call.</p>
            </>
          )}
        </article>
      </div>

      {runStatus?.fallbackReason && (
        <div className="run-progress-note">
          <Clock3 size={16} aria-hidden="true" />
          <span>{runStatus.fallbackReason}</span>
        </div>
      )}
    </section>
  );
}

export default RunProgressPanel;
