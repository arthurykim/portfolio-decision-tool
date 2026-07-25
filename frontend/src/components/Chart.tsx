import { useRef, useState } from "react";

export interface Overlay {
  values: number[];
  color: string;
}

interface Props {
  dates: string[];
  values: number[];
  color: string;
  area?: boolean;
  fmt: (v: number) => string;
  fmtAxis?: (v: number) => string;
  overlay?: Overlay | null;
  height?: number;
}

const W = 900;
const H = 300;
const PAD = { top: 12, right: 16, bottom: 26, left: 60 };

/** Hand-rolled SVG line chart with crosshair + tooltip. No charting library. */
export default function Chart({
  dates, values, color, area = false, fmt, fmtAxis = fmt, overlay = null,
}: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<number | null>(null);

  if (!values.length) return <p className="fineprint">No data.</p>;

  const iw = W - PAD.left - PAD.right;
  const ih = H - PAD.top - PAD.bottom;

  const scaleValues = overlay ? values.concat(overlay.values) : values;
  let min = Math.min(...scaleValues);
  let max = Math.max(...scaleValues);
  if (min === max) { min -= 1; max += 1; }
  const spread = max - min;
  min -= spread * 0.05;
  max += spread * 0.05;

  const x = (i: number, n = values.length) => PAD.left + (i / Math.max(n - 1, 1)) * iw;
  const y = (v: number) => PAD.top + (1 - (v - min) / (max - min)) * ih;

  const path = (vals: number[]) =>
    vals.map((v, i) => `${x(i, vals.length).toFixed(1)},${y(v).toFixed(1)}`).join(" L ");

  const gridlines = [0, 1, 2, 3].map((k) => {
    const v = min + ((max - min) * k) / 3;
    return { v, gy: y(v) };
  });

  const xTicks = [0, Math.floor(values.length / 2), values.length - 1];

  function onMove(e: React.MouseEvent<SVGSVGElement>) {
    const rect = svgRef.current!.getBoundingClientRect();
    const mx = ((e.clientX - rect.left) / rect.width) * W;
    const i = Math.round(((mx - PAD.left) / iw) * (values.length - 1));
    setHover(Math.max(0, Math.min(values.length - 1, i)));
  }

  const baseline = y(Math.min(max, Math.max(min, 0)));

  return (
    <div className="chart">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
      >
        {gridlines.map(({ v, gy }) => (
          <g key={gy}>
            <line className="gridline" x1={PAD.left} x2={W - PAD.right} y1={gy} y2={gy} />
            <text className="axis-label" x={PAD.left - 8} y={gy + 4} textAnchor="end">
              {fmtAxis(v)}
            </text>
          </g>
        ))}

        {xTicks.map((i, k) => (
          <text
            key={k}
            className="axis-label"
            x={x(i)}
            y={H - 6}
            textAnchor={i === 0 ? "start" : i === values.length - 1 ? "end" : "middle"}
          >
            {dates[i]}
          </text>
        ))}

        {overlay && (
          <path
            d={`M ${path(overlay.values)}`}
            fill="none"
            stroke={overlay.color}
            strokeWidth={1.75}
            strokeDasharray="5 4"
            opacity={0.9}
          />
        )}

        {area && (
          <path
            d={`M ${path(values)} L ${x(values.length - 1).toFixed(1)},${baseline} L ${x(0).toFixed(1)},${baseline} Z`}
            fill={color}
            opacity={0.15}
          />
        )}

        <path d={`M ${path(values)}`} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" />

        {hover !== null && (
          <>
            <line
              className="baseline"
              x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={H - PAD.bottom}
            />
            <circle
              cx={x(hover)} cy={y(values[hover])} r={4}
              fill={color} stroke="var(--surface-1)" strokeWidth={2}
            />
          </>
        )}
      </svg>

      {hover !== null && (
        <div
          className="tooltip"
          style={{
            display: "block",
            left: `${Math.min((x(hover) / W) * 100, 88)}%`,
            top: `${(y(values[hover]) / H) * 100 - 14}%`,
          }}
        >
          <div className="tt-date">{dates[hover]}</div>
          <div className="tt-val">{fmt(values[hover])}</div>
        </div>
      )}
    </div>
  );
}

/** Tiny inline sparkline for cards. */
export function Sparkline({ values, width = 90, height = 28 }: {
  values: number[]; width?: number; height?: number;
}) {
  if (values.length < 2) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const pts = values
    .map((v, i) =>
      `${((i / (values.length - 1)) * width).toFixed(1)},${(height - 2 - ((v - min) / range) * (height - 4)).toFixed(1)}`)
    .join(" L ");
  const up = values[values.length - 1] >= values[0];
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
      <path
        d={`M ${pts}`}
        fill="none"
        stroke={`var(${up ? "--delta-up" : "--delta-down"})`}
        strokeWidth={1.5}
      />
    </svg>
  );
}
