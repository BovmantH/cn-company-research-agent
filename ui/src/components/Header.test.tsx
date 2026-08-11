import { create } from 'react-test-renderer';
import { describe, expect, it } from 'vitest';

import Header from './Header';

describe('Header', () => {
  it('在顶部导航展示紧凑的 Star 邀请和安全仓库外链', () => {
    const renderer = create(<Header />);
    const markup = JSON.stringify(renderer.toJSON());
    const repositoryLink = renderer.root.findByProps({
      'aria-label': '前往 GitHub 为项目点 Star',
    });

    expect(markup).toContain('企业深度调研');
    expect(markup).toContain('面向中国公司的公开信息调研助手');
    expect(markup).toContain('这个项目对你有帮助？');
    expect(markup).toContain('去 GitHub 点个 Star');
    expect(repositoryLink.props.href).toContain('BovmantH/cn-company-research-agent');
    expect(repositoryLink.props.target).toBe('_blank');
    expect(repositoryLink.props.rel).toBe('noopener noreferrer');
    expect(markup.toLowerCase()).not.toContain('tavily.com');
    renderer.unmount();
  });
});
