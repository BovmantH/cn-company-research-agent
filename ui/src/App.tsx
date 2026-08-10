import { useEffect, useReducer, useRef, useState } from "react";
import {
  Header,
  ResearchStatus,
  ResearchReport,
  ResearchForm,
  ResearchQueries,
  CurationExtraction,
  ResearchBriefings,
  CompanyResolutionPanel,
  ProfessionalDataStatus,
} from './components';
import { glassStyle, fadeInAnimation } from './styles';
import {
  createInitialResearchStreamState,
  hasMatchingSseEventId,
  parseResearchSsePayload,
  researchStreamReducer,
} from './research/researchStreamReducer';
import type { ResearchFormValues } from './research/model';
import {
  buildResearchRequest,
  parseResearchAcceptedResponse,
} from './research/researchRequest';
import {
  useProfessionalResearchFlow,
  type PreparedResearch,
} from './research/useProfessionalResearchFlow';

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

function App() {
  const professionalFlow = useProfessionalResearchFlow(API_URL);
  const [researchState, dispatchResearch] = useReducer(
    researchStreamReducer,
    undefined,
    createInitialResearchStreamState,
  );
  const {
    status,
    output,
    error,
    currentPhase,
    queries,
    streamingQueries,
    enrichmentCounts,
    briefingStatus,
    isReportStreaming,
    professional,
  } = researchState;
  const isResearching = researchState.lifecycle === 'running';
  const isComplete = researchState.lifecycle === 'completed';
  const isResolvingCompany = professionalFlow.flowState.status === 'resolving';
  const needsCompanyDecision = professionalFlow.flowState.status === 'candidates'
    || professionalFlow.flowState.status === 'fallback';
  const isFormBusy = isResearching || isResolvingCompany || needsCompanyDecision;
  const formBusyLabel = isResearching
    ? '调研中……'
    : isResolvingCompany
      ? '正在核对主体……'
      : '等待主体确认……';
  const visibleStatus = researchState.connection === 'reconnecting'
    ? { step: '连接恢复中', message: '进度连接中断，正在自动重连……' }
    : status;
  const eventSourceRef = useRef<EventSource | null>(null);
  const lastHandledEventIdRef = useRef(0);
  const [originalCompanyName, setOriginalCompanyName] = useState<string>("");
  const [isGeneratingPdf, setIsGeneratingPdf] = useState(false);
  const [isResetting, setIsResetting] = useState(false);
  const [isCopied, setIsCopied] = useState(false);
  const [professionalDataRequested, setProfessionalDataRequested] = useState(false);
  const statusRef = useRef<HTMLDivElement>(null);
  const [isQueriesExpanded, setIsQueriesExpanded] = useState(true);
  const [isEnrichmentExpanded, setIsEnrichmentExpanded] = useState(true);
  const [isBriefingExpanded, setIsBriefingExpanded] = useState(true);
  const [hasScrolledToStatus, setHasScrolledToStatus] = useState(false);

  // 加载动画的颜色轮换状态
  const [loaderColor, setLoaderColor] = useState("#468BFF");
  
  // 滚动到状态区域的辅助函数
  const scrollToStatus = () => {
    if (!hasScrolledToStatus && statusRef.current) {
      const yOffset = -20;
      const y = statusRef.current.getBoundingClientRect().top + window.pageYOffset + yOffset;
      window.scrollTo({ top: y, behavior: 'smooth' });
      setHasScrolledToStatus(true);
    }
  };

  // 调研期间轮换加载动画颜色
  useEffect(() => {
    if (!isResearching) return;
    
    const colors = [
      "#468BFF", // 蓝色
      "#8FBCFA", // 浅蓝色
      "#FE363B", // 红色
      "#FF9A9D", // 浅红色
      "#FDBB11", // 黄色
      "#F6D785", // 浅黄色
    ];
    
    let currentIndex = 0;
    
    const interval = setInterval(() => {
      currentIndex = (currentIndex + 1) % colors.length;
      setLoaderColor(colors[currentIndex]);
    }, 1000);
    
    return () => clearInterval(interval);
  }, [isResearching]);

  useEffect(() => {
    if (!Object.values(briefingStatus).every(Boolean)) return;
    const timeoutId = window.setTimeout(() => {
      setIsBriefingExpanded(false);
    }, 2000);
    return () => window.clearTimeout(timeoutId);
  }, [briefingStatus]);

  const resetResearch = () => {
    setIsResetting(true);

    setTimeout(() => {
      dispatchResearch({ type: 'reset' });
      setIsQueriesExpanded(true);
      setIsEnrichmentExpanded(true);
      setIsBriefingExpanded(true);
      setHasScrolledToStatus(false);
      setIsResetting(false);
    }, 300);
  };

  /** 建立可自动重连的 SSE 连接；业务状态只由 reducer 投影。 */
  const streamResults = (jobId: string) => {
    const eventSource = new EventSource(`${API_URL}/research/${jobId}/stream`);
    eventSourceRef.current = eventSource;

    eventSource.onopen = () => {
      dispatchResearch({ type: 'connection_open' });
    };

    eventSource.onmessage = (event) => {
      try {
        const data = parseResearchSsePayload(JSON.parse(event.data) as unknown);
        if (!data) return;
        if (data.type === 'stream_reset_required') {
          dispatchResearch({ type: 'stream_reset_required' });
          eventSource.close();
          return;
        }
        if (data.type === 'stream_error') {
          dispatchResearch({ type: 'connection_lost' });
          return;
        }
        if (!hasMatchingSseEventId(event.lastEventId, data)) {
          dispatchResearch({
            type: 'stream_reset_required',
            message: '进度数据校验失败，请重新发起调研',
          });
          eventSource.close();
          return;
        }
        if (data.event_id <= lastHandledEventIdRef.current) return;
        lastHandledEventIdRef.current = data.event_id;

        dispatchResearch({ type: 'event', event: data });

        if (['progress', 'query_generated', 'curation', 'briefing_start'].includes(data.type)) {
          scrollToStatus();
        }
        if (data.type === 'curation') {
          setTimeout(() => {
            setIsQueriesExpanded(false);
          }, 1000);
        }
        if (data.type === 'briefing_start') {
          setTimeout(() => {
            setIsEnrichmentExpanded(false);
          }, 1000);
        }
        if (data.type === 'complete' || data.type === 'error') {
          eventSource.close();
        }
      } catch (err) {
        console.error('解析 SSE 事件出错:', err);
      }
    };

    eventSource.onerror = () => {
      if (eventSource.readyState === EventSource.CLOSED) {
        dispatchResearch({
          type: 'stream_reset_required',
          message: '进度连接无法恢复，请稍后重试或重新发起调研',
        });
      } else {
        dispatchResearch({ type: 'connection_lost' });
      }
    };
  };

  // 组件卸载时关闭 SSE 连接
  useEffect(() => {
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
    };
  }, []);

  /** 提交已确认的基础/专业调研；关闭专业数据时保持旧请求体完全不变。 */
  const startResearch = async ({
    values,
    resolutionToken,
  }: PreparedResearch): Promise<void> => {
    // 关闭已有的 SSE 连接
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }

    lastHandledEventIdRef.current = 0;
    dispatchResearch({ type: 'start' });
    setOriginalCompanyName(values.companyName);

    try {
      const url = `${API_URL}/research`;

      const requestData = buildResearchRequest(values, resolutionToken);

      const response = await fetch(url, {
        method: "POST",
        mode: "cors",
        credentials: "omit",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
        },
        body: JSON.stringify(requestData),
      });

      if (!response.ok) {
        throw new Error(`HTTP 请求失败,状态码:${response.status}`);
      }

      const accepted = parseResearchAcceptedResponse(await response.json() as unknown);

      if (accepted) {
        professionalFlow.markResearchAccepted(accepted.professionalData);
        streamResults(accepted.jobId);
      } else {
        throw new Error("未收到任务 ID");
      }
    } catch (err) {
      dispatchResearch({
        type: 'submit_failed',
        message: err instanceof Error ? err.message : "启动调研失败",
      });
    }
  };

  const handleFormSubmit = async (
    formData: ResearchFormValues,
  ): Promise<void> => {
    if (isComplete) {
      resetResearch();
      await new Promise((resolve) => setTimeout(resolve, 300));
    }
    const outcome = await professionalFlow.prepare(formData);
    if (outcome.kind === 'ready') await startResearch(outcome.prepared);
  };

  const handleCandidateSelect = (viewId: string) => {
    const prepared = professionalFlow.selectCandidate(viewId);
    if (prepared) void startResearch(prepared);
  };

  const handleContinueBasic = () => {
    const prepared = professionalFlow.continueBasic();
    if (prepared) {
      setProfessionalDataRequested(false);
      void startResearch(prepared);
    }
  };

  // 生成并下载 PDF 报告
  const handleGeneratePdf = async () => {
    if (!output || isGeneratingPdf) return;
    
    setIsGeneratingPdf(true);
    try {
      const response = await fetch(`${API_URL}/generate-pdf`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          report_content: output.details.report,
          company_name: originalCompanyName || output.details.report
        }),
      });
      
      if (!response.ok) {
        throw new Error('生成 PDF 失败');
      }

      // 取出响应 blob
      const blob = await response.blob();

      // 为 blob 创建临时 URL
      const url = window.URL.createObjectURL(blob);

      // 创建临时 <a> 节点触发下载
      const link = document.createElement('a');
      link.href = url;
      link.download = `${originalCompanyName || 'research_report'}.pdf`;

      // 挂载、点击、移除
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);

      // 释放 URL
      window.URL.revokeObjectURL(url);

    } catch (error) {
      console.error('生成 PDF 出错:', error);
      dispatchResearch({
        type: 'ui_error',
        message: error instanceof Error ? error.message : '生成 PDF 失败',
      });
    } finally {
      setIsGeneratingPdf(false);
    }
  };

  // 复制报告到剪贴板
  const handleCopyToClipboard = async () => {
    if (!output?.details?.report) return;

    try {
      await navigator.clipboard.writeText(output.details.report);
      setIsCopied(true);
      setTimeout(() => setIsCopied(false), 2000); // 2 秒后重置
    } catch (err) {
      console.error('复制失败:', err);
      dispatchResearch({ type: 'ui_error', message: '复制到剪贴板失败' });
    }
  };


  return (
    <div className="min-h-screen bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-white via-gray-50 to-white p-8 relative">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_1px_1px,rgba(70,139,255,0.35)_1px,transparent_0)] bg-[length:24px_24px] bg-center"></div>
      <div className="max-w-5xl mx-auto space-y-8 relative">
        {/* 页头 */}
        <Header glassStyle={glassStyle.card} />

        {/* 调研表单 */}
        <ResearchForm 
          onSubmit={handleFormSubmit}
          isBusy={isFormBusy}
          busyLabel={formBusyLabel}
          capabilityState={professionalFlow.capabilityState}
          professionalDataRequested={professionalDataRequested}
          onProfessionalDataChange={setProfessionalDataRequested}
          glassStyle={glassStyle}
          loaderColor={loaderColor}
        />

        {needsCompanyDecision && (
          <CompanyResolutionPanel
            flow={professionalFlow.flowState}
            onSelect={handleCandidateSelect}
            onContinueBasic={handleContinueBasic}
            onCancel={professionalFlow.cancel}
          />
        )}

        {/* 错误提示 */}
        {error && (
          <div 
            className={`${glassStyle.card} border-[#FE363B]/30 bg-[#FE363B]/10 ${fadeInAnimation.fadeIn} ${isResetting ? 'opacity-0 transform -translate-y-4' : 'opacity-100 transform translate-y-0'} font-['DM_Sans']`}
          >
            <p className="text-[#FE363B]">{error}</p>
          </div>
        )}

        {/* 状态区域 */}
        <ResearchStatus
          status={visibleStatus}
          error={error}
          isComplete={isComplete}
          currentPhase={currentPhase}
          isResetting={isResetting}
          glassStyle={glassStyle}
          loaderColor={loaderColor}
          statusRef={statusRef}
        />

        <ProfessionalDataStatus state={professional} />

        {/* 调研报告：生成后始终置于内容区顶部 */}
        {output && output.details && (
          <ResearchReport
            output={{
              summary: output.summary,
              details: {
                report: output.details.report || ''
              }
            }}
            isResetting={isResetting}
            isStreaming={isReportStreaming}
            glassStyle={glassStyle}
            fadeInAnimation={fadeInAnimation}
            loaderColor={loaderColor}
            isGeneratingPdf={isGeneratingPdf}
            isCopied={isCopied}
            onCopyToClipboard={handleCopyToClipboard}
            onGeneratePdf={handleGeneratePdf}
          />
        )}

        {/* 调研简报：开始生成后持续显示 */}
        {(currentPhase === 'briefing' || currentPhase === 'complete') && (
          <ResearchBriefings
            briefingStatus={briefingStatus}
            isExpanded={isBriefingExpanded}
            onToggleExpand={() => setIsBriefingExpanded(!isBriefingExpanded)}
            isResetting={isResetting}
          />
        )}

        {/* 筛选与抽取：增强阶段开始后持续显示 */}
        {(currentPhase === 'enrichment' || currentPhase === 'briefing' || currentPhase === 'complete') && enrichmentCounts && (
          <CurationExtraction
            enrichmentCounts={enrichmentCounts}
            isExpanded={isEnrichmentExpanded}
            onToggleExpand={() => setIsEnrichmentExpanded(!isEnrichmentExpanded)}
            isResetting={isResetting}
            loaderColor={loaderColor}
          />
        )}

        {/* 检索词：显示时始终位于内容区底部 */}
        {(queries.length > 0 || Object.keys(streamingQueries).length > 0) && (
          <ResearchQueries
            queries={queries}
            streamingQueries={streamingQueries}
            isExpanded={isQueriesExpanded}
            onToggleExpand={() => setIsQueriesExpanded(!isQueriesExpanded)}
            isResetting={isResetting}
            glassStyle={glassStyle.card}
          />
        )}
      </div>
    </div>
  );
}

export default App;
