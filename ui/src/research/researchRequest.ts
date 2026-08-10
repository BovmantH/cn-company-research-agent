import type { ResearchFormValues } from './model';
import {
  PROFESSIONAL_FALLBACK_REASONS,
  type ProfessionalFallbackReason,
} from './professionalFallback';


export type { ProfessionalFallbackReason } from './professionalFallback';

type ResearchRequestPayload = {
  company: string;
  company_url: string | undefined;
  industry: string | undefined;
  hq_location: string | undefined;
  professional_data?:
    | {
        enabled: true;
        resolution_token: string;
      }
    | {
        enabled: false;
        fallback_reason: ProfessionalFallbackReason;
      };
};

export type ProfessionalResearchAcceptance = {
  status: 'accepted' | 'in_progress' | 'replayed' | 'degraded';
  reason: string | null;
};

export type ResearchAcceptedResponse = {
  jobId: string;
  professionalData: ProfessionalResearchAcceptance | null;
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const ACCEPTANCE_STATUSES = new Set([
  'accepted',
  'in_progress',
  'replayed',
  'degraded',
]);

const PROFESSIONAL_DEGRADED_REASONS = new Set([
  'not_configured',
  'provider_unavailable',
  'ledger_unavailable',
  'budget_not_configured',
  'signing_secret_missing',
  'deployment_budget_exhausted',
  ...PROFESSIONAL_FALLBACK_REASONS,
  'idempotency_conflict',
  'budget_blocked',
]);

/** 关闭专业数据时不增加任何新字段，保持旧客户端请求契约。 */
export const buildResearchRequest = (
  values: ResearchFormValues,
  resolutionToken: string | null,
  professionalFallbackReason: ProfessionalFallbackReason | null,
): ResearchRequestPayload => {
  const companyUrl = values.companyUrl
    ? values.companyUrl.startsWith('http://') || values.companyUrl.startsWith('https://')
      ? values.companyUrl
      : `https://${values.companyUrl}`
    : undefined;
  return {
    company: values.companyName,
    company_url: companyUrl,
    industry: values.companyIndustry || undefined,
    hq_location: values.companyHq || undefined,
    ...(values.professionalDataRequested && resolutionToken
      ? {
          professional_data: {
            enabled: true as const,
            resolution_token: resolutionToken,
          },
        }
      : professionalFallbackReason
        ? {
            professional_data: {
              enabled: false as const,
              fallback_reason: professionalFallbackReason,
            },
          }
        : {}),
  };
};

/** 只读取研究受理所需字段，忽略服务端展示文案并拒绝状态组合漂移。 */
export const parseResearchAcceptedResponse = (
  value: unknown,
): ResearchAcceptedResponse | null => {
  if (
    !isRecord(value)
    || value.status !== 'accepted'
    || typeof value.job_id !== 'string'
    || value.job_id.length === 0
    || (value.message !== undefined && typeof value.message !== 'string')
  ) return null;

  if (value.professional_data === undefined) {
    return { jobId: value.job_id, professionalData: null };
  }
  const professional = value.professional_data;
  if (
    !isRecord(professional)
    || typeof professional.status !== 'string'
    || !ACCEPTANCE_STATUSES.has(professional.status)
    || (
      professional.status === 'degraded'
        ? typeof professional.reason !== 'string'
          || !PROFESSIONAL_DEGRADED_REASONS.has(professional.reason)
        : professional.reason !== null
    )
  ) return null;
  return {
    jobId: value.job_id,
    professionalData: professional as ProfessionalResearchAcceptance,
  };
};
