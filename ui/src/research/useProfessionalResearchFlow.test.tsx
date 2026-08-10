import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  loadCapabilities,
  resolveCompany,
  type CompanyResolution,
} from '../api/companyIntelligence';
import type { ResearchFormValues } from './model';
import { useProfessionalResearchFlow } from './useProfessionalResearchFlow';


vi.mock('../api/companyIntelligence', async (importOriginal) => {
  const original = await importOriginal<typeof import('../api/companyIntelligence')>();
  return {
    ...original,
    loadCapabilities: vi.fn(),
    resolveCompany: vi.fn(),
  };
});

const loadCapabilitiesMock = vi.mocked(loadCapabilities);
const resolveCompanyMock = vi.mocked(resolveCompany);

const values: ResearchFormValues = {
  companyName: '示例科技',
  companyUrl: '',
  companyHq: '',
  companyIndustry: '',
  professionalDataRequested: true,
};

const identity = (suffix: string, token: string) => ({
  company_name: `示例科技${suffix}有限公司`,
  credit_code: `91320594MA1N0000${suffix}`,
  registration_status: '存续',
  region: '江苏省',
  resolution_token: token,
});

type HookValue = ReturnType<typeof useProfessionalResearchFlow>;

const renderHook = async (): Promise<{
  current: () => HookValue;
  renderer: ReactTestRenderer;
}> => {
  let latest: HookValue | null = null;
  const Harness = () => {
    latest = useProfessionalResearchFlow('http://api.test');
    return null;
  };
  let renderer!: ReactTestRenderer;
  await act(async () => {
    renderer = create(<Harness />);
    await Promise.resolve();
  });
  return {
    current: () => {
      if (!latest) throw new Error('hook_not_ready');
      return latest;
    },
    renderer,
  };
};

const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
};


describe('useProfessionalResearchFlow', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    loadCapabilitiesMock.mockResolvedValue({
      status: 'ready',
      capability: {
        enabled: true,
        provider: 'qcc_mcp',
        billing_mode: 'deployment_byok',
        requires_confirmation: true,
        reason: null,
      },
    });
  });

  it('关闭专业数据时直接放行基础调研且不解析主体', async () => {
    const hook = await renderHook();
    const baseValues = { ...values, professionalDataRequested: false };
    const outcome = await hook.current().prepare(baseValues);

    expect(outcome).toEqual({
      kind: 'ready',
      prepared: { values: baseValues, resolutionToken: null },
    });
    expect(resolveCompanyMock).not.toHaveBeenCalled();
    hook.renderer.unmount();
  });

  it('重复提交只启动一次付费主体解析', async () => {
    const result = deferred<CompanyResolution>();
    resolveCompanyMock.mockReturnValue(result.promise);
    const hook = await renderHook();

    let first!: ReturnType<HookValue['prepare']>;
    let second!: ReturnType<HookValue['prepare']>;
    await act(async () => {
      first = hook.current().prepare(values);
      second = hook.current().prepare(values);
      await Promise.resolve();
    });

    expect(resolveCompanyMock).toHaveBeenCalledTimes(1);
    await expect(second).resolves.toEqual({ kind: 'pending' });

    await act(async () => {
      result.resolve({ kind: 'exact', identity: identity('0', 'signed.exact-token') });
      await first;
    });
    hook.renderer.unmount();
  });

  it('研究提交失败时复用解析键，受理成功后下一任务才换新键', async () => {
    resolveCompanyMock.mockResolvedValue({
      kind: 'exact',
      identity: identity('0', 'signed.exact-token'),
    });
    const hook = await renderHook();

    await act(async () => {
      await hook.current().prepare(values);
      await hook.current().prepare(values);
    });
    const firstKey = resolveCompanyMock.mock.calls[0][2];
    const retryKey = resolveCompanyMock.mock.calls[1][2];
    expect(retryKey).toBe(firstKey);

    hook.current().markResearchAccepted({ status: 'accepted', reason: null });
    await act(async () => {
      await hook.current().prepare(values);
    });
    expect(resolveCompanyMock.mock.calls[2][2]).not.toBe(firstKey);
    hook.renderer.unmount();
  });

  it('纯基础或预算降级保留解析键，Token 消费后才轮换', async () => {
    resolveCompanyMock.mockResolvedValue({
      kind: 'exact',
      identity: identity('0', 'signed.exact-token'),
    });
    const hook = await renderHook();

    await act(async () => {
      await hook.current().prepare(values);
    });
    const firstKey = resolveCompanyMock.mock.calls[0][2];

    hook.current().markResearchAccepted(null);
    await act(async () => {
      await hook.current().prepare(values);
    });
    expect(resolveCompanyMock.mock.calls[1][2]).toBe(firstKey);

    hook.current().markResearchAccepted({
      status: 'degraded',
      reason: 'budget_blocked',
    });
    await act(async () => {
      await hook.current().prepare(values);
    });
    expect(resolveCompanyMock.mock.calls[2][2]).toBe(firstKey);

    hook.current().markResearchAccepted({ status: 'replayed', reason: null });
    await act(async () => {
      await hook.current().prepare(values);
    });
    expect(resolveCompanyMock.mock.calls[3][2]).not.toBe(firstKey);
    hook.renderer.unmount();
  });

  it.each([
    { status: 'in_progress', reason: null },
    { status: 'degraded', reason: 'identity_unconfirmed' },
  ] as const)('$status/$reason 受理状态会轮换已失效的解析键', async (acceptance) => {
    resolveCompanyMock.mockResolvedValue({
      kind: 'exact',
      identity: identity('0', 'signed.exact-token'),
    });
    const hook = await renderHook();

    await act(async () => {
      await hook.current().prepare(values);
    });
    const firstKey = resolveCompanyMock.mock.calls[0][2];
    hook.current().markResearchAccepted(acceptance);
    await act(async () => {
      await hook.current().prepare(values);
    });

    expect(resolveCompanyMock.mock.calls[1][2]).not.toBe(firstKey);
    hook.renderer.unmount();
  });

  it('候选可渲染状态不含 Token，选择项只取回对应 Token', async () => {
    resolveCompanyMock.mockResolvedValue({
      kind: 'candidates',
      candidates: [
        identity('0', 'signed.first-token'),
        identity('1', 'signed.second-token'),
      ],
    });
    const hook = await renderHook();

    await act(async () => {
      await hook.current().prepare(values);
    });

    const state = hook.current().flowState;
    expect(state.status).toBe('candidates');
    expect(JSON.stringify(state)).not.toContain('signed.');
    if (state.status !== 'candidates') throw new Error('candidates_not_ready');

    const selected = hook.current().selectCandidate(state.candidates[1].view_id);
    expect(selected?.resolutionToken).toBe('signed.second-token');
    expect(hook.current().selectCandidate(state.candidates[1].view_id)).toBeNull();
    expect(JSON.stringify(hook.current().flowState)).not.toContain('signed.');
    hook.renderer.unmount();
  });

  it('降级为基础报告时完整保留草稿并关闭专业开关', async () => {
    resolveCompanyMock.mockResolvedValue({ kind: 'not_found' });
    const hook = await renderHook();

    await act(async () => {
      await hook.current().prepare(values);
    });
    const prepared = hook.current().continueBasic();

    expect(prepared).toEqual({
      values: { ...values, professionalDataRequested: false },
      resolutionToken: null,
    });
    expect(hook.current().flowState).toEqual({ status: 'idle' });
    expect(resolveCompanyMock).toHaveBeenCalledTimes(1);
    hook.renderer.unmount();
  });

  it('取消后丢弃晚到响应并清空候选状态', async () => {
    const result = deferred<CompanyResolution>();
    resolveCompanyMock.mockReturnValue(result.promise);
    const hook = await renderHook();
    let pending!: ReturnType<HookValue['prepare']>;

    await act(async () => {
      pending = hook.current().prepare(values);
      await Promise.resolve();
      hook.current().cancel();
    });
    await act(async () => {
      result.resolve({
        kind: 'candidates',
        candidates: [
          identity('0', 'signed.first-token'),
          identity('1', 'signed.second-token'),
        ],
      });
      await pending;
    });

    expect(hook.current().flowState).toEqual({ status: 'idle' });
    hook.renderer.unmount();
  });

  it('组件卸载后让晚到解析结果失效', async () => {
    const result = deferred<CompanyResolution>();
    resolveCompanyMock.mockReturnValue(result.promise);
    const hook = await renderHook();
    const pending = hook.current().prepare(values);

    await act(async () => {
      hook.renderer.unmount();
    });
    result.resolve({ kind: 'exact', identity: identity('0', 'signed.late-token') });

    await expect(pending).resolves.toEqual({ kind: 'pending' });
  });
});
