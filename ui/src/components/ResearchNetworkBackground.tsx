const FLOW_ROUTES = [
  {
    name: 'primary',
    path: 'M-180 135 C120 10 350 65 575 215 S980 470 1240 245 1530 95 1780 220',
    duration: '17s',
    begin: '-5s',
    radius: 4.5,
  },
  {
    name: 'secondary',
    path: 'M-160 395 C135 210 410 275 650 430 S1060 690 1330 455 1580 305 1770 385',
    duration: '21s',
    begin: '-13s',
    radius: 3.8,
  },
  {
    name: 'tertiary',
    path: 'M-190 735 C125 505 435 565 715 755 S1160 965 1440 700 1660 590 1800 660',
    duration: '24s',
    begin: '-8s',
    radius: 3.4,
  },
] as const;

const AMBIENT_PARTICLES = [
  [74, 192, 2.4],
  [218, 82, 2.8],
  [386, 246, 2.1],
  [1180, 115, 2.5],
  [1440, 198, 3],
  [1525, 486, 2.2],
  [185, 650, 2.7],
  [420, 835, 2.2],
  [1195, 825, 2.5],
  [1488, 755, 3.1],
] as const;

const ResearchNetworkBackground = () => (
  <svg
    aria-hidden="true"
    className="research-flow-background pointer-events-none absolute inset-x-0 top-16 h-[calc(100%-4rem)] min-h-[900px] w-full"
    viewBox="0 0 1600 1040"
    preserveAspectRatio="none"
  >
    <defs>
      <linearGradient id="research-flow-ribbon-gradient" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0%" stopColor="#dbeafe" stopOpacity="0.08" />
        <stop offset="38%" stopColor="#60a5fa" stopOpacity="0.44" />
        <stop offset="68%" stopColor="#22d3ee" stopOpacity="0.26" />
        <stop offset="100%" stopColor="#bfdbfe" stopOpacity="0.04" />
      </linearGradient>
      <radialGradient id="research-flow-halo-gradient">
        <stop offset="0%" stopColor="#60a5fa" stopOpacity="0.42" />
        <stop offset="52%" stopColor="#bae6fd" stopOpacity="0.18" />
        <stop offset="100%" stopColor="#eff6ff" stopOpacity="0" />
      </radialGradient>
      <filter id="research-flow-soft-glow" x="-40%" y="-40%" width="180%" height="180%">
        <feGaussianBlur stdDeviation="9" />
      </filter>
      <filter id="research-flow-spark-glow" x="-250%" y="-250%" width="600%" height="600%">
        <feGaussianBlur stdDeviation="4" result="blur" />
        <feMerge>
          <feMergeNode in="blur" />
          <feMergeNode in="SourceGraphic" />
        </feMerge>
      </filter>
    </defs>

    <ellipse
      className="research-flow-halo research-flow-halo-start"
      cx="80"
      cy="165"
      rx="430"
      ry="315"
      fill="url(#research-flow-halo-gradient)"
    />
    <ellipse
      className="research-flow-halo research-flow-halo-end"
      cx="1540"
      cy="820"
      rx="470"
      ry="350"
      fill="url(#research-flow-halo-gradient)"
    />

    <g fill="none" strokeLinecap="round">
      {FLOW_ROUTES.map((route) => (
        <path
          key={`ribbon-${route.name}`}
          className={`research-flow-ribbon research-flow-ribbon-${route.name}`}
          d={route.path}
          stroke="url(#research-flow-ribbon-gradient)"
          filter="url(#research-flow-soft-glow)"
        />
      ))}
      {FLOW_ROUTES.map((route) => (
        <path
          key={`trace-${route.name}`}
          className={`research-flow-trace research-flow-trace-${route.name}`}
          d={route.path}
        />
      ))}
    </g>

    <g fill="currentColor">
      {AMBIENT_PARTICLES.map(([cx, cy, radius], index) => (
        <circle
          key={`${cx}-${cy}`}
          className="research-flow-particle"
          cx={cx}
          cy={cy}
          r={radius}
          style={{ animationDelay: `${index * -0.7}s` }}
        />
      ))}
    </g>

    <g filter="url(#research-flow-spark-glow)">
      {FLOW_ROUTES.map((route) => (
        <circle key={`spark-${route.name}`} className="research-flow-spark" r={route.radius}>
          <animateMotion
            path={route.path}
            dur={route.duration}
            begin={route.begin}
            repeatCount="indefinite"
            calcMode="paced"
          />
        </circle>
      ))}
    </g>
  </svg>
);

export default ResearchNetworkBackground;
