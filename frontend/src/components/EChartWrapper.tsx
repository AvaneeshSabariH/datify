"use client";

/**
 * src/components/EChartWrapper.tsx
 * ──────────────────────────────────
 * Premium, client-side ECharts wrapper using the Canvas renderer.
 *
 * Features
 * ─────────
 * • Deep-merges "Apple × Linear × Stripe" aesthetic defaults into every
 *   options prop (glassmorphic tooltip, spring-loaded animations).
 * • Canvas renderer with selective ECharts tree-shaking.
 * • Animated conic-gradient "thinking glow" border when loading={true}.
 * • Clean empty state when options is absent or empty.
 * • Fully responsive — stretches to fill its container width.
 */

import React, { useMemo } from "react";

// ── ECharts core (tree-shaken) ─────────────────────────────────────────────

import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import {
  BarChart,
  LineChart,
  PieChart,
  ScatterChart,
  RadarChart,
  HeatmapChart,
  FunnelChart,
  GaugeChart,
} from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
  TitleComponent,
  LegendComponent,
  DataZoomComponent,
  VisualMapComponent,
  ToolboxComponent,
  MarkLineComponent,
  MarkPointComponent,
} from "echarts/components";
import ReactECharts from "echarts-for-react";

// Register everything once at module level.
echarts.use([
  CanvasRenderer,
  BarChart,
  LineChart,
  PieChart,
  ScatterChart,
  RadarChart,
  HeatmapChart,
  FunnelChart,
  GaugeChart,
  GridComponent,
  TooltipComponent,
  TitleComponent,
  LegendComponent,
  DataZoomComponent,
  VisualMapComponent,
  ToolboxComponent,
  MarkLineComponent,
  MarkPointComponent,
]);

// ── Types ──────────────────────────────────────────────────────────────────

export interface EChartWrapperProps {
  /** A flat Apache ECharts option object. Omit or pass {} for the empty state. */
  options?: Record<string, unknown>;
  /** Pixel height of the rendered chart area. Defaults to 420. */
  height?: number | string;
  /** Extra Tailwind classes for the outer container card. */
  className?: string;
  /** Inline style overrides for the outer container card. */
  style?: React.CSSProperties;
  /**
   * When true, hides the chart and shows the animated conic-gradient
   * "Datify is thinking…" glow ring instead of a standard spinner.
   */
  loading?: boolean;
  /** Optional title displayed above the chart inside the card. */
  title?: string;
  /** Optional subtitle / description text. */
  subtitle?: string;
}

// ── Premium Aesthetic Defaults ─────────────────────────────────────────────

/**
 * Deep-merged into every options object.
 * Consumer-provided values always win — this only fills in absent keys.
 */
const PREMIUM_DEFAULTS: Record<string, unknown> = {
  // Spring-loaded animation — 1200 ms with a natural cubic-out easing.
  animation: true,
  animationDuration: 1200,
  animationEasing: "cubicOut",
  animationDurationUpdate: 800,
  animationEasingUpdate: "cubicInOut",

  // Glassmorphic tooltip styling.
  tooltip: {
    show: true,
    backgroundColor: "rgba(255,255,255,0.70)",
    borderColor: "rgba(255,255,255,0.40)",
    borderWidth: 1,
    borderRadius: 12,
    textStyle: {
      color: "#0a0f28",
      fontFamily: "Inter, system-ui, sans-serif",
      fontSize: 13,
      fontWeight: 500,
    },
    // Backdrop-blur lives in extraCssText because ECharts renders the
    // tooltip as a DOM element, so regular CSS properties apply.
    extraCssText: [
      "backdrop-filter: blur(16px)",
      "-webkit-backdrop-filter: blur(16px)",
      "box-shadow: 0 8px 32px rgba(10,15,40,0.20)",
      "padding: 10px 14px",
    ].join(";"),
  },
};

// ── Helpers ────────────────────────────────────────────────────────────────

/** Shallow-checks whether an object is "empty" (no own enumerable keys). */
function isEmptyObject(obj: unknown): boolean {
  return (
    obj === null ||
    obj === undefined ||
    (typeof obj === "object" && Object.keys(obj as object).length === 0)
  );
}

/**
 * Deep-merge `defaults` into `target`.
 * Plain-object values are merged recursively; everything else is replaced
 * only when the target key is absent.
 */
function deepMergeDefaults(
  target: Record<string, unknown>,
  defaults: Record<string, unknown>
): Record<string, unknown> {
  const result: Record<string, unknown> = { ...target };
  for (const [key, defaultVal] of Object.entries(defaults)) {
    if (!(key in result)) {
      result[key] = defaultVal;
    } else if (
      typeof defaultVal === "object" &&
      defaultVal !== null &&
      !Array.isArray(defaultVal) &&
      typeof result[key] === "object" &&
      result[key] !== null &&
      !Array.isArray(result[key])
    ) {
      result[key] = deepMergeDefaults(
        result[key] as Record<string, unknown>,
        defaultVal as Record<string, unknown>
      );
    }
    // If the target already has the key with a non-object value, leave it alone.
  }
  return result;
}

// ── Sub-components ─────────────────────────────────────────────────────────

/** Clean empty state shown when no chart data is provided. */
function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center gap-4 py-16 select-none">
      {/* SVG chart icon */}
      <svg
        width="56"
        height="56"
        viewBox="0 0 56 56"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        aria-hidden="true"
      >
        <rect width="56" height="56" rx="14" fill="rgba(79,70,229,0.12)" />
        <rect x="12" y="32" width="8" height="12" rx="2" fill="rgba(79,70,229,0.35)" />
        <rect x="24" y="22" width="8" height="22" rx="2" fill="rgba(79,70,229,0.55)" />
        <rect x="36" y="14" width="8" height="30" rx="2" fill="#4f46e5" />
        <path
          d="M12 28 L20 20 L28 24 L36 12 L44 18"
          stroke="#06b6d4"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          fill="none"
        />
      </svg>
      <p className="text-sm font-medium text-white/40 tracking-wide uppercase">
        No data yet
      </p>
      <p className="text-xs text-white/25 max-w-[200px] text-center leading-relaxed">
        Run an analysis to generate a chart.
      </p>
    </div>
  );
}

/**
 * "Thinking Glow" loader — a rotating conic-gradient border ring.
 *
 * Implementation: two absolutely-positioned divs.
 * The outer div is the spinning conic ring; the inner div (inset 2px) is
 * the card background, creating the glowing border illusion.
 */
function ThinkingGlow({ height }: { height: number | string }) {
  const h = typeof height === "number" ? `${height}px` : height;
  return (
    <div
      className="relative rounded-2xl overflow-hidden"
      style={{ height: h }}
      role="status"
      aria-label="Datify is analysing your data"
    >
      {/* Spinning conic ring — rotates via animate-spin-glow (globals.css) */}
      <div
        className="animate-spin-glow absolute inset-0 rounded-2xl"
        style={{
          background:
            "conic-gradient(from 0deg, #4f46e5, #06b6d4, #818cf8, #06b6d4, #4f46e5)",
        }}
        aria-hidden="true"
      />
      {/* Inner card — 2 px inset to expose the ring */}
      <div
        className="absolute rounded-xl bg-[#0d1232] flex flex-col items-center justify-center gap-3"
        style={{ inset: "2px" }}
      >
        {/* Indigo/cyan gradient orb */}
        <div
          className="w-10 h-10 rounded-full"
          style={{
            background:
              "conic-gradient(from 0deg, #4f46e5, #06b6d4, #4f46e5)",
            filter: "blur(8px)",
            opacity: 0.8,
          }}
          aria-hidden="true"
        />
        <p className="animate-pulse-soft text-sm font-semibold tracking-wide"
          style={{
            background: "linear-gradient(135deg, #818cf8, #67e8f9)",
            WebkitBackgroundClip: "text",
            WebkitTextFillColor: "transparent",
            backgroundClip: "text",
          }}
        >
          Datify is thinking…
        </p>
      </div>
    </div>
  );
}

// ── Main Component ─────────────────────────────────────────────────────────

export default function EChartWrapper({
  options,
  height = 420,
  className = "",
  style,
  loading = false,
  title,
  subtitle,
}: EChartWrapperProps) {
  // Merge premium defaults into consumer options.
  const mergedOptions = useMemo(() => {
    if (isEmptyObject(options)) return null;
    return deepMergeDefaults(
      options as Record<string, unknown>,
      PREMIUM_DEFAULTS
    );
  }, [options]);

  const chartHeight =
    typeof height === "number" ? `${height}px` : height;

  const isEmpty = mergedOptions === null;

  return (
    <div
      className={[
        // Base card
        "rounded-2xl overflow-hidden",
        "bg-[#0d1232]",
        // Physical raised look
        "shadow-bento",
        // Smooth hover lift
        "transition-all duration-300 ease-out",
        !isEmpty && !loading && "hover:shadow-bento-hover hover:scale-[1.012]",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
      style={style}
    >
      {/* Optional card header */}
      {(title || subtitle) && (
        <div className="px-5 pt-5 pb-1">
          {title && (
            <h3 className="text-sm font-semibold text-white/90 tracking-tight">
              {title}
            </h3>
          )}
          {subtitle && (
            <p className="text-xs text-white/40 mt-0.5">{subtitle}</p>
          )}
        </div>
      )}

      {/* Chart area */}
      <div className="p-3">
        {loading ? (
          <ThinkingGlow height={height} />
        ) : isEmpty ? (
          <EmptyState />
        ) : (
          <ReactECharts
            echarts={echarts}
            option={mergedOptions as Record<string, unknown>}
            notMerge={true}
            lazyUpdate={false}
            style={{ height: chartHeight, width: "100%" }}
            opts={{ renderer: "canvas" }}
          />
        )}
      </div>
    </div>
  );
}
