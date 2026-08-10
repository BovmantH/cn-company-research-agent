/** 前后端共同约定、允许写入基础报告的专业数据降级原因。 */
export const PROFESSIONAL_FALLBACK_REASONS = [
  'identity_not_found',
  'identity_unconfirmed',
  'resolution_in_progress',
  'provider_unavailable',
] as const;

export type ProfessionalFallbackReason =
  typeof PROFESSIONAL_FALLBACK_REASONS[number];

/** 集中维护公开文案，确保受控原因不会在不同界面产生语义漂移。 */
export const PROFESSIONAL_FALLBACK_REASON_TEXT: Readonly<
  Record<ProfessionalFallbackReason, string>
> = {
  identity_not_found: '未找到可确认的公司主体，基础 Web 报告仍会正常交付。',
  identity_unconfirmed: '公司主体尚未完成确认，基础 Web 报告仍会正常交付。',
  resolution_in_progress: '公司主体解析仍在进行，基础 Web 报告仍会正常交付。',
  provider_unavailable: '专业数据源暂时不可用，基础 Web 报告仍会正常交付。',
};

export const isProfessionalFallbackReason = (
  reason: string,
): reason is ProfessionalFallbackReason => (
  PROFESSIONAL_FALLBACK_REASONS.some((candidate) => candidate === reason)
);
