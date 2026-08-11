import ReactMarkdown from "react-markdown";
import remarkGfm from 'remark-gfm';
import { Check, Copy, Download, Loader2 } from 'lucide-react';
import type { GlassStyle, AnimationStyle } from '../types';

interface ResearchReportProps {
  output: {
    summary: string;
    details: {
      report: string;
    };
  } | null;
  isResetting: boolean;
  isStreaming: boolean;
  glassStyle: GlassStyle;
  fadeInAnimation: AnimationStyle;
  loaderColor: string;
  isGeneratingPdf: boolean;
  isCopied: boolean;
  onCopyToClipboard: () => void;
  onGeneratePdf: () => void;
}

const ResearchReport = ({
  output,
  isResetting,
  isStreaming,
  glassStyle,
  fadeInAnimation,
  loaderColor,
  isGeneratingPdf,
  isCopied,
  onCopyToClipboard,
  onGeneratePdf
}: ResearchReportProps) => {
  if (!output || !output.details) return null;

  return (
    <div 
      className={`${glassStyle.card} ${fadeInAnimation.fadeIn} ${isResetting ? 'opacity-0 transform -translate-y-4' : 'opacity-100 transform translate-y-0'} font-['DM_Sans']`}
    >
      {isStreaming && (
        <div className="flex items-center gap-2 mb-4 px-4 py-2 bg-[#468BFF]/10 rounded-lg border border-[#468BFF]/20">
          <Loader2 className="h-4 w-4 animate-spin" style={{ stroke: loaderColor }} />
          <span className="text-sm text-gray-600">正在生成报告……</span>
        </div>
      )}
      <div className="flex justify-end gap-2 mb-4">
        {output?.details?.report && (
          <>
            <button
              onClick={onCopyToClipboard}
              className="inline-flex items-center justify-center px-4 py-2 rounded-lg bg-[#468BFF] text-white hover:bg-[#8FBCFA] transition-all duration-200"
            >
              {isCopied ? (
                <Check className="h-5 w-5" />
              ) : (
                <Copy className="h-5 w-5" />
              )}
            </button>
            <button
              onClick={onGeneratePdf}
              disabled={isGeneratingPdf}
              className="inline-flex items-center justify-center px-4 py-2 rounded-lg bg-[#FFB800] text-white hover:bg-[#FFA800] transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isGeneratingPdf ? (
                <>
                  <Loader2 className="animate-spin h-5 w-5 mr-2" style={{ stroke: loaderColor }} />
                  正在生成 PDF……
                </>
              ) : (
                <>
                  <Download className="h-5 w-5" />
                  <span className="ml-2">PDF</span>
                </>
              )}
            </button>
          </>
        )}
      </div>
      <div className="prose prose-invert prose-lg max-w-none">
        <div className="mt-4">
          <ReactMarkdown
            skipHtml
            remarkPlugins={[remarkGfm]}
            components={{
              div: ({node: _node, ...props}) => (
                <div className="space-y-4 text-gray-800" {...props} />
              ),
              h1: ({node: _node, children, ...props}) => {
                const text = String(children);
                // 第 5 组提示中文化后，LLM 输出的一级标题已改为
                // "# {company} 调研报告",这里同步改为中文判断;
                // "参考文献" 是 references.py 自己拼装的,保持中文一致
                const isFirstH1 = text.includes("调研报告");
                const isReferences = text.includes("参考文献");
                return (
                  <div>
                    <h1 
                      className={`font-bold text-gray-900 break-words whitespace-pre-wrap ${isFirstH1 ? 'mb-10 mt-4 max-w-none text-3xl sm:text-4xl lg:max-w-[calc(100%-8rem)] lg:text-5xl' : 'mb-6 text-2xl sm:text-3xl'}`}
                      {...props} 
                    >
                      {children}
                    </h1>
                    {isReferences && (
                      <div className="h-[1px] w-full bg-gradient-to-r from-transparent via-gray-300 to-transparent my-8"></div>
                    )}
                  </div>
                );
              },
              h2: ({node: _node, ...props}) => (
                <h2 className="text-3xl font-bold text-gray-900 first:mt-2 mt-8 mb-4" {...props} />
              ),
              h3: ({node: _node, ...props}) => (
                <h3 className="text-xl font-semibold text-gray-900 mt-6 mb-3" {...props} />
              ),
              p: ({node: _node, children, ...props}) => {
                const text = String(children);
                // 把以中/英文冒号结尾的短句当 h3 渲染(LLM 偶尔会忘记 ### 前缀)
                const isSubsectionHeader = (
                  text.includes('\n') === false &&
                  text.length < 50 &&
                  (text.endsWith(':') || text.endsWith('：') || /^[A-Z][A-Za-z\s/]+$/.test(text))
                );

                if (isSubsectionHeader) {
                  return (
                    <h3 className="text-xl font-semibold text-gray-900 mt-6 mb-3">
                      {(text.endsWith(':') || text.endsWith('：')) ? text.slice(0, -1) : text}
                    </h3>
                  );
                }
                
                const isBulletLabel = text.startsWith('•') && text.includes(':');
                if (isBulletLabel) {
                  const [label, content] = text.split(':');
                  return (
                    <div className="text-gray-800 my-2">
                      <span className="font-semibold text-gray-900">
                        {label.replace('•', '').trim()}:
                      </span>
                      {content}
                    </div>
                  );
                }
                
                const urlRegex = /(https?:\/\/[^\s<>"]+)/g;
                if (urlRegex.test(text)) {
                  const parts = text.split(urlRegex);
                  return (
                    <p className="text-gray-800 my-2" {...props}>
                      {parts.map((part, i) => 
                        urlRegex.test(part) ? (
                          <a 
                            key={i}
                            href={part}
                            className="text-[#468BFF] hover:text-[#8FBCFA] underline decoration-[#468BFF] hover:decoration-[#8FBCFA] cursor-pointer transition-colors"
                            target="_blank"
                            rel="noopener noreferrer"
                          >
                            {part}
                          </a>
                        ) : part
                      )}
                    </p>
                  );
                }
                
                return <p className="text-gray-800 my-2" {...props}>{children}</p>;
              },
              ul: ({node: _node, ...props}) => (
                <ul className="text-gray-800 space-y-1 list-disc pl-6" {...props} />
              ),
              li: ({node: _node, ...props}) => (
                <li className="text-gray-800" {...props} />
              ),
              a: ({node: _node, href, ...props}) => (
                <a 
                  href={href}
                  className="text-[#468BFF] hover:text-[#8FBCFA] underline decoration-[#468BFF] hover:decoration-[#8FBCFA] cursor-pointer transition-colors" 
                  target="_blank"
                  rel="noopener noreferrer"
                  {...props} 
                />
              ),
            }}
          >
            {output.details.report || "暂无报告内容"}
          </ReactMarkdown>
        </div>
      </div>
    </div>
  );
};

export default ResearchReport;
