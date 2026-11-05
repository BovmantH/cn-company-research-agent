const MAX_ERROR_BODY_BYTES = 2_048;
const SAFE_DETAILS: Record<number, ReadonlySet<string>> = {
  401: new Set(['API Key 无效或无权读取该厂商的官方模型目录']),
  422: new Set([
    '所选模型在厂商当前官方模型目录中不存在',
    '所选模型在厂商当前推荐模型清单中不存在',
    '当前尚未开放该厂商的用户自带 Key 联网调研',
    '当前按量 API 端点不支持 Token Plan Key',
    '读取该厂商的官方模型目录需要 API Key',
    '业务空间 ID 仅适用于百炼',
  ]),
  429: new Set(['当前调研任务较多，请稍后重试']),
  500: new Set(['启动调研任务失败']),
  503: new Set([
    '该厂商的模型目录暂时不可用，请稍后重试',
    '当前部署未配置服务端模型，请填写本次任务的 API Key',
  ]),
};

/** 仅承载本站已确认安全的用户提示，网络或代理异常不得直接显示。 */
export class ResearchSubmissionError extends Error {}

const fallbackMessage = (status: number): string => {
  if (status === 401 || status === 403) return 'API Key 无效或权限不足，请检查后重试';
  if (status === 402) return '所选账户额度不足，请检查厂商账户余额';
  if (status === 400 || status === 422) return '提交参数有误，请检查公司信息及模型配置';
  if (status === 429) return '当前请求较多，请稍后重试';
  if (status >= 500) return '调研服务暂时不可用，请稍后重试';
  return '启动调研失败，请稍后重试';
};

/** 只解析有界 JSON 及已知文案，不反射网关正文或附加的敏感字段。 */
export const researchSubmissionErrorMessage = async (response: Response): Promise<string> => {
  const fallback = fallbackMessage(response.status);
  if (response.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase() !== 'application/json') {
    return fallback;
  }
  const reader = response.body?.getReader();
  if (!reader) return fallback;
  try {
    const decoder = new TextDecoder();
    let size = 0;
    let body = '';
    for (let chunk = await reader.read(); !chunk.done; chunk = await reader.read()) {
      size += chunk.value.byteLength;
      if (size > MAX_ERROR_BODY_BYTES) return fallback;
      body += decoder.decode(chunk.value, { stream: true });
    }
    body += decoder.decode();
    const value: unknown = JSON.parse(body);
    if (typeof value !== 'object' || value === null || Array.isArray(value)) return fallback;
    const detail: unknown = Reflect.get(value, 'detail');
    return typeof detail === 'string' && SAFE_DETAILS[response.status]?.has(detail)
      ? detail
      : fallback;
  } catch {
    return fallback;
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
};
