import { describe, expect, it } from 'vitest';

import { researchSubmissionErrorMessage } from './researchErrors';

describe('调研提交错误边界', () => {
  it('仅显示按状态登记的本站文案', async () => {
    const detail = 'API Key 无效或无权读取该厂商的官方模型目录';
    const response = new Response(JSON.stringify({ detail, debug: 'upstream-secret' }), {
      status: 401, headers: { 'Content-Type': 'application/json; charset=utf-8' },
    });
    expect(await researchSubmissionErrorMessage(response)).toBe(detail);
  });

  it.each([
    ['未知中文正文', JSON.stringify({ detail: '账户信息：upstream-secret' }), 'application/json'],
    ['网关 HTML', '<html>Authorization: upstream-secret</html>', 'text/html'],
    ['非 JSON', 'Authorization: upstream-secret', 'application/json'],
    ['错误字段类型', JSON.stringify({ detail: ['upstream-secret'] }), 'application/json'],
    ['过长正文', JSON.stringify({ detail: 'API Key 无效或无权读取该厂商的官方模型目录', debug: 'x'.repeat(2_048) }), 'application/json'],
  ])('%s使用安全兜底', async (_name, body, contentType) => {
    const message = await researchSubmissionErrorMessage(new Response(body, {
      status: 401, headers: { 'Content-Type': contentType },
    }));
    expect(message).toBe('API Key 无效或权限不足，请检查后重试');
    expect(message).not.toContain('upstream-secret');
  });
});
