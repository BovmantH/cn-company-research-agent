import { useState, useEffect, useRef } from "react";
import {
  Header,
  ResearchStatus,
  ResearchReport,
  ResearchForm,
  ResearchQueries,
  CurationExtraction,
  ResearchBriefings
} from './components';
import type { ResearchOutput, ResearchStatusType } from './types';
import { glassStyle, fadeInAnimation } from './styles';

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

function App() {

  const [isResearching, setIsResearching] = useState(false);
  const [status, setStatus] = useState<ResearchStatusType | null>(null);
  const [output, setOutput] = useState<ResearchOutput | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isComplete, setIsComplete] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);
  const [originalCompanyName, setOriginalCompanyName] = useState<string>("");
  const [currentPhase, setCurrentPhase] = useState<'search' | 'enrichment' | 'briefing' | 'complete' | null>(null);
  const [isGeneratingPdf, setIsGeneratingPdf] = useState(false);
  const [isResetting, setIsResetting] = useState(false);
  const [isCopied, setIsCopied] = useState(false);
  const statusRef = useRef<HTMLDivElement>(null);
  const [queries, setQueries] = useState<Array<{ text: string; number: number; category: string }>>([]);
  const [streamingQueries, setStreamingQueries] = useState<Record<string, { text: string; number: number; category: string; isComplete: boolean }>>({});
  const [isQueriesExpanded, setIsQueriesExpanded] = useState(true);
  const [enrichmentCounts, setEnrichmentCounts] = useState<{
    company: { total: number; enriched: number };
    industry: { total: number; enriched: number };
    financial: { total: number; enriched: number };
    news: { total: number; enriched: number };
  } | undefined>(undefined);
  const [briefingStatus, setBriefingStatus] = useState({
    company: false,
    industry: false,
    financial: false,
    news: false
  });
  const [isEnrichmentExpanded, setIsEnrichmentExpanded] = useState(true);
  const [isBriefingExpanded, setIsBriefingExpanded] = useState(true);
  const [hasScrolledToStatus, setHasScrolledToStatus] = useState(false);
  const [isReportStreaming, setIsReportStreaming] = useState(false);

  // Add new state for color cycling
  const [loaderColor, setLoaderColor] = useState("#468BFF");
  
  // Scroll helper function
  const scrollToStatus = () => {
    if (!hasScrolledToStatus && statusRef.current) {
      const yOffset = -20;
      const y = statusRef.current.getBoundingClientRect().top + window.pageYOffset + yOffset;
      window.scrollTo({ top: y, behavior: 'smooth' });
      setHasScrolledToStatus(true);
    }
  };

  // Add useEffect for color cycling
  useEffect(() => {
    if (!isResearching) return;
    
    const colors = [
      "#468BFF", // Blue
      "#8FBCFA", // Light Blue
      "#FE363B", // Red
      "#FF9A9D", // Light Red
      "#FDBB11", // Yellow
      "#F6D785", // Light Yellow
    ];
    
    let currentIndex = 0;
    
    const interval = setInterval(() => {
      currentIndex = (currentIndex + 1) % colors.length;
      setLoaderColor(colors[currentIndex]);
    }, 1000);
    
    return () => clearInterval(interval);
  }, [isResearching]);

  const resetResearch = () => {
    setIsResetting(true);
    
    // Use setTimeout to create a smooth transition
    setTimeout(() => {
      setStatus(null);
      setOutput(null);
      setError(null);
      setIsComplete(false);
      setCurrentPhase(null);
      setQueries([]);
      setStreamingQueries({});
      setEnrichmentCounts(undefined);
      setBriefingStatus({
        company: false,
        industry: false,
        financial: false,
        news: false
      });
      setIsQueriesExpanded(true);
      setIsEnrichmentExpanded(true);
      setIsBriefingExpanded(true);
      setHasScrolledToStatus(false);
      setIsReportStreaming(false);
      setIsResetting(false);
    }, 300);
  };

  // Stream research results via SSE
  const streamResults = (jobId: string) => {
    const eventSource = new EventSource(`${API_URL}/research/${jobId}/stream`);
    eventSourceRef.current = eventSource;

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        
        // 把后端节点名映射为用户可读的中文阶段名
        const getStepName = (nodeName: string): string => {
          const stepMap: Record<string, string> = {
            'grounding': '检索',
            'financial_analyst': '检索',
            'news_scanner': '检索',
            'industry_analyst': '检索',
            'company_analyst': '检索',
            'collector': '检索',
            'curator': '抽取增强',
            'enricher': '抽取增强',
            'briefing': '简报生成',
            'editor': '收尾整理'
          };
          return stepMap[nodeName] || nodeName;
        };

        // 分类英文 key 与中文显示名映射(key 不能改,后端事件用同样字符串)
        const CATEGORY_LABELS: Record<string, string> = {
          company: '公司',
          industry: '行业',
          financial: '财务',
          news: '新闻',
        };
        const labelOf = (cat?: string) =>
          (cat && CATEGORY_LABELS[cat]) || cat || '';

        // 处理后端进度事件(节点切换)
        if (data.type === 'progress' && data.step) {
          const stepName = getStepName(data.step);
          setStatus({
            step: stepName,
            message: `正在处理「${data.step}」节点……`
          });
          
          // Update phase based on step
          if (['grounding', 'financial_analyst', 'news_scanner', 'industry_analyst', 'company_analyst', 'collector'].includes(data.step)) {
            setCurrentPhase('search');
          } else if (['curator', 'enricher'].includes(data.step)) {
            setCurrentPhase('enrichment');
          } else if (data.step === 'briefing') {
            setCurrentPhase('briefing');
          }
          
          scrollToStatus();
        }
        
        // 直接事件 → 阶段映射
        if (data.type === 'query_generating') {
          // 显示正在生成的 query,并维护流式 query 列表
          setCurrentPhase('search');
          setStatus({
            step: '检索',
            message: `第 ${data.query_number} 条 Query：${data.query}`
          });
          // 把当前部分 query 写入流式列表
          const key = `${data.category}_${data.query_number}`;
          setStreamingQueries(prev => ({
            ...prev,
            [key]: {
              text: data.query,
              number: data.query_number,
              category: data.category,
              isComplete: false
            }
          }));
        } else if (data.type === 'query_generated') {
          // 显示已完成的 query,并把它移入完成列表
          setCurrentPhase('search');
          setStatus({
            step: '检索',
            message: `已生成 Query：${data.query}`
          });
          // 加入已完成 query 列表
          setQueries(prev => [...prev, {
            text: data.query,
            number: data.query_number,
            category: data.category
          }]);
          // 从流式列表中移除
          const key = `${data.category}_${data.query_number}`;
          setStreamingQueries(prev => {
            const updated = { ...prev };
            delete updated[key];
            return updated;
          });
          scrollToStatus();
        } else if (data.type === 'research_init') {
          // 调研初始化
          setCurrentPhase('search');
          setStatus({
            step: '初始化',
            message: data.message || `开始调研 ${data.company}`
          });
        } else if (data.type === 'crawl_start') {
          // 网站抓取开始
          setCurrentPhase('search');
          setStatus({
            step: '网站抓取',
            message: data.message || '正在抓取公司官网……'
          });
        } else if (data.type === 'curation') {
          // 数据筛选 → 切换到抽取增强阶段
          setCurrentPhase('enrichment');
          setStatus({
            step: '数据筛选',
            message: data.message || `正在筛选「${labelOf(data.category)}」类文档`
          });
          // 当某分类的筛选开始时,初始化抽取计数
          if (data.category) {
            setEnrichmentCounts(prev => ({
              ...prev,
              [data.category]: {
                total: data.total || 0,
                enriched: 0
              }
            } as typeof enrichmentCounts));
          }
          // 进入抽取阶段后折叠 query 区域
          setTimeout(() => {
            setIsQueriesExpanded(false);
          }, 1000);
          scrollToStatus();
        } else if (data.type === 'enrichment') {
          // 抽取增强进度
          setCurrentPhase('enrichment');
          setStatus({
            step: '抽取增强',
            message: data.message || '正在为文档抽取补充内容'
          });
          // 如果带 enriched 字段则更新
          if (data.category && data.enriched !== undefined) {
            const category = data.category as 'company' | 'industry' | 'financial' | 'news';
            setEnrichmentCounts(prev => {
              if (!prev) return prev;
              return {
                ...prev,
                [category]: {
                  total: prev[category]?.total || data.total || 0,
                  enriched: data.enriched
                }
              } as typeof enrichmentCounts;
            });
          }
        } else if (data.type === 'briefing_start') {
          // 简报生成开始
          setCurrentPhase('briefing');
          setStatus({
            step: '简报生成中',
            message: `基于 ${data.total_docs} 篇文档生成「${labelOf(data.category)}」简报`
          });
          // 进入简报阶段后折叠抽取区域
          setTimeout(() => {
            setIsEnrichmentExpanded(false);
          }, 1000);
          scrollToStatus();
        } else if (data.type === 'briefing_complete') {
          // 简报完成 → 标记该分类为完成
          setCurrentPhase('briefing');
          setStatus({
            step: '简报完成',
            message: `「${labelOf(data.category)}」简报已生成(${data.content_length} 字符)`
          });
          // 标记该分类的简报状态为完成
          if (data.category) {
            setBriefingStatus(prev => {
              const newBriefingStatus = {
                ...prev,
                [data.category]: true
              };

              // 检查是否四份简报全部完成
              const allBriefingsComplete = Object.values(newBriefingStatus).every(status => status);

              // 如果全部完成则折叠简报区域
              if (allBriefingsComplete) {
                setTimeout(() => {
                  setIsBriefingExpanded(false);
                }, 2000);
              }

              return newBriefingStatus;
            });
          }
        } else if (data.type === 'report_compilation') {
          // 报告编排
          setCurrentPhase('briefing');
          setStatus({
            step: '报告生成中',
            message: data.message || '正在编排最终报告'
          });
        } else if (data.type === 'report_chunk' && data.chunk) {
          // 流式追加报告内容
          setIsReportStreaming(true);
          setOutput((prev) => {
            const currentReport = prev?.details?.report || '';
            return {
              summary: "",
              details: { report: currentReport + data.chunk },
            };
          });
          setStatus({
            step: '报告生成中',
            message: '正在生成最终报告……'
          });
        } else if (data.type === 'complete' && data.report) {
          setIsReportStreaming(false);
          setOutput({
            summary: "",
            details: { report: data.report },
          });
          setStatus({ step: "完成", message: "调研已完成" });
          setIsComplete(true);
          setIsResearching(false);
          eventSource.close();
        } else if (data.type === 'error') {
          setError(data.error);
          setIsResearching(false);
          eventSource.close();
        }
      } catch (err) {
        console.error('解析 SSE 事件出错:', err);
      }
    };

    eventSource.onerror = () => {
      setError('连接已断开或服务端出错');
      setIsResearching(false);
      eventSource.close();
    };
  };

  // Cleanup SSE on unmount
  useEffect(() => {
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
    };
  }, []);

  // Create a custom handler for the form that receives form data
  const handleFormSubmit = async (formData: {
    companyName: string;
    companyUrl: string;
    companyHq: string;
    companyIndustry: string;
  }) => {

    // Clear any existing errors first
    setError(null);

    // If research is complete, reset the UI first
    if (isComplete) {
      resetResearch();
      await new Promise(resolve => setTimeout(resolve, 300)); // Wait for reset animation
    }

    // Clear any existing SSE connection
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }

    setIsResearching(true);
    setOriginalCompanyName(formData.companyName);
    setStatus({
      step: "处理中",
      message: "正在启动调研……"
    });

    try {
      const url = `${API_URL}/research`;

      // Format the company URL if provided
      const formattedCompanyUrl = formData.companyUrl
        ? formData.companyUrl.startsWith('http://') || formData.companyUrl.startsWith('https://')
          ? formData.companyUrl
          : `https://${formData.companyUrl}`
        : undefined;

      const requestData = {
        company: formData.companyName,
        company_url: formattedCompanyUrl,
        industry: formData.companyIndustry || undefined,
        hq_location: formData.companyHq || undefined,
      };

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

      const data = await response.json();

      if (data.job_id) {
        streamResults(data.job_id);
      } else {
        throw new Error("未收到任务 ID");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "启动调研失败");
      setIsResearching(false);
    }
  };

  // Add new function to handle PDF generation
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
      setError(error instanceof Error ? error.message : '生成 PDF 失败');
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
      setError('复制到剪贴板失败');
    }
  };


  return (
    <div className="min-h-screen bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-white via-gray-50 to-white p-8 relative">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_1px_1px,rgba(70,139,255,0.35)_1px,transparent_0)] bg-[length:24px_24px] bg-center"></div>
      <div className="max-w-5xl mx-auto space-y-8 relative">
        {/* Header Component */}
        <Header glassStyle={glassStyle.card} />

        {/* Form Section */}
        <ResearchForm 
          onSubmit={handleFormSubmit}
          isResearching={isResearching}
          glassStyle={glassStyle}
          loaderColor={loaderColor}
        />

        {/* Error Message */}
        {error && (
          <div 
            className={`${glassStyle.card} border-[#FE363B]/30 bg-[#FE363B]/10 ${fadeInAnimation.fadeIn} ${isResetting ? 'opacity-0 transform -translate-y-4' : 'opacity-100 transform translate-y-0'} font-['DM_Sans']`}
          >
            <p className="text-[#FE363B]">{error}</p>
          </div>
        )}

        {/* Status Box */}
        <ResearchStatus
          status={status}
          error={error}
          isComplete={isComplete}
          currentPhase={currentPhase}
          isResetting={isResetting}
          glassStyle={glassStyle}
          loaderColor={loaderColor}
          statusRef={statusRef}
        />

        {/* Research Report - always at the top when available */}
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

        {/* Research Briefings - show once briefing starts and keep visible */}
        {(currentPhase === 'briefing' || currentPhase === 'complete') && (
          <ResearchBriefings
            briefingStatus={briefingStatus}
            isExpanded={isBriefingExpanded}
            onToggleExpand={() => setIsBriefingExpanded(!isBriefingExpanded)}
            isResetting={isResetting}
          />
        )}

        {/* Curation and Extraction - show once enrichment starts and keep visible */}
        {(currentPhase === 'enrichment' || currentPhase === 'briefing' || currentPhase === 'complete') && enrichmentCounts && (
          <CurationExtraction
            enrichmentCounts={enrichmentCounts}
            isExpanded={isEnrichmentExpanded}
            onToggleExpand={() => setIsEnrichmentExpanded(!isEnrichmentExpanded)}
            isResetting={isResetting}
            loaderColor={loaderColor}
          />
        )}

        {/* Research Queries - always at the bottom when visible */}
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