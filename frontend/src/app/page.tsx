"use client";

/**
 * src/app/page.tsx
 * ─────────────────
 * Datify — Two-Stage User Journey
 *
 * Stage 1 — Landing:   Centered hero with animated gradient title + CSV upload CTA.
 * Stage 2 — Workspace: Bento Box dashboard with charts, stats, and chat interface.
 *
 * State machine: fileSchema=null → Landing · fileSchema≠null → Workspace
 * Logo click resets to Landing from any state.
 */

import { useState, useRef, useCallback, useEffect } from "react";
import EChartWrapper from "@/components/EChartWrapper";
import toast, { Toaster } from "react-hot-toast";

// ── Types ──────────────────────────────────────────────────────────────────

interface FileSchema {
  name: string;
  size: number;
  rowCount: number;
  columns: number;
}


// ── Helpers ────────────────────────────────────────────────────────────────

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// ── Sub-components ─────────────────────────────────────────────────────────

/** Persistent sticky header — visible across both views */
function SiteHeader({ onLogoClick }: { onLogoClick: () => void }) {
  return (
    <header
      className="fixed top-0 left-0 right-0 z-50 flex items-center px-6 md:px-10"
      style={{
        height: "56px",
        background: "rgba(10,15,40,0.75)",
        backdropFilter: "blur(20px)",
        WebkitBackdropFilter: "blur(20px)",
        borderBottom: "1px solid rgba(255,255,255,0.06)",
      }}
    >
      {/* Logo badge */}
      <button
        onClick={onLogoClick}
        aria-label="Go to home"
        className="group flex items-center gap-2.5 focus:outline-none"
      >
        <div
          className="w-9 h-9 rounded-xl flex items-center justify-center shadow-rim-light transition-all duration-200 group-hover:scale-105"
          style={{
            background: "rgba(13,18,50,0.9)",
            border: "1px solid rgba(79,70,229,0.5)",
            boxShadow:
              "inset 0 1px 0 rgba(255,255,255,1), 0 0 16px rgba(79,70,229,0.35), 0 0 40px rgba(6,182,212,0.15)",
          }}
        >
          <span
            className="text-base font-bold"
            style={{
              background: "linear-gradient(135deg, #818cf8, #67e8f9)",
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent",
              backgroundClip: "text",
            }}
          >
            D
          </span>
        </div>
        <span
          className="text-sm font-semibold tracking-tight hidden sm:block"
          style={{
            background: "linear-gradient(135deg, #ffffff 0%, #c7d2fe 100%)",
            WebkitBackgroundClip: "text",
            WebkitTextFillColor: "transparent",
            backgroundClip: "text",
          }}
        >
          Datify
        </span>
      </button>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Nav pill */}
      <div
        className="hidden md:flex items-center gap-1 text-xs text-white/30 font-medium px-3 py-1.5 rounded-full"
        style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.07)" }}
      >
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
        <span className="ml-1.5">Backend · localhost:8000</span>
      </div>
    </header>
  );
}

/** Upload drop-zone card used on the landing page */
function UploadCard({
  onFile,
  isParsing,
}: {
  onFile: (file: File) => void;
  isParsing: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [isDragOver, setIsDragOver] = useState(false);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragOver(false);
      const file = e.dataTransfer.files[0];
      if (file) onFile(file);
    },
    [onFile]
  );

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) onFile(file);
  };

  if (isParsing) {
    return (
      <div className="w-full max-w-md mx-auto animate-scale-in">
        <EChartWrapper loading={true} height={220} />
        <p className="text-center text-xs text-white/35 mt-3 animate-pulse-soft font-medium">
          Profiling dataset…
        </p>
      </div>
    );
  }

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => inputRef.current?.click()}
      onKeyDown={(e) => e.key === "Enter" && inputRef.current?.click()}
      onDragOver={(e) => { e.preventDefault(); setIsDragOver(true); }}
      onDragLeave={() => setIsDragOver(false)}
      onDrop={handleDrop}
      aria-label="Upload CSV file"
      className={[
        "w-full max-w-md mx-auto rounded-2xl cursor-pointer",
        "transition-all duration-300 ease-out",
        "bg-[#0d1232]",
        isDragOver
          ? "shadow-upload-glow scale-[1.02] animate-drag-pulse"
          : "shadow-bento hover:shadow-upload-glow hover:scale-[1.015]",
      ].join(" ")}
    >
      <div
        className={[
          "rounded-2xl p-8 flex flex-col items-center gap-5",
          "border-2 border-dashed transition-colors duration-300",
          isDragOver ? "border-indigo-400/70" : "border-white/10 hover:border-indigo-500/40",
        ].join(" ")}
      >
        {/* Icon */}
        <div
          className="w-16 h-16 rounded-2xl flex items-center justify-center"
          style={{
            background: isDragOver
              ? "linear-gradient(135deg, rgba(79,70,229,0.35), rgba(6,182,212,0.35))"
              : "linear-gradient(135deg, rgba(79,70,229,0.15), rgba(6,182,212,0.15))",
            border: "1px solid rgba(79,70,229,0.4)",
            boxShadow: isDragOver ? "0 0 32px rgba(79,70,229,0.3)" : "none",
            transition: "all 0.3s",
          }}
        >
          <svg width="28" height="28" viewBox="0 0 28 28" fill="none" aria-hidden="true">
            <path
              d="M14 18V6M14 6L9 11M14 6L19 11"
              stroke="url(#lg1)"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
            <path
              d="M5 22H23"
              stroke="url(#lg1)"
              strokeWidth="2"
              strokeLinecap="round"
            />
            <defs>
              <linearGradient id="lg1" x1="5" y1="6" x2="23" y2="22" gradientUnits="userSpaceOnUse">
                <stop stopColor="#818cf8" />
                <stop offset="1" stopColor="#67e8f9" />
              </linearGradient>
            </defs>
          </svg>
        </div>

        {/* Labels */}
        <div className="text-center">
          <p className="text-base font-semibold text-white/85">
            {isDragOver ? "Release to upload" : "Drop a CSV file"}
          </p>
          <p className="text-sm text-white/35 mt-1.5">or click to browse from disk</p>
        </div>

        {/* Format badge */}
        <div
          className="flex items-center gap-2 px-3 py-1.5 rounded-full text-[11px] font-medium text-white/30"
          style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.06)" }}
        >
          <span>.csv</span>
          <span className="text-white/15">·</span>
          <span>up to 500 MB</span>
        </div>
      </div>

      <input
        ref={inputRef}
        type="file"
        accept=".csv"
        className="hidden"
        onChange={handleChange}
        aria-hidden="true"
        tabIndex={-1}
      />
    </div>
  );
}

/** Chat / Query interface card for the workspace */
function ChatCard({
  fileName,
  onQuery,
  disabled = false,
}: {
  fileName: string;
  onQuery: (q: string) => void;
  disabled?: boolean;
}) {
  const [query, setQuery] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea as the user types
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [query]);

  const submit = () => {
    const q = query.trim();
    if (!q || disabled) return;
    onQuery(q);
    setQuery("");
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit();
  };

  const canSubmit = query.trim() && !disabled;

  return (
    <div className="rounded-2xl bg-[#0d1232] shadow-bento p-5 flex flex-col gap-4 h-full">
      {/* Header */}
      <div className="flex items-center gap-2">
        <div
          className="w-6 h-6 rounded-lg flex items-center justify-center flex-shrink-0"
          style={{ background: "linear-gradient(135deg, #4f46e5, #06b6d4)" }}
        >
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
            <path d="M1 6h10M6 1l4 5-4 5" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>
        <div>
          <p className="text-xs font-semibold text-white/80 leading-none">
            {disabled ? "Analyzing…" : "Run Query"}
          </p>
          <p className="text-[10px] text-white/30 mt-0.5 truncate max-w-[140px]" title={fileName}>
            {fileName}
          </p>
        </div>
      </div>

      {/* Textarea */}
      <div
        className="flex-1 rounded-xl overflow-hidden"
        style={{ border: "1px solid rgba(255,255,255,0.08)", background: "rgba(255,255,255,0.03)" }}
      >
        <textarea
          ref={textareaRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={disabled
            ? "Agent is processing your request…"
            : "e.g. Show me a bar chart of revenue by month\nor  Find outliers in the price column"
          }
          aria-label="Analysis query"
          disabled={disabled}
          rows={4}
          className={[
            "w-full bg-transparent resize-none px-4 py-3",
            "text-sm text-white/80 placeholder:text-white/20",
            "focus:outline-none scrollbar-hide",
            "leading-relaxed font-medium",
            disabled ? "opacity-50 cursor-not-allowed" : "",
          ].join(" ")}
          style={{ maxHeight: "160px", overflowY: "auto", fontFamily: "Inter, sans-serif" }}
        />
      </div>

      {/* Footer — hint + submit */}
      <div className="flex items-center justify-between gap-3">
        <span className="text-[10px] text-white/20 font-medium hidden sm:block">
          {disabled ? "" : "⌘ Enter to run"}
        </span>
        <button
          onClick={submit}
          disabled={!canSubmit}
          className={[
            "flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold",
            "transition-all duration-200",
            canSubmit
              ? "text-white cursor-pointer hover:scale-[1.03] active:scale-[0.98]"
              : "text-white/25 cursor-not-allowed",
          ].join(" ")}
          style={{
            background: canSubmit
              ? "linear-gradient(135deg, #4f46e5, #06b6d4)"
              : "rgba(255,255,255,0.05)",
            boxShadow: canSubmit ? "0 0 20px rgba(79,70,229,0.35)" : "none",
          }}
        >
          {disabled ? (
            <>
              <span className="animate-pulse-soft">⏳</span>
              Analyzing…
            </>
          ) : (
            <>
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
                <path d="M1 6h10M7 2l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              Run Query
            </>
          )}
        </button>
      </div>
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────

export default function Page() {
  const [fileSchema, setFileSchema] = useState<FileSchema | null>(null);
  const [isParsing, setIsParsing] = useState(false);
  const [workspaceVisible, setWorkspaceVisible] = useState(false);

  // ── Backend-connected state ────────────────────────────────────────────
  const [csvSessionPath, setCsvSessionPath] = useState("");
  const [schemaJson, setSchemaJson] = useState("");
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [dynamicChartData, setDynamicChartData] = useState<Record<string, unknown> | null>(null);

  /** Called when the user selects or drops a file */
  const handleFile = useCallback(async (file: File) => {
    setIsParsing(true);
    try {
      const formData = new FormData();
      formData.append("file", file);

      const res = await fetch("http://localhost:8000/upload", {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || "Upload failed");
      }

      const data = await res.json();
      setCsvSessionPath(data.csv_session_path);
      setSchemaJson(data.schema_json);

      // Parse schema_json to extract real profiler stats
      const schema = JSON.parse(data.schema_json);
      setFileSchema({
        name: file.name,
        size: file.size,
        rowCount: schema.dataset_info?.total_rows ?? 0,
        columns: schema.dataset_info?.total_columns ?? 0,
      });

      // Tiny delay so the DOM re-renders before adding the class
      requestAnimationFrame(() => {
        setWorkspaceVisible(true);
        toast.success("Dataset loaded successfully!");
      });
    } catch (err) {
      toast.error(`Upload failed: ${err instanceof Error ? err.message : err}`);
    } finally {
      setIsParsing(false);
    }
  }, []);

  /** Logo click — reset everything back to landing */
  const handleReset = useCallback(() => {
    setWorkspaceVisible(false);
    // Wait for fade-out before clearing state
    setTimeout(() => {
      setFileSchema(null);
      setCsvSessionPath("");
      setSchemaJson("");
      setDynamicChartData(null);
    }, 200);
  }, []);

  const handleQuery = async (q: string) => {
    setIsAnalyzing(true);
    try {
      const res = await fetch("http://localhost:8000/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query: q,
          csv_session_path: csvSessionPath,
          schema_json: schemaJson,
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || "Query failed");
      }

      const data = await res.json();

      // Store the chart configuration for rendering
      if (data.chart_json && Object.keys(data.chart_json).length > 0) {
        setDynamicChartData(data.chart_json);
      }

      // Version chaining — update to the new CSV path
      if (data.new_csv_path) {
        setCsvSessionPath(data.new_csv_path);
      }
    } catch (err) {
      toast.error(`Analysis failed: ${err instanceof Error ? err.message : err}`);
    } finally {
      setIsAnalyzing(false);
    }
  };

  // Sum null_count across all columns from the real profiler schema.
  const nullCells = (() => {
    try {
      const schema = JSON.parse(schemaJson);
      return Object.values(
        schema.columns as Record<string, { null_count: number }>
      ).reduce(
        (sum: number, col: { null_count: number }) => sum + (col.null_count ?? 0),
        0
      );
    } catch {
      return 0;
    }
  })();

  const stats = fileSchema
    ? [
        { label: "Total Rows", value: fileSchema.rowCount.toLocaleString() },
        { label: "Columns",    value: String(fileSchema.columns) },
        { label: "Null Cells", value: nullCells.toLocaleString() },
      ]
    : [];

  return (
    <>
      <Toaster position="bottom-right" />
      {/* ── Persistent Header ─────────────────────────────────────────────── */}
      <SiteHeader onLogoClick={handleReset} />

      {/* ── Push content below fixed header ───────────────────────────────── */}
      <div style={{ paddingTop: "56px" }} className="min-h-screen">

        {/* ═══════════════════════════════════════════════════════════════════
            STATE 1 — LANDING VIEW
        ═══════════════════════════════════════════════════════════════════ */}
        {!fileSchema && (
          <section
            className="min-h-[calc(100vh-56px)] flex flex-col items-center justify-center px-6 py-12 animate-fade-in"
          >
            {/* Hero copy */}
            <div className="text-center mb-10 animate-scale-in">
              {/* Ambient glow orb behind the title */}
              <div
                aria-hidden="true"
                className="pointer-events-none absolute left-1/2 -translate-x-1/2"
                style={{
                  width: "600px",
                  height: "300px",
                  background: "radial-gradient(ellipse at center, rgba(79,70,229,0.18) 0%, transparent 70%)",
                  filter: "blur(40px)",
                  transform: "translateX(-50%)",
                  zIndex: 0,
                }}
              />

              <div className="relative z-10">
                <h1
                  className="hero-gradient-text text-7xl md:text-8xl font-extrabold tracking-tight leading-none mb-4 select-none"
                >
                  Datify
                </h1>
                <p className="text-lg md:text-xl text-white/40 font-medium tracking-wide max-w-md mx-auto">
                  Autonomous AI Data Scientist Copilot
                </p>
                <p className="text-sm text-white/25 mt-2 font-medium">
                  Drop a CSV · Ask a question · Get a chart
                </p>
              </div>
            </div>

            {/* Upload card — the hero CTA */}
            <div className="relative z-10 w-full flex justify-center px-4">
              <UploadCard onFile={handleFile} isParsing={isParsing} />
            </div>

            {/* Footer hint */}
            {!isParsing && (
              <p className="mt-10 text-[11px] text-white/15 font-medium">
                Datify · Privacy-first · Powered by Claude & Apache ECharts
              </p>
            )}
          </section>
        )}

        {/* ═══════════════════════════════════════════════════════════════════
            STATE 2 — WORKSPACE DASHBOARD
        ═══════════════════════════════════════════════════════════════════ */}
        {fileSchema && (
          <section
            className="px-6 py-8 md:px-10 md:py-10 max-w-[1400px] mx-auto w-full"
            style={{
              opacity: workspaceVisible ? 1 : 0,
              transform: workspaceVisible ? "translateY(0)" : "translateY(12px)",
              transition: "opacity 0.4s ease-out, transform 0.4s ease-out",
            }}
          >
            {/* ── Workspace Header ──────────────────────────────────────── */}
            <div className="mb-7 flex flex-wrap items-end justify-between gap-4">
              <div>
                <h2 className="text-xl font-bold text-white/90 leading-tight">
                  Workspace
                </h2>
                <p className="text-sm text-white/35 mt-0.5 font-medium">
                  {fileSchema.name}
                  <span className="mx-2 text-white/15">·</span>
                  {formatBytes(fileSchema.size)}
                </p>
              </div>
              <button
                onClick={handleReset}
                className="text-xs text-white/30 hover:text-white/60 transition-colors duration-150 font-medium flex items-center gap-1.5"
                aria-label="Upload new file"
              >
                <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
                  <path d="M1 6a5 5 0 1 0 5-5 5 5 0 0 0-4.9 4" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/>
                  <path d="M1 2v4h4" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
                Upload new file
              </button>
            </div>

            {/* ── Bento Grid ────────────────────────────────────────────── */}
            <div
              className="grid gap-4 w-full"
              style={{
                gridTemplateColumns: "repeat(3, 1fr)",
                gridTemplateRows: "auto auto",
                gridTemplateAreas: `
                  "hero   hero   stats"
                  "hero   hero   chat"
                `,
              }}
            >

              {/* Hero Chart — dynamic from backend */}
              <div style={{ gridArea: "hero" }} className="animate-fade-up">
                <EChartWrapper
                  options={dynamicChartData ?? undefined}
                  loading={isAnalyzing}
                  height={340}
                  title={dynamicChartData ? "Analysis Result" : undefined}
                  subtitle={dynamicChartData ? "Generated by Datify Agent" : undefined}
                />
              </div>

              {/* Stats Column */}
              <div
                style={{ gridArea: "stats" }}
                className="rounded-2xl bg-[#0d1232] shadow-bento p-5 flex flex-col gap-3 animate-fade-up"
              >
                <h3 className="text-xs font-semibold text-white/50 uppercase tracking-widest mb-1">
                  Dataset Overview
                </h3>
                {stats.map((s) => (
                  <div
                    key={s.label}
                    className="flex items-center justify-between rounded-xl bg-white/[0.03] px-4 py-3 border border-white/[0.05]"
                  >
                    <span className="text-xs text-white/50 font-medium">{s.label}</span>
                    <span
                      className="text-lg font-bold tabular-nums"
                      style={{
                        background: "linear-gradient(135deg, #818cf8, #67e8f9)",
                        WebkitBackgroundClip: "text",
                        WebkitTextFillColor: "transparent",
                        backgroundClip: "text",
                      }}
                    >
                      {s.value}
                    </span>
                  </div>
                ))}

                {/* AI Status */}
                <div className="mt-2">
                  <p className="text-[10px] text-white/30 mb-2 uppercase tracking-wider font-medium">
                    AI Status
                  </p>
                  <EChartWrapper loading={isAnalyzing} height={88} />
                </div>
              </div>


              {/* Chat Interface — replaces old upload CTA */}
              <div style={{ gridArea: "chat" }} className="animate-fade-up">
                <ChatCard fileName={fileSchema.name} onQuery={handleQuery} disabled={isAnalyzing} />
              </div>

            </div>

            {/* Footer */}
            <footer className="mt-10 text-center text-[11px] text-white/15 font-medium">
              Datify · Privacy-first · Powered by Claude & Apache ECharts
            </footer>
          </section>
        )}

      </div>
    </>
  );
}
