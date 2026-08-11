import { create } from 'react-test-renderer';
import { describe, expect, it } from 'vitest';

import Header from './Header';

describe('Header', () => {
  it('展示当前项目品牌和仓库入口，不再引用旧 Tavily 页面', () => {
    const renderer = create(<Header />);
    const markup = JSON.stringify(renderer.toJSON());

    expect(markup).toContain('企业深度调研');
    expect(markup).toContain('面向中国公司的公开信息调研助手');
    expect(markup).toContain('BovmantH/cn-company-research-agent');
    expect(markup.toLowerCase()).not.toContain('tavily.com');
    renderer.unmount();
  });
});
