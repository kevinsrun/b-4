"use client";

import { useEffect, useState } from "react";
import type { JobResponse, PredictionReport } from "@/lib/amp-types";
import { getAmpJob } from "@/lib/amp-api";
import { Panel, Status, Id } from "@/components/ui";

interface JobsTabProps {
  jobs: JobResponse[];
  onLoadJobReport: (report: PredictionReport) => void;
  isBackendConnected: boolean;
  useFixtures: boolean;
}

export function JobsTab({
  jobs,
  onLoadJobReport,
  isBackendConnected,
  useFixtures,
}: JobsTabProps) {
  const [activeJobId, setActiveJobId] = useState<string>(jobs[0]?.job_id || "");
  const [jobLookupInput, setJobLookupInput] = useState<string>("");
  const [currentJob, setCurrentJob] = useState<JobResponse | null>(jobs[0] || null);
  const [isPolling, setIsPolling] = useState(false);
  const [pollError, setPollError] = useState<string | null>(null);

  async function fetchJob(jobId: string) {
    if (!jobId.trim()) return;
    setPollError(null);
    try {
      const data = await getAmpJob(jobId.trim(), useFixtures || !isBackendConnected);
      setCurrentJob(data);
      if (data.status === "succeeded" || data.status === "partial_success" || data.status === "failed") {
        setIsPolling(false);
      }
    } catch (err: unknown) {
      setPollError(err instanceof Error ? err.message : String(err));
      setIsPolling(false);
    }
  }

  // Polling loop
  useEffect(() => {
    let intervalId: NodeJS.Timeout | null = null;
    if (isPolling && activeJobId) {
      intervalId = setInterval(() => {
        fetchJob(activeJobId);
      }, 2000);
    }
    return () => {
      if (intervalId) clearInterval(intervalId);
    };
  }, [isPolling, activeJobId]);

  function handleSelectJob(job: JobResponse) {
    setActiveJobId(job.job_id);
    setCurrentJob(job);
    if (job.status === "queued" || job.status === "running") {
      setIsPolling(true);
    } else {
      setIsPolling(false);
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-line pb-4">
        <div>
          <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-cyan">Batch Processing</p>
          <h2 className="mt-1 text-2xl font-medium tracking-tight text-text">
            AMP Job Monitoring & Execution Queue
          </h2>
          <p className="text-[12px] text-muted">
            Track asynchronous batch prediction jobs (GET /api/v1/amp/jobs/&#123;job_id&#125;).
          </p>
        </div>

        <div className="flex items-center gap-2">
          <input
            type="text"
            value={jobLookupInput}
            onChange={(e) => setJobLookupInput(e.target.value)}
            placeholder="Enter Job ID..."
            className="border border-line bg-ink px-2.5 py-1 text-[12px] text-text font-mono focus:border-cyan focus:outline-none"
          />
          <button
            onClick={() => {
              if (jobLookupInput.trim()) {
                setActiveJobId(jobLookupInput.trim());
                fetchJob(jobLookupInput.trim());
              }
            }}
            className="border border-line bg-raised px-3 py-1 text-[12px] font-medium text-text hover:border-cyan/40 hover:text-cyan"
          >
            Lookup Job
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        {/* Jobs List */}
        <div className="lg:col-span-5 space-y-3">
          <div className="flex items-center justify-between text-[12px] text-muted">
            <span>Known Batch Jobs ({jobs.length})</span>
          </div>

          <div className="space-y-2">
            {jobs.map((job) => {
              const isSelected = activeJobId === job.job_id;

              return (
                <div
                  key={job.job_id}
                  onClick={() => handleSelectJob(job)}
                  className={`cursor-pointer border p-3 transition-colors ${
                    isSelected
                      ? "border-cyan bg-panel shadow-sm ring-1 ring-cyan/40"
                      : "border-line bg-panel/70 hover:border-line-strong hover:bg-panel"
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-[12px] text-text font-medium truncate max-w-[200px]">
                      {job.job_id}
                    </span>
                    <Status status={job.status} />
                  </div>
                  <div className="mt-2 flex items-center justify-between text-[11px] text-muted">
                    <span>{new Date(job.created_at).toLocaleTimeString()}</span>
                    <span>
                      {job.report ? `${job.report.sequences.length} seqs` : "Pending report"}
                    </span>
                  </div>
                </div>
              );
            })}

            {jobs.length === 0 && (
              <div className="p-8 text-center text-[12px] text-muted border border-dashed border-line">
                No batch jobs submitted in this session. Submit an asynchronous job from the
                Submission workspace to monitor execution here.
              </div>
            )}
          </div>
        </div>

        {/* Selected Job Inspector */}
        <div className="lg:col-span-7">
          {currentJob ? (
            <Panel
              title={
                <div className="flex items-center gap-2">
                  <span>Job:</span>
                  <Id>{currentJob.job_id}</Id>
                  <Status status={currentJob.status} />
                </div>
              }
              aside={
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => fetchJob(currentJob.job_id)}
                    className="border border-line bg-raised px-2.5 py-1 text-[11px] font-medium text-muted hover:text-text"
                  >
                    ↻ Poll Now
                  </button>
                  {currentJob.report && (
                    <button
                      onClick={() => onLoadJobReport(currentJob.report!)}
                      className="border border-cyan/40 bg-cyan/15 px-3 py-1 text-[11px] font-medium text-cyan hover:bg-cyan/25"
                    >
                      Load into Results Workspace →
                    </button>
                  )}
                </div>
              }
            >
              <div className="space-y-4 text-[12px]">
                {pollError && (
                  <div className="border border-red/40 bg-red/10 p-2.5 text-red text-[11px]">
                    {pollError}
                  </div>
                )}

                <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 border border-line bg-raised/20 p-3">
                  <div>
                    <span className="text-[10px] uppercase text-faint block">Created At</span>
                    <span className="num text-text">{new Date(currentJob.created_at).toLocaleString()}</span>
                  </div>
                  <div>
                    <span className="text-[10px] uppercase text-faint block">Updated At</span>
                    <span className="num text-text">{new Date(currentJob.updated_at).toLocaleString()}</span>
                  </div>
                  <div>
                    <span className="text-[10px] uppercase text-faint block">Polling Active</span>
                    <span className={isPolling ? "text-cyan" : "text-muted"}>
                      {isPolling ? "Live (every 2s)" : "Paused"}
                    </span>
                  </div>
                </div>

                {currentJob.error && (
                  <div className="border border-red/40 bg-red/10 p-3 text-red">
                    <strong className="block">Job Execution Error:</strong>
                    <span>{currentJob.error.message || currentJob.error.code}</span>
                  </div>
                )}

                {currentJob.report ? (
                  <div className="space-y-3 border-t border-line pt-3">
                    <h4 className="font-medium text-text">Execution Report Summary</h4>
                    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 text-[11.5px]">
                      <div className="bg-panel border border-line p-2">
                        <span className="text-faint block">Total Sequences</span>
                        <span className="num text-text font-semibold">{currentJob.report.sequences.length}</span>
                      </div>
                      <div className="bg-panel border border-line p-2">
                        <span className="text-faint block">Successful Predictions</span>
                        <span className="num text-green font-semibold">{currentJob.report.execution.successful_predictions}</span>
                      </div>
                      <div className="bg-panel border border-line p-2">
                        <span className="text-faint block">Duration</span>
                        <span className="num text-text font-semibold">{currentJob.report.execution.duration_seconds.toFixed(2)}s</span>
                      </div>
                      <div className="bg-panel border border-line p-2">
                        <span className="text-faint block">Cache Hits</span>
                        <span className="num text-cyan font-semibold">{currentJob.report.execution.cache_hits}</span>
                      </div>
                    </div>

                    <div className="pt-2">
                      <button
                        onClick={() => onLoadJobReport(currentJob.report!)}
                        className="w-full border border-cyan/40 bg-cyan/15 py-2 text-center text-[12px] font-medium text-cyan hover:bg-cyan/25"
                      >
                        Inspect Full Results in Multi-Model Workspace →
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="border border-line bg-raised/10 p-6 text-center text-muted">
                    {currentJob.status === "queued"
                      ? "Job is queued waiting for execution workers..."
                      : currentJob.status === "running"
                      ? "Job is currently executing across configured model adapters..."
                      : "No report generated yet."}
                  </div>
                )}
              </div>
            </Panel>
          ) : (
            <div className="border border-line bg-panel p-12 text-center text-[12px] text-muted">
              Select a batch job to view status and execution details.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
