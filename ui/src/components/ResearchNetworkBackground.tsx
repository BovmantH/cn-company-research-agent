const ResearchNetworkBackground = () => (
  <svg
    aria-hidden="true"
    className="research-network pointer-events-none absolute inset-x-0 top-16 h-[900px] w-full"
    viewBox="0 0 1600 900"
    preserveAspectRatio="none"
  >
    <g fill="none" stroke="currentColor" strokeWidth="1.2">
      <path
        className="research-network-flow research-network-flow-slow"
        d="M-100 180 C180 18 360 90 560 250 S940 500 1200 250 1530 120 1710 220"
      />
      <path
        className="research-network-flow research-network-flow-medium"
        d="M-80 360 C220 220 420 265 630 420 S1020 620 1280 400 1540 300 1690 360"
      />
      <path
        className="research-network-flow research-network-flow-fast"
        d="M-120 650 C220 470 500 540 720 700 S1120 850 1420 630 1640 560 1740 610"
      />
      <path d="M80 -40 C210 210 180 470 20 760" />
      <path d="M1510 -60 C1390 210 1420 520 1600 780" />
    </g>
    <g fill="currentColor">
      <circle className="research-network-node" cx="145" cy="106" r="4" />
      <circle className="research-network-node" cx="360" cy="124" r="3" />
      <circle className="research-network-node" cx="1190" cy="255" r="4" />
      <circle className="research-network-node" cx="1455" cy="195" r="3" />
      <circle className="research-network-node" cx="1320" cy="430" r="4" />
      <circle className="research-network-node" cx="190" cy="515" r="3" />
      <circle className="research-network-node" cx="1520" cy="675" r="4" />
    </g>
  </svg>
);

export default ResearchNetworkBackground;
