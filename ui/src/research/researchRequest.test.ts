import { describe, expect, it } from 'vitest';

import type { ResearchFormValues } from './model';
import {
  buildResearchRequest,
  parseResearchAcceptedResponse,
} from './researchRequest';


const values: ResearchFormValues = {
  companyName: '示例科技',
  companyUrl: 'example.com',
  companyHq: '上海',
  companyIndustry: '软件',
  professionalDataRequested: false,
};


describe('buildResearchRequest', () => {
  it('关闭专业数据时保持旧 JSON 请求体', () => {
    expect(JSON.parse(JSON.stringify(buildResearchRequest(values, null)))).toEqual({
      company: '示例科技',
      company_url: 'https://example.com',
      industry: '软件',
      hq_location: '上海',
    });
  });

  it('开启后只增加服务端签发的 Token，不提交信用代码', () => {
    const payload = buildResearchRequest(
      { ...values, professionalDataRequested: true },
      'signed.resolution-token',
    );

    expect(payload.professional_data).toEqual({
      enabled: true,
      resolution_token: 'signed.resolution-token',
    });
    expect(JSON.stringify(payload)).not.toContain('credit_code');
  });

  it('关闭开关时陈旧 Token 也不能开启专业数据', () => {
    expect(buildResearchRequest(values, 'stale.resolution-token')).not.toHaveProperty(
      'professional_data',
    );
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
