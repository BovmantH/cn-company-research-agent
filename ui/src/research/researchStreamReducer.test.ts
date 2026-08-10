import { describe, expect, it } from "vitest";

import {
  createInitialResearchStreamState,
  hasMatchingSseEventId,
  parseResearchSsePayload,
  researchStreamReducer,
  type ResearchSseEvent,
} from "./researchStreamReducer";

const event = (
  value: Omit<ResearchSseEvent, "version" | "event_id">,
  eventId: number,
): ResearchSseEvent => ({
  ...value,
  version: 1,
  event_id: eventId,
} as ResearchSseEvent);

describe("researchStreamReducer", () => {
  it("拒绝缺少版本游标或字段类型错误的 SSE 数据", () => {
    expect(parseResearchSsePayload({ type: "complete", report: "报告" })).toBeNull();
    expect(parseResearchSsePayload({
      type: "complete",
      report: { raw: "报告" },
      version: 1,
      event_id: 1,
    })).toBeNull();
    expect(parseResearchSsePayload({
      type: "query_generated",
      query: "公司股东",
      query_number: "1",
      category: "company",
      version: 1,
      event_id: 2,
    })).toBeNull();
  });

  it("要求 SSE 帧游标与正文游标完全一致", () => {
    const payload = event({ type: "progress", step: "collector" }, 2);

    expect(hasMatchingSseEventId("2", payload)).toBe(true);
    expect(hasMatchingSseEventId("", payload)).toBe(false);
    expect(hasMatchingSseEventId("999", payload)).toBe(false);
  });

  it("对重放的 query 和 report chunk 只应用一次", () => {
    let state = createInitialResearchStreamState();
    const query = event({
      type: "query_generated",
      query: "示例公司 股东",
      query_number: 1,
      category: "company",
    }, 1);
    const chunk = event({ type: "report_chunk", chunk: "第一段" }, 2);

    state = researchStreamReducer(state, { type: "event", event: query });
    state = researchStreamReducer(state, { type: "event", event: query });
    state = researchStreamReducer(state, { type: "event", event: chunk });
    state = researchStreamReducer(state, { type: "event", event: chunk });

    expect(state.queries).toHaveLength(1);
    expect(state.output?.details.report).toBe("第一段");
    expect(state.lastEventId).toBe(2);
  });

  it("专业数据降级后基础报告仍可成功", () => {
    let state = createInitialResearchStreamState();
    state = researchStreamReducer(state, {
      type: "event",
      event: event({
        type: "professional_data_degraded",
        reason: "provider_unavailable",
      }, 1),
    });
    state = researchStreamReducer(state, {
      type: "event",
      event: event({ type: "complete", report: "基础报告" }, 2),
    });

    expect(state.lifecycle).toBe("completed");
    expect(state.professional.status).toBe("degraded");
    expect(state.output?.details.report).toBe("基础报告");
  });

  it("专业采集状态单调推进且完成事件不覆盖既有降级", () => {
    let succeeded = researchStreamReducer(createInitialResearchStreamState(), {
      type: "event",
      event: event({ type: "professional_data_started" }, 1),
    });
    succeeded = researchStreamReducer(succeeded, {
      type: "event",
      event: event({ type: "professional_data_progress" }, 2),
    });
    expect(succeeded.professional.status).toBe("running");
    succeeded = researchStreamReducer(succeeded, {
      type: "event",
      event: event({ type: "professional_data_completed" }, 3),
    });
    expect(succeeded.professional.status).toBe("completed");

    let degraded = researchStreamReducer(createInitialResearchStreamState(), {
      type: "event",
      event: event({
        type: "professional_data_degraded",
        reason: "provider_unavailable",
      }, 1),
    });
    degraded = researchStreamReducer(degraded, {
      type: "event",
      event: event({ type: "professional_data_completed" }, 2),
    });
    expect(degraded.professional.status).toBe("degraded");
  });

  it("成功终态清除不影响任务的临时界面错误", () => {
    let state = researchStreamReducer(createInitialResearchStreamState(), {
      type: "ui_error",
      message: "复制到剪贴板失败",
    });
    state = researchStreamReducer(state, {
      type: "event",
      event: event({ type: "complete", report: "基础报告" }, 1),
    });

    expect(state.lifecycle).toBe("completed");
    expect(state.error).toBeNull();
  });

  it("预算阻断和报告降级都不是任务终态", () => {
    let state = createInitialResearchStreamState();
    state = researchStreamReducer(state, {
      type: "event",
      event: event({
        type: "professional_data_budget_blocked",
        reason: "budget_blocked",
      }, 1),
    });
    state = researchStreamReducer(state, {
      type: "event",
      event: event({ type: "report_degraded", reason: "formatting_failed" }, 2),
    });
    state = researchStreamReducer(state, {
      type: "event",
      event: event({ type: "progress", step: "editor" }, 3),
    });

    expect(state.lifecycle).not.toBe("failed");
    expect(state.professional.status).toBe("budget_blocked");
    expect(state.currentPhase).toBe("briefing");
  });

  it("首个任务终态获胜", () => {
    let state = createInitialResearchStreamState();
    state = researchStreamReducer(state, {
      type: "event",
      event: event({
        type: "error",
        error: "调研任务执行失败",
        reason: "research_failed",
      }, 1),
    });
    state = researchStreamReducer(state, {
      type: "event",
      event: event({ type: "complete", report: "不应覆盖" }, 2),
    });

    expect(state.lifecycle).toBe("failed");
    expect(state.output).toBeNull();
    expect(state.lastEventId).toBe(2);
  });

  it("连接中断只进入自动重连状态", () => {
    let running = researchStreamReducer(createInitialResearchStreamState(), {
      type: "start",
    });
    running = researchStreamReducer(running, {
      type: "event",
      event: event({ type: "progress", step: "collector" }, 1),
    });
    const reconnecting = researchStreamReducer(running, {
      type: "connection_lost",
    });
    const connected = researchStreamReducer(reconnecting, {
      type: "connection_open",
    });

    expect(reconnecting.connection).toBe("reconnecting");
    expect(reconnecting.lifecycle).toBe("running");
    expect(reconnecting.error).toBeNull();
    expect(connected.status).toEqual(running.status);
  });

  it("历史窗口失效与业务失败分开表达", () => {
    const running = researchStreamReducer(createInitialResearchStreamState(), {
      type: "start",
    });
    const state = researchStreamReducer(running, {
      type: "stream_reset_required",
    });

    expect(state.connection).toBe("reset_required");
    expect(state.lifecycle).toBe("reset_required");
    expect(state.error).toContain("进度历史");
  });

  it("reset 恢复全部初始状态", () => {
    const running = researchStreamReducer(createInitialResearchStreamState(), {
      type: "start",
    });
    const reset = researchStreamReducer(running, { type: "reset" });

    expect(reset).toEqual(createInitialResearchStreamState());
  });
});
