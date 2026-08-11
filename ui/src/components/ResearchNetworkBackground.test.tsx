import { create } from 'react-test-renderer';
import { describe, expect, it } from 'vitest';

import ResearchNetworkBackground from './ResearchNetworkBackground';

describe('ResearchNetworkBackground', () => {
  it('以装饰性 SVG 渲染三层信息流光、方向轨迹与移动光点', () => {
    const renderer = create(<ResearchNetworkBackground />);
    const network = renderer.root.findByType('svg');
    const paths = network.findAllByType('path');
    const sparks = network.findAllByProps({ className: 'research-flow-spark' });

    expect(network.props['aria-hidden']).toBe('true');
    expect(network.props.className).toContain('research-flow-background');
    expect(paths.filter((path) => path.props.className.includes('research-flow-ribbon')))
      .toHaveLength(3);
    expect(paths.filter((path) => path.props.className.includes('research-flow-trace')))
      .toHaveLength(3);
    expect(sparks).toHaveLength(3);
    expect(sparks.every((spark) => spark.findAllByType('animateMotion').length === 1))
      .toBe(true);

    renderer.unmount();
  });
});
