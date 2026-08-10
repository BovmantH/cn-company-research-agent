export type ProfessionalCapabilityReason =
  | "not_configured"
  | "provider_unavailable"
  | "ledger_unavailable"
  | "budget_not_configured"
  | "signing_secret_missing"
  | "deployment_budget_exhausted";

type CapabilityCommon = {
  provider: "qcc_mcp";
  billing_mode: "deployment_byok";
  requires_confirmation: true;
};

export type ProfessionalCompanyDataCapability =
  | (CapabilityCommon & { enabled: true; reason: null })
  | (CapabilityCommon & {
      enabled: false;
      reason: ProfessionalCapabilityReason;
    });

export type CapabilityLoadState =
  | { status: "loading" }
  | { status: "ready"; capability: ProfessionalCompanyDataCapability }
  | { status: "unavailable"; reason: "request_failed" | "invalid_response" };

export type PublicCompanyIdentity = {
  company_name: string;
  credit_code: string;
  registration_status: string | null;
  region: string | null;
  resolution_token: string;
};

export type CompanyResolution =
  | { kind: "exact"; identity: PublicCompanyIdentity }
  | { kind: "candidates"; candidates: PublicCompanyIdentity[] }
  | { kind: "not_found" }
  | { kind: "blocked"; reason: string };

const CAPABILITY_REASONS = new Set<ProfessionalCapabilityReason>([
  "not_configured",
  "provider_unavailable",
  "ledger_unavailable",
  "budget_not_configured",
  "signing_secret_missing",
  "deployment_budget_exhausted",
]);

const RESOLUTION_REASONS = new Set([
  ...CAPABILITY_REASONS,
  "budget_blocked",
  "resolution_in_progress",
]);

const CAPABILITY_REASON_TEXT: Record<ProfessionalCapabilityReason, string> = {
  not_configured: "当前部署未启用工商司法数据。",
  provider_unavailable: "工商司法数据源暂时不可用，仍可继续基础调研。",
  ledger_unavailable: "专业数据服务暂不可用，请联系部署者。",
  budget_not_configured: "专业数据服务配置未完成，请联系部署者。",
  signing_secret_missing: "专业数据服务配置未完成，请联系部署者。",
  deployment_budget_exhausted: "今日专业数据额度已用完，仍可继续基础调研。",
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const hasOnlyKeys = (
  value: Record<string, unknown>,
  keys: readonly string[],
): boolean => Object.keys(value).every((key) => keys.includes(key));

export const capabilityReasonText = (
  reason: ProfessionalCapabilityReason,
): string => CAPABILITY_REASON_TEXT[reason];

export const parseCapabilitiesResponse = (
  value: unknown,
): ProfessionalCompanyDataCapability | null => {
  if (!isRecord(value) || !hasOnlyKeys(value, ["professional_company_data"])) {
    return null;
  }
  const capability = value.professional_company_data;
  if (
    !isRecord(capability)
    || !hasOnlyKeys(capability, [
      "enabled",
      "provider",
      "billing_mode",
      "requires_confirmation",
      "reason",
    ])
    || capability.provider !== "qcc_mcp"
    || capability.billing_mode !== "deployment_byok"
    || capability.requires_confirmation !== true
  ) return null;

  if (capability.enabled === true && capability.reason === null) {
    return capability as ProfessionalCompanyDataCapability;
  }
  if (
    capability.enabled === false
    && typeof capability.reason === "string"
    && CAPABILITY_REASONS.has(capability.reason as ProfessionalCapabilityReason)
  ) return capability as ProfessionalCompanyDataCapability;
  return null;
};

const parseIdentity = (value: unknown): PublicCompanyIdentity | null => {
  if (
    !isRecord(value)
    || !hasOnlyKeys(value, [
      "company_name",
      "credit_code",
      "registration_status",
      "region",
      "resolution_token",
    ])
    || typeof value.company_name !== "string"
    || value.company_name.length === 0
    || value.company_name.length > 200
    || typeof value.credit_code !== "string"
    || !/^[0-9A-Z]{18}$/.test(value.credit_code)
    || (value.registration_status !== null && typeof value.registration_status !== "string")
    || (value.region !== null && typeof value.region !== "string")
    || typeof value.resolution_token !== "string"
    || value.resolution_token.length < 10
    || value.resolution_token.length > 4096
  ) return null;
  return value as PublicCompanyIdentity;
};

export const parseCompanyResolution = (value: unknown): CompanyResolution | null => {
  if (
    !isRecord(value)
    || !hasOnlyKeys(value, ["kind", "identity", "candidates", "reason"])
    || !Array.isArray(value.candidates)
  ) return null;

  if (value.kind === "exact" && value.candidates.length === 0 && value.reason === null) {
    const identity = parseIdentity(value.identity);
    return identity ? { kind: "exact", identity } : null;
  }
  if (
    value.kind === "candidates"
    && value.identity === null
    && value.reason === null
    && value.candidates.length >= 2
    && value.candidates.length <= 5
  ) {
    const candidates = value.candidates.map(parseIdentity);
    return candidates.every((candidate) => candidate !== null)
      ? { kind: "candidates", candidates: candidates as PublicCompanyIdentity[] }
      : null;
  }
  if (
    value.kind === "not_found"
    && value.identity === null
    && value.candidates.length === 0
    && value.reason === null
  ) return { kind: "not_found" };
  if (
    value.kind === "blocked"
    && value.identity === null
    && value.candidates.length === 0
    && typeof value.reason === "string"
    && RESOLUTION_REASONS.has(value.reason)
  ) return { kind: "blocked", reason: value.reason };
  return null;
};

/** 能力探测始终默认关闭，网络异常和非法响应不会阻断基础调研。 */
export const loadCapabilities = async (
  apiUrl: string,
  signal?: AbortSignal,
): Promise<CapabilityLoadState> => {
  try {
    const response = await fetch(`${apiUrl}/capabilities`, {
      headers: { Accept: "application/json" },
      signal,
    });
    if (!response.ok) return { status: "unavailable", reason: "request_failed" };
    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      return { status: "unavailable", reason: "invalid_response" };
    }
    const capability = parseCapabilitiesResponse(payload);
    return capability
      ? { status: "ready", capability }
      : { status: "unavailable", reason: "invalid_response" };
  } catch {
    return { status: "unavailable", reason: "request_failed" };
  }
};

/** 只返回经过白名单校验的主体响应，绝不把上游或 HTTP 错误正文交给界面。 */
export const resolveCompany = async (
  apiUrl: string,
  query: string,
  idempotencyKey: string,
  signal?: AbortSignal,
): Promise<CompanyResolution> => {
  const response = await fetch(`${apiUrl}/companies/resolve`, {
    method: "POST",
    mode: "cors",
    credentials: "omit",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey,
    },
    body: JSON.stringify({ query }),
    signal,
  });
  if (!response.ok && response.status !== 202) {
    throw new Error("企业主体解析请求失败");
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new Error("企业主体解析响应无效");
  }
  const resolution = parseCompanyResolution(payload);
  if (!resolution) throw new Error("企业主体解析响应无效");
  return resolution;
};
