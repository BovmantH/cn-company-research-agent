import type {
  EnrichmentCounts,
  ResearchCategory,
  ResearchOutput,
  ResearchStatusType,
} from "../types";

export type ResearchPhase =
  | "search"
  | "enrichment"
  | "briefing"
  | "complete"
  | null;

export type ResearchLifecycle =
  | "idle"
  | "running"
  | "completed"
  | "failed"
  | "reset_required";
export type StreamConnection =
  | "idle"
  | "connected"
  | "reconnecting"
  | "reset_required";

export type ResearchQuery = {
  text: string;
  number: number;
  category: string;
};

export type StreamingResearchQuery = ResearchQuery & { isComplete: boolean };

type EventEnvelope = {
  version: 1;
  event_id: number;
};

type ProgressEvent = EventEnvelope & { type: "progress"; step: string };
type QueryGeneratingEvent = EventEnvelope & {
  type: "query_generating";
  query: string;
  query_number: number;
  category: string;
};
type QueryGeneratedEvent = EventEnvelope & {
  type: "query_generated";
  query: string;
  query_number: number;
  category: string;
};
type ResearchInitEvent = EventEnvelope & {
  type: "research_init";
  company?: string;
  message?: string;
};
type CrawlStartEvent = EventEnvelope & {
  type: "crawl_start";
  message?: string;
};
type CurationEvent = EventEnvelope & {
  type: "curation";
  category?: string;
  total?: number;
  message?: string;
};
type EnrichmentEvent = EventEnvelope & {
  type: "enrichment";
  category?: string;
  total?: number;
  enriched?: number;
  message?: string;
};
type BriefingStartEvent = EventEnvelope & {
  type: "briefing_start";
  category: string;
  total_docs: number;
};
type BriefingCompleteEvent = EventEnvelope & {
  type: "briefing_complete";
  category: string;
  content_length: number;
};
type ReportCompilationEvent = EventEnvelope & {
  type: "report_compilation";
  message?: string;
};
type ReportChunkEvent = EventEnvelope & {
  type: "report_chunk";
  chunk: string;
};
type CompleteEvent = EventEnvelope & { type: "complete"; report: string };
type ErrorEvent = EventEnvelope & {
  type: "error";
  error?: string;
  reason?: string;
};
type ProfessionalEvent = EventEnvelope & {
  type:
    | "professional_data_started"
    | "professional_data_progress"
    | "professional_data_completed";
};
type DegradationEvent = EventEnvelope & {
  type:
    | "professional_data_degraded"
    | "professional_data_budget_blocked"
    | "report_degraded"
    | "briefing_degraded"
    | "research_degraded"
    | "crawl_error"
    | "query_error";
  reason?: string;
};
type ExplicitNoopEvent = EventEnvelope & {
  type:
    | "crawl_success"
    | "crawl_warning"
    | "grounding_complete"
    | "no_url"
    | "queries_complete"
    | "search_started"
    | "search_complete"
    | "analysis_complete"
    | "company_resolution_started"
    | "company_resolution_required";
};

export type ResearchSseEvent =
  | ProgressEvent
  | QueryGeneratingEvent
  | QueryGeneratedEvent
  | ResearchInitEvent
  | CrawlStartEvent
  | CurationEvent
  | EnrichmentEvent
  | BriefingStartEvent
  | BriefingCompleteEvent
  | ReportCompilationEvent
  | ReportChunkEvent
  | CompleteEvent
  | ErrorEvent
  | ProfessionalEvent
  | DegradationEvent
  | ExplicitNoopEvent;

export type StreamControlSignal = {
  type: "stream_error" | "stream_reset_required";
  reason?: string;
};

export type ProfessionalStreamState = {
  status:
    | "not_requested"
    | "running"
    | "completed"
    | "degraded"
    | "budget_blocked";
  reason: string | null;
};

type Degradation = {
  eventId: number;
  type: DegradationEvent["type"];
  reason: string;
};

export type ResearchStreamState = {
  lifecycle: ResearchLifecycle;
  connection: StreamConnection;
  lastEventId: number;
  status: ResearchStatusType | null;
  output: ResearchOutput | null;
  error: string | null;
  currentPhase: ResearchPhase;
  queries: ResearchQuery[];
  streamingQueries: Record<string, StreamingResearchQuery>;
  enrichmentCounts: EnrichmentCounts | undefined;
  briefingStatus: Record<ResearchCategory, boolean>;
  isReportStreaming: boolean;
  professional: ProfessionalStreamState;
  degradations: Degradation[];
};

export type ResearchStreamAction =
  | { type: "start" }
  | { type: "reset" }
  | { type: "connection_open" }
  | { type: "connection_lost" }
  | { type: "stream_reset_required"; message?: string }
  | { type: "submit_failed"; message: string }
  | { type: "ui_error"; message: string }
  | { type: "event"; event: ResearchSseEvent };

const EVENT_TYPES = new Set<ResearchSseEvent["type"]>([
  "progress",
  "query_generating",
  "query_generated",
  "research_init",
  "crawl_start",
  "curation",
  "enrichment",
  "briefing_start",
  "briefing_complete",
  "report_compilation",
  "report_chunk",
  "complete",
  "error",
  "professional_data_started",
  "professional_data_progress",
  "professional_data_completed",
  "professional_data_degraded",
  "professional_data_budget_blocked",
  "report_degraded",
  "briefing_degraded",
  "research_degraded",
  "crawl_error",
  "query_error",
  "crawl_success",
  "crawl_warning",
  "grounding_complete",
  "no_url",
  "queries_complete",
  "search_started",
  "search_complete",
  "analysis_complete",
  "company_resolution_started",
  "company_resolution_required",
]);

const CATEGORIES: ResearchCategory[] = [
  "company",
  "industry",
  "financial",
  "news",
];

const CATEGORY_LABELS: Record<ResearchCategory, string> = {
  company: "公司",
  industry: "行业",
  financial: "财务",
  news: "新闻",
};

const STEP_LABELS: Record<string, string> = {
  grounding: "检索",
  financial_analyst: "检索",
  news_scanner: "检索",
  industry_analyst: "检索",
  company_analyst: "检索",
  collector: "检索",
  curator: "抽取增强",
  enricher: "抽取增强",
  briefing: "简报生成",
  editor: "收尾整理",
  report: "收尾整理",
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null;

const isCategory = (value: unknown): value is ResearchCategory =>
  typeof value === "string" && CATEGORIES.includes(value as ResearchCategory);

const isOptionalString = (value: unknown): boolean =>
  value === undefined || typeof value === "string";

const isNonNegativeInteger = (value: unknown): boolean =>
  Number.isInteger(value) && Number(value) >= 0;

const hasValidEventFields = (value: Record<string, unknown>): boolean => {
  switch (value.type) {
    case "progress":
      return typeof value.step === "string";
    case "query_generating":
    case "query_generated":
      return typeof value.query === "string"
        && Number.isInteger(value.query_number)
        && Number(value.query_number) > 0
        && isCategory(value.category);
    case "research_init":
      return isOptionalString(value.company) && isOptionalString(value.message);
    case "crawl_start":
    case "report_compilation":
      return isOptionalString(value.message);
    case "curation":
      return (value.category === undefined || isCategory(value.category))
        && (value.total === undefined || isNonNegativeInteger(value.total))
        && isOptionalString(value.message);
    case "enrichment":
      return (value.category === undefined || isCategory(value.category))
        && (value.total === undefined || isNonNegativeInteger(value.total))
        && (value.enriched === undefined || isNonNegativeInteger(value.enriched))
        && isOptionalString(value.message);
    case "briefing_start":
      return isCategory(value.category) && isNonNegativeInteger(value.total_docs);
    case "briefing_complete":
      return isCategory(value.category) && isNonNegativeInteger(value.content_length);
    case "report_chunk":
      return typeof value.chunk === "string";
    case "complete":
      return typeof value.report === "string";
    case "error":
      return isOptionalString(value.error) && isOptionalString(value.reason);
    case "professional_data_degraded":
    case "professional_data_budget_blocked":
    case "report_degraded":
    case "briefing_degraded":
    case "research_degraded":
    case "crawl_error":
    case "query_error":
      return isOptionalString(value.reason);
    default:
      return true;
  }
};

const labelOf = (category: unknown): string =>
  isCategory(category) ? CATEGORY_LABELS[category] : String(category ?? "");

const phaseForStep = (step: string): ResearchPhase => {
  if ([
    "grounding",
    "financial_analyst",
    "news_scanner",
    "industry_analyst",
    "company_analyst",
    "collector",
  ].includes(step)) return "search";
  if (["curator", "enricher"].includes(step)) return "enrichment";
  if (["briefing", "editor", "report"].includes(step)) return "briefing";
  return null;
};

const addDegradation = (
  state: ResearchStreamState,
  event: DegradationEvent,
): ResearchStreamState => {
  const reason = event.reason || "unavailable";
  const professional = event.type === "professional_data_budget_blocked"
    ? { status: "budget_blocked" as const, reason }
    : event.type === "professional_data_degraded"
      ? { status: "degraded" as const, reason }
      : state.professional;
  return {
    ...state,
    professional,
    degradations: [
      ...state.degradations.slice(-49),
      { eventId: event.event_id, type: event.type, reason },
    ],
  };
};

export const createInitialResearchStreamState = (): ResearchStreamState => ({
  lifecycle: "idle",
  connection: "idle",
  lastEventId: 0,
  status: null,
  output: null,
  error: null,
  currentPhase: null,
  queries: [],
  streamingQueries: {},
  enrichmentCounts: undefined,
  briefingStatus: {
    company: false,
    industry: false,
    financial: false,
    news: false,
  },
  isReportStreaming: false,
  professional: { status: "not_requested", reason: null },
  degradations: [],
});

/** 把未知 JSON 限制在已声明的 SSE 类型集合内，拒绝无版本或无游标事件。 */
export const parseResearchSsePayload = (
  value: unknown,
): ResearchSseEvent | StreamControlSignal | null => {
  if (!isRecord(value) || typeof value.type !== "string") return null;
  if (value.type === "stream_error" || value.type === "stream_reset_required") {
    return {
      type: value.type,
      reason: typeof value.reason === "string" ? value.reason : undefined,
    };
  }
  if (
    value.version !== 1
    || !Number.isInteger(value.event_id)
    || Number(value.event_id) <= 0
    || !EVENT_TYPES.has(value.type as ResearchSseEvent["type"])
    || !hasValidEventFields(value)
  ) return null;
  return value as unknown as ResearchSseEvent;
};

/** 校验 SSE 帧游标与正文游标一致，避免错误大游标吞掉后续合法事件。 */
export const hasMatchingSseEventId = (
  transportEventId: string,
  event: ResearchSseEvent,
): boolean => {
  const parsedTransportId = Number(transportEventId);
  return Number.isInteger(parsedTransportId)
    && parsedTransportId > 0
    && parsedTransportId === event.event_id;
};

/** 纯函数投影任务事件；先去重，再保证第一个业务终态不可被后续事件覆盖。 */
export const researchStreamReducer = (
  state: ResearchStreamState,
  action: ResearchStreamAction,
): ResearchStreamState => {
  if (action.type === "reset") return createInitialResearchStreamState();
  if (action.type === "start") {
    return {
      ...createInitialResearchStreamState(),
      lifecycle: "running",
      status: { step: "处理中", message: "正在启动调研……" },
    };
  }
  if (action.type === "connection_open") {
    return { ...state, connection: "connected" };
  }
  if (action.type === "connection_lost") {
    if (
      state.lifecycle === "completed"
      || state.lifecycle === "failed"
      || state.lifecycle === "reset_required"
    ) return state;
    return { ...state, connection: "reconnecting" };
  }
  if (action.type === "stream_reset_required") {
    const message = action.message || "进度历史已过期，请重新打开该调研任务";
    return {
      ...state,
      lifecycle: "reset_required",
      connection: "reset_required",
      error: message,
      status: { step: "进度不可恢复", message: "请重新发起调研" },
    };
  }
  if (action.type === "submit_failed") {
    return {
      ...state,
      lifecycle: "failed",
      connection: "idle",
      error: action.message,
      status: { step: "启动失败", message: action.message },
    };
  }
  if (action.type === "ui_error") {
    return { ...state, error: action.message };
  }

  const event = action.event;
  if (event.event_id <= state.lastEventId) return state;
  const current = { ...state, lastEventId: event.event_id };
  if (
    state.lifecycle === "completed"
    || state.lifecycle === "failed"
    || state.lifecycle === "reset_required"
  ) return current;

  switch (event.type) {
    case "progress": {
      const phase = phaseForStep(event.step);
      return {
        ...current,
        currentPhase: phase ?? current.currentPhase,
        status: {
          step: STEP_LABELS[event.step] || event.step,
          message: `正在处理「${event.step}」节点……`,
        },
      };
    }
    case "query_generating": {
      const key = `${event.category}_${event.query_number}`;
      return {
        ...current,
        currentPhase: "search",
        status: {
          step: "检索",
          message: `第 ${event.query_number} 条 Query：${event.query}`,
        },
        streamingQueries: {
          ...current.streamingQueries,
          [key]: {
            text: event.query,
            number: event.query_number,
            category: event.category,
            isComplete: false,
          },
        },
      };
    }
    case "query_generated": {
      const key = `${event.category}_${event.query_number}`;
      const streamingQueries = { ...current.streamingQueries };
      delete streamingQueries[key];
      return {
        ...current,
        currentPhase: "search",
        status: { step: "检索", message: `已生成 Query：${event.query}` },
        queries: [
          ...current.queries,
          {
            text: event.query,
            number: event.query_number,
            category: event.category,
          },
        ],
        streamingQueries,
      };
    }
    case "research_init":
      return {
        ...current,
        lifecycle: "running",
        currentPhase: "search",
        status: {
          step: "初始化",
          message: event.message || `开始调研 ${event.company || ""}`,
        },
      };
    case "crawl_start":
      return {
        ...current,
        currentPhase: "search",
        status: { step: "网站抓取", message: event.message || "正在抓取公司官网……" },
      };
    case "curation": {
      const enrichmentCounts = { ...current.enrichmentCounts };
      if (isCategory(event.category)) {
        enrichmentCounts[event.category] = { total: event.total || 0, enriched: 0 };
      }
      return {
        ...current,
        currentPhase: "enrichment",
        status: {
          step: "数据筛选",
          message: event.message || `正在筛选「${labelOf(event.category)}」类文档`,
        },
        enrichmentCounts,
      };
    }
    case "enrichment": {
      const enrichmentCounts = { ...current.enrichmentCounts };
      if (isCategory(event.category) && event.enriched !== undefined) {
        const previous = enrichmentCounts[event.category];
        enrichmentCounts[event.category] = {
          total: previous?.total || event.total || 0,
          enriched: event.enriched,
        };
      }
      return {
        ...current,
        currentPhase: "enrichment",
        status: {
          step: "抽取增强",
          message: event.message || "正在为文档抽取补充内容",
        },
        enrichmentCounts,
      };
    }
    case "briefing_start":
      return {
        ...current,
        currentPhase: "briefing",
        status: {
          step: "简报生成中",
          message: `基于 ${event.total_docs || 0} 篇文档生成「${labelOf(event.category)}」简报`,
        },
      };
    case "briefing_complete": {
      const briefingStatus = { ...current.briefingStatus };
      if (isCategory(event.category)) briefingStatus[event.category] = true;
      return {
        ...current,
        currentPhase: "briefing",
        status: {
          step: "简报完成",
          message: `「${labelOf(event.category)}」简报已生成(${event.content_length || 0} 字符)`,
        },
        briefingStatus,
      };
    }
    case "report_compilation":
      return {
        ...current,
        currentPhase: "briefing",
        status: { step: "报告生成中", message: event.message || "正在编排最终报告" },
      };
    case "report_chunk": {
      const report = `${current.output?.details.report || ""}${event.chunk}`;
      return {
        ...current,
        isReportStreaming: true,
        output: { summary: "", details: { report } },
        status: { step: "报告生成中", message: "正在生成最终报告……" },
      };
    }
    case "complete":
      return {
        ...current,
        lifecycle: "completed",
        connection: "idle",
        error: null,
        currentPhase: "complete",
        isReportStreaming: false,
        output: { summary: "", details: { report: event.report } },
        status: { step: "完成", message: "调研已完成" },
      };
    case "error":
      return {
        ...current,
        lifecycle: "failed",
        connection: "idle",
        isReportStreaming: false,
        error: event.error || "调研任务执行失败",
        status: { step: "调研失败", message: event.error || "调研任务执行失败" },
      };
    case "professional_data_started":
    case "professional_data_progress":
      return {
        ...current,
        professional: { status: "running", reason: null },
      };
    case "professional_data_completed":
      return {
        ...current,
        professional: current.professional.status === "degraded"
          || current.professional.status === "budget_blocked"
          ? current.professional
          : { status: "completed", reason: null },
      };
    case "professional_data_degraded":
    case "professional_data_budget_blocked":
    case "report_degraded":
    case "briefing_degraded":
    case "research_degraded":
    case "crawl_error":
    case "query_error":
      return addDegradation(current, event);
    default:
      return current;
  }
};
