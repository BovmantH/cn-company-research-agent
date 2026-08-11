import { create } from 'react-test-renderer';
import { describe, expect, it } from 'vitest';

import ResearchNetworkBackground from './ResearchNetworkBackground';


describe('ResearchNetworkBackground', () => {
  it('以装饰性 SVG 渲染三档流速路径与呼吸节点', () => {
    const renderer = create(<ResearchNetworkBackground />);
    const network = renderer.root.findByType('svg');

    expect(network.props['aria-hidden']).toBe('true');
    expect(network.findAllByType('path').slice(0, 3).map((path) => path.props.className))
      .toEqual([
        'research-network-flow research-network-flow-slow',
        'research-network-flow research-network-flow-medium',
        'research-network-flow research-network-flow-fast',
      ]);
    expect(network.findAllByType('circle').every(
      (node) => node.props.className === 'research-network-node',
    )).toBe(true);

    renderer.unmount();
  });
});
