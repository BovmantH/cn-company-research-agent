import { describe, expect, it } from 'vitest';

import { EXAMPLE_COMPANIES } from './exampleCompanies';

describe('EXAMPLE_COMPANIES', () => {
  it('首个一键示例使用苹果公司', () => {
    expect(EXAMPLE_COMPANIES[0]).toEqual({
      name: '苹果公司',
      url: 'apple.com',
      hq: '库比蒂诺,美国',
      industry: '消费电子、软件服务',
    });
  });
});
