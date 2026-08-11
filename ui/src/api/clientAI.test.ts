import { describe, expect, it, vi } from 'vitest';

import {
  loadClientModels,
  loadClientProviders,
  parseClientModelCatalog,
  parseClientProviders,
} from './clientAI';


describe('client AI contracts', () => {
  it('严格解析服务端厂商能力且不接受端点字段', () => {
    expect(parseClientProviders({
      providers: [{
        id: 'qwen',
        name: '阿里百炼（Qwen）',
        short_name: 'Qwen',
        description: '阿里云百炼提供的通义千问模型服务。',
        catalog_source: 'curated',
        requires_key_to_list: false,
        available_for_research: true,
      }],
    })).toEqual([{
      id: 'qwen',
      name: '阿里百炼（Qwen）',
      shortName: 'Qwen',
      description: '阿里云百炼提供的通义千问模型服务。',
      catalogSource: 'curated',
      requiresKeyToList: false,
      availableForResearch: true,
    }]);
    expect(parseClientProviders({
      providers: [{
        id: 'qwen',
        name: '千问',
        short_name: 'Qwen',
        description: '阿里云百炼提供的通义千问模型服务。',
        catalog_source: 'curated',
        requires_key_to_list: false,
        available_for_research: true,
        base_url: 'https://attacker.invalid',
      }],
    })).toBeNull();
    expect(parseClientProviders({
      providers: [{
        id: 'qwen',
        name: '阿里百炼（Qwen）',
        short_name: 'Qwen',
        catalog_source: 'curated',
        requires_key_to_list: false,
        available_for_research: true,
      }],
    })).toBeNull();
  });

  it('拒绝目录来源或模型结构漂移', () => {
    expect(parseClientModelCatalog({
      vendor: 'qwen',
      source: 'unknown',
      available_for_research: true,
      models: [],
    })).toBeNull();
    expect(parseClientModelCatalog({
      vendor: 'qwen',
      source: 'curated',
      available_for_research: true,
      models: [{ id: 'qwen3.7-plus', name: 123 }],
    })).toBeNull();
  });

  it('加载动态目录时只把 Key 发给部署实例后端', async () => {
    const sentinel = 'sk-browser-sentinel';
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      expect(init?.credentials).toBe('omit');
      expect(JSON.parse(String(init?.body))).toEqual({
        vendor: 'kimi',
        api_key: sentinel,
      });
      return new Response(JSON.stringify({
        vendor: 'kimi',
        source: 'official_api',
        available_for_research: false,
        models: [{ id: 'kimi-k4', name: 'Kimi K4' }],
      }), { status: 200, headers: { 'Content-Type': 'application/json' } });
    });

    const result = await loadClientModels(
      'https://app.example',
      'kimi',
      sentinel,
      undefined,
      fetchMock,
    );

    expect(fetchMock).toHaveBeenCalledWith(
      'https://app.example/ai/models',
      expect.any(Object),
    );
    expect(JSON.stringify(result)).not.toContain(sentinel);
  });

  it('上游失败时只抛安全中文信息', async () => {
    const fetchMock = vi.fn(async () => new Response(
      JSON.stringify({ detail: 'Authorization: Bearer upstream-secret' }),
      { status: 401, headers: { 'Content-Type': 'application/json' } },
    ));

    await expect(loadClientProviders('', undefined, fetchMock)).rejects.toThrow(
      '模型厂商列表暂时不可用',
    );
    await expect(loadClientModels(
      '',
      'kimi',
      'sk-browser-secret',
      undefined,
      fetchMock,
    )).rejects.toThrow('API Key 无效或无权读取模型目录');

    const sensitiveNetworkFailure = vi.fn(async () => {
      throw new Error('Authorization: Bearer sk-network-secret');
    });
    await expect(loadClientModels(
      '',
      'kimi',
      'sk-browser-secret',
      undefined,
      sensitiveNetworkFailure,
    )).rejects.toThrow('模型目录暂时不可用');

    const invalidSensitiveJson = vi.fn(async () => new Response(
      'Authorization: Bearer sk-json-secret',
      { status: 200, headers: { 'Content-Type': 'application/json' } },
    ));
    await expect(loadClientProviders(
      '',
      undefined,
      invalidSensitiveJson,
    )).rejects.toThrow('模型厂商列表格式不正确');
  });
});
