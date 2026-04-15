import React, { useMemo, useState } from "react";
import { APP_META } from "./appMeta";
import { LANGUAGE_OPTIONS, UI_STRINGS } from "./locales";
import { LanguageCode } from "./locales/types";

type ParserType =
  | "pypdf"
  | "gemini-2.5-flash-pdf"
  | "gemini-2.5-flash-text"
  | "gemini-2.5-flash"
  | "mistral"
  | "mistral-ocr";

type ExtractItem = {
  filename: string;
  parser?: ParserType;
  sha256?: string;
  cached?: boolean;
  text?: string;
  pages?: Array<{ page: number; content: string }>;
  summary?: string;
  summary_cached?: boolean;
  error?: string;
};

type AsyncJobStatus = "queued" | "processing" | "done" | "failed";

type AsyncJobItem = {
  job_id: string;
  filename: string;
  parser: ParserType;
  status: AsyncJobStatus;
  error?: string;
};

async function extractPdf(
  files: File[],
  parser: ParserType,
  language: LanguageCode,
): Promise<{ results: ExtractItem[] }> {
  const form = new FormData();
  for (const file of files) {
    form.append("files", file);
  }
  form.append("parser", parser);
  form.append("language", language);

  const res = await fetch("/api/pdf/extract", {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

async function extractPdfAsync(
  files: File[],
  parser: ParserType,
  language: LanguageCode,
): Promise<{ jobs: Array<{ job_id: string; filename: string; parser: ParserType }> }> {
  const form = new FormData();
  for (const file of files) {
    form.append("files", file);
  }
  form.append("parser", parser);
  form.append("language", language);

  const res = await fetch("/api/jobs/extract", {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

async function askGemini(
  prompt: string,
  context: string | undefined,
  language: LanguageCode,
): Promise<{ model: string; text: string }> {
  const res = await fetch("/api/gemini/answer", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ prompt, context, language }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export default function App() {
  const [files, setFiles] = useState<File[]>([]);
  const [status, setStatus] = useState<string>(UI_STRINGS.en.extractStatusIdle);
  const [extractResults, setExtractResults] = useState<ExtractItem[]>([]);
  const [asyncJobs, setAsyncJobs] = useState<AsyncJobItem[]>([]);

  const [prompt, setPrompt] = useState<string>("");
  const [answer, setAnswer] = useState<string>("");
  const [isWorking, setIsWorking] = useState<boolean>(false);
  const [language, setLanguage] = useState<LanguageCode>("en");
  const [parser, setParser] = useState<ParserType>("pypdf");
  const ui = UI_STRINGS[language];

  const contextForGemini = useMemo(() => {
    // Merge extracted texts from multiple files and keep prompt size bounded.
    const allText = extractResults
      .map((r) => r.text || "")
      .filter(Boolean)
      .join("\n\n---\n\n");
    if (!allText) return undefined;
    return allText.slice(0, 12000);
  }, [extractResults]);

  return (
    <div style={{ fontFamily: "system-ui, Arial", maxWidth: 900, margin: "24px auto", padding: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
        <h1 style={{ margin: 0 }}>{ui.title}</h1>
        <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {ui.interfaceLanguageLabel}
          <select value={language} onChange={(e) => setLanguage(e.target.value as LanguageCode)}>
            {LANGUAGE_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <section style={{ marginTop: 16 }}>
        <h2>{ui.extractTitle}</h2>
        <input
          type="file"
          multiple
          accept="application/pdf"
          onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
        />
        <div style={{ marginTop: 8 }}>
          <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {ui.parserLabel}
            <select value={parser} onChange={(e) => setParser(e.target.value as ParserType)}>
              <option value="pypdf">{ui.parserPypdfOption}</option>
              <option value="gemini-2.5-flash-pdf">{ui.parserGeminiPdfOption}</option>
              <option value="gemini-2.5-flash-text">{ui.parserGeminiTextOption}</option>
              <option value="gemini-2.5-flash">{ui.parserGeminiLegacyOption}</option>
              <option value="mistral">{ui.parserMistralOption}</option>
              <option value="mistral-ocr">{ui.parserMistralOcrOption}</option>
            </select>
          </label>
        </div>
        <div style={{ marginTop: 6, fontSize: 13, color: "#555" }}>{ui.extractMultiHint}</div>
        {files.length > 0 && (
          <div style={{ marginTop: 6, fontSize: 13 }}>
            <strong>{ui.selectedFilesLabel}:</strong> {files.map((f) => f.name).join(", ")}
          </div>
        )}
        <div style={{ marginTop: 8 }}>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <button
              disabled={files.length === 0 || isWorking}
              onClick={async () => {
                try {
                  setIsWorking(true);
                  setStatus(ui.extractStatusRunning);
                  setExtractResults([]);
                  setAsyncJobs([]);
                  setAnswer("");
                  if (files.length === 0) return;
                  const result = await extractPdf(files, parser, language);
                  setExtractResults(result.results);
                  const okCount = result.results.filter((r) => !r.error).length;
                  const cacheHits = result.results.filter((r) => r.cached === true).length;
                  setStatus(
                    `${ui.extractStatusDone(cacheHits > 0)} Files processed: ${okCount}/${result.results.length}.`,
                  );
                } catch (e: any) {
                  setStatus(`${ui.errorPrefix}: ${e?.message ?? String(e)}`);
                } finally {
                  setIsWorking(false);
                }
              }}
            >
              {ui.extractButton}
            </button>

            <button
              disabled={files.length === 0 || isWorking}
              onClick={async () => {
                try {
                  setIsWorking(true);
                  setStatus(ui.extractStatusRunning);
                  setExtractResults([]);
                  setAsyncJobs([]);
                  setAnswer("");
                  if (files.length === 0) return;

                  const created = await extractPdfAsync(files, parser, language);
                  const jobs = created.jobs || [];

                  setAsyncJobs(
                    jobs.map((j) => ({
                      job_id: j.job_id,
                      filename: j.filename,
                      parser: j.parser,
                      status: "queued",
                    })),
                  );

                  const pollOne = async (job_id: string, filenameForJob: string) => {
                    const maxAttempts = 45;
                    const intervalMs = 1000;
                    for (let attempt = 0; attempt < maxAttempts; attempt++) {
                      const res = await fetch(`/api/jobs/${job_id}`);
                      const job = await res.json();
                      const nextStatus = (job.status as AsyncJobStatus) || "processing";
                      const nextError = (job.error as string) || undefined;

                      setAsyncJobs((prev) =>
                        prev.map((x) =>
                          x.job_id === job_id ? { ...x, status: nextStatus, error: nextError } : x,
                        ),
                      );

                      if (nextStatus === "done") {
                        const parsed = job.result || {};
                        const item: ExtractItem = {
                          filename: job.filename || parsed.filename || "unknown.pdf",
                          parser: (job.parser as ParserType) || parser,
                          sha256: parsed.sha256,
                          cached: parsed.cached,
                          text: parsed.text,
                          pages: parsed.pages,
                          summary: parsed.summary,
                          summary_cached: parsed.summary_cached,
                        };
                        setExtractResults((prev) => [...prev, item]);
                        return;
                      }

                      if (nextStatus === "failed") {
                        const item: ExtractItem = {
                          filename: job.filename || "unknown.pdf",
                          parser: (job.parser as ParserType) || parser,
                          error: job.error || "Job failed",
                        };
                        setExtractResults((prev) => [...prev, item]);
                        return;
                      }

                      await new Promise((r) => setTimeout(r, intervalMs));
                    }

                    setAsyncJobs((prev) => prev.map((x) => (x.job_id === job_id ? { ...x, status: "failed" } : x)));
                    setExtractResults((prev) => [
                      ...prev,
                      { filename: filenameForJob || "unknown.pdf", parser, error: "Timeout" },
                    ]);
                  };

                  await Promise.all(jobs.map((j) => pollOne(j.job_id, j.filename)));

                  setStatus("Async extraction completed.");
                } catch (e: any) {
                  setStatus(`${ui.errorPrefix}: ${e?.message ?? String(e)}`);
                } finally {
                  setIsWorking(false);
                }
              }}
            >
              Extract async
            </button>
          </div>
        </div>
      </section>

      <section style={{ marginTop: 16 }}>
        <h2>{ui.geminiTitle}</h2>
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder={ui.promptPlaceholder}
          rows={4}
          style={{ width: "100%" }}
        />
        <div style={{ marginTop: 8 }}>
          <button
            disabled={isWorking || !prompt.trim()}
            onClick={async () => {
              try {
                setIsWorking(true);
                setStatus(ui.geminiStatusRunning);
                setAnswer("");
                const result = await askGemini(prompt.trim(), contextForGemini, language);
                setAnswer(result.text || "(brak odpowiedzi)");
                setStatus(ui.geminiStatusDone);
              } catch (e: any) {
                setStatus(`${ui.errorPrefix}: ${e?.message ?? String(e)}`);
              } finally {
                setIsWorking(false);
              }
            }}
          >
            {ui.askButton}
          </button>
        </div>
      </section>

      <section style={{ marginTop: 16 }}>
        <h2>{ui.statusTitle}</h2>
        <div>{status}</div>
      </section>

      {asyncJobs.length > 0 && (
        <section style={{ marginTop: 16 }}>
          <h2>Async jobs</h2>
          {asyncJobs.map((j) => (
            <div key={j.job_id} style={{ marginBottom: 10 }}>
              <div>
                <strong>file:</strong> {j.filename}
              </div>
              <div>
                <strong>parser:</strong> {j.parser}
              </div>
              <div>
                <strong>status:</strong> {j.status}
              </div>
              {j.error ? (
                <div style={{ color: "#b00020" }}>
                  <strong>{ui.errorPrefix}:</strong> {j.error}
                </div>
              ) : null}
            </div>
          ))}
        </section>
      )}

      {extractResults.length > 0 && (
        <section style={{ marginTop: 16 }}>
          <h2>{ui.extractResultTitle}</h2>
          {extractResults.map((item) => (
            <div key={`${item.filename}-${item.sha256 ?? "error"}`} style={{ marginBottom: 14 }}>
              <div><strong>file:</strong> {item.filename}</div>
              <div><strong>parser:</strong> {item.parser ?? parser}</div>
              {item.error ? (
                <div style={{ color: "#b00020" }}><strong>{ui.errorPrefix}:</strong> {item.error}</div>
              ) : (
                <>
                  <div>{ui.sha256Label}: {item.sha256}</div>
                  <div>{ui.cachedLabel}: {String(item.cached)}</div>
                  {item.pages && item.pages.length > 0 ? (
                    <div>
                      {item.pages.map((p) => (
                        <details key={p.page} style={{ marginBottom: 10 }}>
                          <summary style={{ cursor: "pointer" }}>Page {p.page}</summary>
                          <pre
                            style={{
                              whiteSpace: "pre-wrap",
                              background: "#f6f6f6",
                              padding: 12,
                              borderRadius: 8,
                              maxHeight: 220,
                              overflow: "auto",
                            }}
                          >
                            {p.content}
                          </pre>
                        </details>
                      ))}
                    </div>
                  ) : (
                    <pre
                      style={{
                        whiteSpace: "pre-wrap",
                        background: "#f6f6f6",
                        padding: 12,
                        borderRadius: 8,
                        maxHeight: 220,
                        overflow: "auto",
                      }}
                    >
                      {item.text}
                    </pre>
                  )}
                  {item.summary && item.summary.trim() ? (
                    <details style={{ marginTop: 12 }}>
                      <summary style={{ cursor: "pointer" }}>Summary</summary>
                      <pre
                        style={{
                          whiteSpace: "pre-wrap",
                          background: "#f6f6f6",
                          padding: 12,
                          borderRadius: 8,
                          maxHeight: 220,
                          overflow: "auto",
                        }}
                      >
                        {item.summary}
                      </pre>
                    </details>
                  ) : null}
                </>
              )}
            </div>
          ))}
        </section>
      )}

      {answer && (
        <section style={{ marginTop: 16 }}>
          <h2>{ui.geminiAnswerTitle}</h2>
          <pre style={{ whiteSpace: "pre-wrap", background: "#f6f6f6", padding: 12, borderRadius: 8 }}>
            {answer}
          </pre>
        </section>
      )}

      <footer
        style={{
          marginTop: 48,
          paddingTop: 16,
          borderTop: "1px solid #ddd",
          fontSize: 13,
          color: "#666",
          textAlign: "center",
          lineHeight: 1.5,
        }}
      >
        <strong>{APP_META.name}</strong> {APP_META.version} · {APP_META.releaseDate} · Code author:{" "}
        {APP_META.codeAuthor}
      </footer>
    </div>
  );
}

