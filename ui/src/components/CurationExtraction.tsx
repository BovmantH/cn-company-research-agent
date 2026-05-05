import { ChevronDown, ChevronUp, Loader2 } from 'lucide-react';
import type { EnrichmentCounts } from '../types';
import { glassStyle } from '../styles';

// 分类英文 key 与中文显示名映射(key 不能改,Backend 事件用同样字符串)
const CATEGORY_LABELS: Record<string, string> = {
  company: '公司',
  industry: '行业',
  financial: '财务',
  news: '新闻',
};

interface CurationExtractionProps {
  enrichmentCounts: EnrichmentCounts | undefined;
  isExpanded: boolean;
  onToggleExpand: () => void;
  isResetting: boolean;
  loaderColor: string;
}

const CurationExtraction = ({
  enrichmentCounts,
  isExpanded,
  onToggleExpand,
  isResetting,
  loaderColor
}: CurationExtractionProps) => {
  return (
    <div 
      className={`${glassStyle.card} transition-all duration-300 ease-in-out ${
        isResetting ? 'opacity-0 transform -translate-y-4' : 'opacity-100 transform translate-y-0'
      }`}
    >
      <div 
        className="flex items-center justify-between cursor-pointer"
        onClick={onToggleExpand}
      >
        <h2 className="text-xl font-semibold text-gray-900">
          数据筛选与抽取
        </h2>
        <button className="text-gray-600 hover:text-gray-900 transition-colors">
          {isExpanded ? (
            <ChevronUp className="h-6 w-6" />
          ) : (
            <ChevronDown className="h-6 w-6" />
          )}
        </button>
      </div>

      <div className={`overflow-hidden transition-all duration-500 ease-in-out ${
        isExpanded ? 'mt-4 max-h-[1000px] opacity-100' : 'max-h-0 opacity-0'
      }`}>
        <div className="grid grid-cols-4 gap-4">
          {['company', 'industry', 'financial', 'news'].map((category) => {
            const counts = enrichmentCounts?.[category as keyof EnrichmentCounts];
            return (
              <div key={category} className="backdrop-blur-2xl bg-white/95 border border-gray-200/50 rounded-xl p-3 shadow-none">
                <h3 className="text-sm font-medium text-gray-700 mb-2">{CATEGORY_LABELS[category]}</h3>
                <div className="text-gray-900">
                  <div className="text-2xl font-bold mb-1">
                    {counts ? (
                      <span className="text-[#468BFF]">
                        {counts.enriched}
                      </span>
                    ) : (
                      <Loader2 className="animate-spin h-6 w-6 mx-auto loader-icon" style={{ stroke: loaderColor }} />
                    )}
                  </div>
                  <div className="text-sm text-gray-600">
                    {counts ? (
                      `从 ${counts.total} 条中筛出`
                    ) : (
                      "等待中……"
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {!isExpanded && enrichmentCounts && (
        <div className="mt-2 text-sm text-gray-600">
          已抽取 {Object.values(enrichmentCounts).reduce((acc, curr) => acc + curr.enriched, 0)} / {Object.values(enrichmentCounts).reduce((acc, curr) => acc + curr.total, 0)} 篇文档
        </div>
      )}
    </div>
  );
};

export default CurationExtraction; 