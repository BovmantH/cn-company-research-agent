import { afterEach, describe, expect, it, vi } from "vitest";

import {
  capabilityReasonText,
  loadCapabilities,
  parseCapabilitiesResponse,
  parseCompanyResolution,
} from "./companyIntelligence";


const enabledCapability = {
  professional_company_data: {
    enabled: true,
    provider: "qcc_mcp",
    billing_mode: "deployment_byok",
    requires_confirmation: true,
    reason: null,
  },
};


describe("companyIntelligence API contracts", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("只接受完整且一致的能力响应", () => {
    expect(parseCapabilitiesResponse(enabledCapability)).toEqual(
      enabledCapability.professional_company_data,
    );
    expect(parseCapabilitiesResponse({
      professional_company_data: {
        ...enabledCapability.professional_company_data,
        enabled: false,
      },
    })).toBeNull();
    expect(parseCapabilitiesResponse({
      professional_company_data: {
        ...enabledCapability.professional_company_data,
        provider: "unknown",
      },
    })).toBeNull();
  });

  it.each([
    "not_configured",
    "provider_unavailable",
    "ledger_unavailable",
    "budget_not_configured",
    "signing_secret_missing",
    "deployment_budget_exhausted",
  ] as const)("安全映射关闭原因 %s", (reason) => {
    const parsed = parseCapabilitiesResponse({
      professional_company_data: {
        ...enabledCapability.professional_company_data,
        enabled: false,
        reason,
      },
    });

    expect(parsed?.enabled).toBe(false);
    expect(capabilityReasonText(reason)).not.toContain(reason);
  });

  it("拒绝未知关闭原因", () => {
    expect(parseCapabilitiesResponse({
      professional_company_data: {
        ...enabledCapability.professional_company_data,
        enabled: false,
        reason: "Authorization: Bearer secret",
      },
    })).toBeNull();
  });

  it("网络、HTTP 和非法 JSON 都安全关闭能力且不回显正文", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    fetchMock.mockRejectedValueOnce(new Error("Authorization: Bearer secret"));
    await expect(loadCapabilities("http://api.test")).resolves.toEqual({
      status: "unavailable",
      reason: "request_failed",
    });

    fetchMock.mockResolvedValueOnce(new Response("upstream secret", { status: 503 }));
    await expect(loadCapabilities("http://api.test")).resolves.toEqual({
      status: "unavailable",
      reason: "request_failed",
    });

    fetchMock.mockResolvedValueOnce(new Response("not-json", {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
    await expect(loadCapabilities("http://api.test")).resolves.toEqual({
      status: "unavailable",
      reason: "invalid_response",
    });
  });

  it("只接受四种互斥的主体解析响应", () => {
    const candidate = {
      company_name: "示例科技有限公司",
      credit_code: "91320594MA1N00000X",
      registration_status: "存续",
      region: "江苏省",
      resolution_token: "signed.resolution-token",
    };

    expect(parseCompanyResolution({
      kind: "exact",
      identity: candidate,
      candidates: [],
      reason: null,
    })?.kind).toBe("exact");
    expect(parseCompanyResolution({
      kind: "candidates",
      identity: null,
      candidates: [candidate, { ...candidate, credit_code: "91320594MA1N00001R" }],
      reason: null,
    })?.kind).toBe("candidates");
    expect(parseCompanyResolution({
      kind: "not_found",
      identity: null,
      candidates: [],
      reason: null,
    })?.kind).toBe("not_found");
    expect(parseCompanyResolution({
      kind: "blocked",
      identity: null,
      candidates: [],
      reason: "budget_blocked",
    })?.kind).toBe("blocked");
  });

  it("拒绝缺 Token、候选数量错误或形状冲突的主体响应", () => {
    const invalidIdentity = {
      company_name: "示例科技有限公司",
      credit_code: "91320594MA1N00000X",
      registration_status: "存续",
      region: "江苏省",
    };
    expect(parseCompanyResolution({
      kind: "exact",
      identity: invalidIdentity,
      candidates: [],
      reason: null,
    })).toBeNull();
    expect(parseCompanyResolution({
      kind: "candidates",
      identity: null,
      candidates: [invalidIdentity],
      reason: null,
    })).toBeNull();
    expect(parseCompanyResolution({
      kind: "not_found",
      identity: invalidIdentity,
      candidates: [],
      reason: null,
    })).toBeNull();
  });
});
