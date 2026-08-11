import { create } from 'react-test-renderer';
import { describe, expect, it } from 'vitest';

import { PROJECT_REPOSITORY_URL } from '../constants/project';
import ProjectFooter from './ProjectFooter';

describe('ProjectFooter', () => {
  it('显示低干扰 Star 邀请和安全 GitHub 外链', () => {
    const renderer = create(<ProjectFooter />);
    const link = renderer.root.findByProps({
      'aria-label': '前往 GitHub 为项目点 Star',
    });

    expect(JSON.stringify(renderer.toJSON())).toContain('欢迎在 GitHub 点个 Star');
    expect(link.props.href).toBe(PROJECT_REPOSITORY_URL);
    expect(link.props.target).toBe('_blank');
    expect(link.props.rel).toBe('noopener noreferrer');
  });
});
