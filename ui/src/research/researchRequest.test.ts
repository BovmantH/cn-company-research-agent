import { describe, expect, it } from 'vitest';

import type { ResearchFormValues } from './model';
import {
  buildResearchRequest,
  parseResearchAcceptedResponse,
} from './researchRequest';
import type { ClientAISelection } from '../api/clientAI';


const values: ResearchFormValues = {
  companyName: '示例科技',
  companyUrl: 'example.com',
  companyHq: '上海',
  companyIndustry: '软件',
  professionalDataRequested: false,
};
const clientAI: ClientAISelection = {
  vendor: 'qwen',
  model: 'qwen3.7-plus',
  apiKey: 'sk-browser-sentinel',
};


describe('buildResearchRequest', () => {
  it('关闭专业数据时保持旧 JSON 请求体', () => {
    expect(JSON.parse(JSON.stringify(buildResearchRequest(values, null, null)))).toEqual({
      company: '示例科技',
      company_url: 'https://example.com',
      industry: '软件',
      hq_location: '上海',
    });
  });

  it('用户选择模型时只增加固定 AI 字段且不允许自定义端点', () => {
    const payload = buildResearchRequest(values, null, null, clientAI);

    expect(payload.ai).toEqual({
      vendor: 'qwen',
      model: 'qwen3.7-plus',
      api_key: 'sk-browser-sentinel',
      web_search: true,
    });
    expect(JSON.stringify(payload)).not.toContain('base_url');
  });

  it('开启后只增加服务端签发的 Token，不提交信用代码', () => {
    const payload = buildResearchRequest(
      { ...values, professionalDataRequested: true },
      'signed.resolution-token',
      null,
    );

    expect(payload.professional_data).toEqual({
      enabled: true,
      resolution_token: 'signed.resolution-token',
    });
    expect(JSON.stringify(payload)).not.toContain('credit_code');
  });

  it('关闭开关时陈旧 Token 也不能开启专业数据', () => {
    expect(buildResearchRequest(values, 'stale.resolution-token', null)).not.toHaveProperty(
      'professional_data',
    );
  });

  it('继续基础报告时只提交安全降级原因且不携带 Token', () => {
    const payload = buildResearchRequest(
      values,
      null,
      'identity_not_found',
    );

    expect(payload.professional_data).toEqual({
      enabled: false,
      fallback_reason: 'identity_not_found',
    });
    expect(JSON.stringify(payload)).not.toContain('resolution_token');
  });

  it('区分纯基础、专业受理和专业降级响应', () => {
    expect(parseResearchAcceptedResponse({
      status: 'accepted',
      job_id: 'job-base',
      message: 'ok',
    })).toEqual({ jobId: 'job-base', professionalData: null });
    expect(parseResearchAcceptedResponse({
      status: 'accepted',
      job_id: 'job-professional',
      professional_data: { status: 'accepted', reason: null },
    })?.professionalData?.status).toBe('accepted');
    expect(parseResearchAcceptedResponse({
      status: 'accepted',
      job_id: 'job-degraded',
      professional_data: { status: 'degraded', reason: 'budget_blocked' },
    })?.professionalData).toEqual({
      status: 'degraded',
      reason: 'budget_blocked',
    });
    for (const reason of [
      'identity_not_found',
      'identity_unconfirmed',
      'resolution_in_progress',
      'provider_unavailable',
    ]) {
      expect(parseResearchAcceptedResponse({
        status: 'accepted',
        job_id: `job-${reason}`,
        professional_data: { status: 'degraded', reason },
      })?.professionalData).toEqual({ status: 'degraded', reason });
    }
    expect(parseResearchAcceptedResponse({
      status: 'accepted',
      job_id: 'job-invalid',
      professional_data: {
        status: 'degraded',
        reason: 'Authorization: Bearer secret',
      },
    })).toBeNull();
  });
});
