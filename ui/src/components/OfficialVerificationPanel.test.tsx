import { create } from 'react-test-renderer';
import { describe, expect, it } from 'vitest';

import OfficialVerificationPanel from './OfficialVerificationPanel';

describe('OfficialVerificationPanel', () => {
  it('只提供安全的官方平台跳转，不伪装成自动抓取', () => {
    const renderer = create(<OfficialVerificationPanel />);
    const links = renderer.root.findAllByType('a');

    expect(links.map((link) => link.props.href)).toEqual([
      'https://aiqicha.baidu.com/',
      'https://zxgk.court.gov.cn/',
    ]);
    for (const link of links) {
      expect(link.props.target).toBe('_blank');
      expect(link.props.rel).toBe('noopener noreferrer');
    }
    expect(JSON.stringify(renderer.toJSON())).toContain('材料上传后续支持');
    expect(JSON.stringify(renderer.toJSON())).toContain('不会读取第三方登录状态');
    renderer.unmount();
  });
});
