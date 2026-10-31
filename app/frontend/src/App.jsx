import {
  Plane,
  Languages,
  ChevronDown,
  ArrowLeft,
  ArrowRight,
  FileText,
  Clock,
  RotateCcw,
} from "lucide-react";

import { useState, useEffect } from "react";
import LanguageButton from "./components/LanguageButton";
import FileUploader from "./components/FileUploader";
import { createPhrasebook, getPhrasebookStatus } from "./api/phrasebook";
import JobCard from "./components/JobCard";

function App() {
  const [targetLanguage, setTargetLanguage] = useState("");
  const [uploadedFiles, setUploadedFiles] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // Each selected file has its own ID, File object and custom phrasebook name.
  const [phrasebookNames, setPhrasebookNames] = useState({});

  // Session-only job history.
  const [jobs, setJobs] = useState(() => {
    try {
      return JSON.parse(sessionStorage.getItem("wayword-jobs") || "[]");
    } catch {
      return [];
    }
  });

  // Save job history whenever it changes.
  useEffect(() => {
    try {
      sessionStorage.setItem("wayword-jobs", JSON.stringify(jobs));
    } catch (err) {
      console.error("Failed to save job history:", err);
    }
  }, [jobs]);

  // Poll active jobs for status updates.
  useEffect(() => {
    const activeJobs = jobs.filter((job) =>
      ["PENDING", "PROCESSING", "RETRYING"].includes(job.jobStatus),
    );

    if (activeJobs.length === 0) return;

    let cancelled = false;

    const pollJobs = async () => {
      const updates = await Promise.all(
        activeJobs.map(async (job) => {
          try {
            const latest = await getPhrasebookStatus(job.jobId);

            return {
              jobId: job.jobId,
              ...latest,
            };
          } catch (err) {
            console.error(`Failed to check job ${job.jobId}:`, err);

            return null;
          }
        }),
      );

      if (cancelled) return;

      const validUpdates = updates.filter(Boolean);

      if (validUpdates.length > 0) {
        setJobs((current) =>
          current.map((job) => {
            const latest = validUpdates.find(
              (item) => item.jobId === job.jobId,
            );

            return latest ? { ...job, ...latest } : job;
          }),
        );
      }
    };

    pollJobs();

    const interval = setInterval(pollJobs, 5000);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [jobs]);

  // Scroll to a page section.
  const scrollToSection = (id) => {
    document.getElementById(id)?.scrollIntoView({
      behavior: "smooth",
    });
  };

  // Receive files from FileUploader and assign each one a unique ID.
  const handleChildFiles = (filesReceived) => {
    const files = Array.from(filesReceived || []);

    // Match existing files so their IDs and custom names are preserved.
    const updatedFiles = files.map((file) => {
      const existingEntry = uploadedFiles.find(
        ({ file: existingFile }) =>
          existingFile.name === file.name &&
          existingFile.size === file.size &&
          existingFile.lastModified === file.lastModified
      );

      return existingEntry || {
        id: crypto.randomUUID(),
        file,
      };
    });

    setUploadedFiles(updatedFiles);

    // Keep names only for files that are still selected.
    setPhrasebookNames((currentNames) => {
      const updatedNames = {};

      updatedFiles.forEach(({ id, file }) => {
        updatedNames[id] =
          currentNames[id] ?? file.name.replace(/\.txt$/i, "");
      });

      return updatedNames;
    });

    setError("");
  };

  // Submit one independent phrasebook job per selected file.
  const handleSubmit = async () => {
    if (loading) return;

    if (!targetLanguage) {
      setError("Please select a target language first.");
      return;
    }

    if (uploadedFiles.length === 0) {
      setError("Please upload at least one .txt file.");
      return;
    }

    setLoading(true);
    setError("");

    try {
      // Each file creates its own API request and job.
      const results = await Promise.allSettled(
        uploadedFiles.map(async ({ id, file }) => {
          const content = await file.text();

          const phrases = content
            .split(/\r?\n/)
            .map((phrase) => phrase.trim())
            .filter(Boolean);

          if (phrases.length === 0) {
            throw new Error(`${file.name} contains no phrases.`);
          }

          const phrasebookName =
            phrasebookNames[id]?.trim() || file.name.replace(/\.txt$/i, "");

          const result = await createPhrasebook(
            phrases,
            targetLanguage,
            phrasebookName,
          );

          if (!result.jobId) {
            throw new Error("The server did not return a job ID.");
          }

          return {
            jobId: result.jobId,
            jobStatus: result.jobStatus || "PENDING",
            targetLanguage,
            phrasebookName,
            sourceFile: file.name,
            downloadUrl: result.downloadUrl || null,
            submittedAt: new Date().toISOString(),
          };
        }),
      );

      const successfulJobs = results
        .filter((result) => result.status === "fulfilled")
        .map((result) => result.value);

      const failedFiles = results
        .map((result, index) => ({
          result,
          file: uploadedFiles[index].file,
        }))
        .filter(({ result }) => result.status === "rejected");

      // Keep every successfully created job in session history.
      if (successfulJobs.length > 0) {
        setJobs((current) => [...successfulJobs, ...current]);
      }

      if (failedFiles.length > 0) {
        const details = failedFiles.map(({ result, file }) => {
          const reason = result.reason;

          return `${file.name}: ${reason?.message || "Submission failed"}`;
        });

        setError(
          `${successfulJobs.length} of ${uploadedFiles.length} ` +
            `phrasebooks submitted successfully.\n` +
            `Failed files:\n${details.join("\n")}`,
        );
      } else {
        setError("");
      }
    } catch (err) {
      setError(err.message || "Failed to submit your phrasebooks.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="h-screen w-full snap-y snap-mandatory overflow-y-auto bg-[#F7F3EA] text-[#171A21]">
      {/* Landing page */}
      <section
        id="home"
        className="flex min-h-screen snap-start flex-col items-center justify-center gap-6 p-6 sm:p-10"
      >
        <h1 className="text-6xl font-bold sm:text-7xl">Wayword</h1>

        <div className="flex gap-3">
          <Plane />
          <Languages />
        </div>

        <div className="flex w-full max-w-3xl flex-col gap-6 text-center">
          <p className="uppercase tracking-[0.3em] opacity-60">
            Stop studying the same generic phrases
          </p>

          <p>
            Wayword allows you to generate a custom phrasebook for your specific
            travel needs, equipped with accurate translation from English,
            pronunciation, and context for every phrase.
          </p>

          <button
            type="button"
            onClick={() => scrollToSection("setup")}
            className="flex flex-col items-center justify-center transition duration-300 hover:scale-105"
          >
            <span className="font-semibold">Click here to get started</span>
            <ChevronDown />
          </button>
        </div>
      </section>

      {/* Step 1: Language selection */}
      <section
        id="setup"
        className="relative flex min-h-screen snap-start flex-col items-center justify-center gap-10 p-6 sm:p-10"
      >
        <button
          type="button"
          onClick={() => scrollToSection("home")}
          className="absolute left-6 top-6 flex items-center gap-2 opacity-60 transition hover:opacity-100 sm:left-10 sm:top-10"
        >
          <ArrowLeft size={20} />
          Back
        </button>

        <button
          type="button"
          onClick={() => scrollToSection("add-phrases")}
          className="absolute right-6 top-6 flex items-center gap-2 opacity-60 transition hover:opacity-100 sm:right-10 sm:top-10"
        >
          Next
          <ArrowRight size={20} />
        </button>

        <div className="flex flex-col items-center gap-3 text-center">
          <p className="text-sm uppercase tracking-[0.3em] opacity-60">
            Step 01
          </p>

          <h2 className="text-4xl font-bold md:text-5xl">
            Choose your language
          </h2>

          <p className="opacity-70">Where are you heading?</p>
        </div>

        <div className="grid grid-cols-2 gap-5 sm:grid-cols-3">
          {[
            ["Chinese", "cn"],
            ["Japanese", "jp"],
            ["Korean", "kr"],
            ["Thai", "th"],
            ["French", "fr"],
            ["Spanish", "es"],
          ].map(([language, countryCode]) => (
            <div key={language} onClick={() => setTargetLanguage(language)}>
              <LanguageButton
                language={language}
                countryCode={countryCode}
                selected={targetLanguage === language}
              />
            </div>
          ))}
        </div>

        {targetLanguage && (
          <p className="text-sm opacity-70">
            Selected language: <strong>{targetLanguage}</strong>
          </p>
        )}
      </section>

      {/* Step 2: Upload and name phrasebooks */}
      <section
        id="add-phrases"
        className="relative flex min-h-screen snap-start flex-col items-center justify-center gap-8 p-6 sm:p-10"
      >
        <button
          type="button"
          onClick={() => scrollToSection("setup")}
          className="absolute left-6 top-6 flex items-center gap-2 opacity-60 transition hover:opacity-100 sm:left-10 sm:top-10"
        >
          <ArrowLeft size={20} />
          Back
        </button>

        <button
          type="button"
          onClick={() => scrollToSection("generate-pdf")}
          className="absolute right-6 top-6 flex items-center gap-2 opacity-60 transition hover:opacity-100 sm:right-10 sm:top-10"
        >
          Next
          <ArrowRight size={20} />
        </button>

        <div className="flex flex-col items-center gap-3 text-center">
          <p className="text-sm uppercase tracking-[0.3em] opacity-60">
            Step 02
          </p>

          <h2 className="text-4xl font-bold md:text-5xl">Add your phrases</h2>

          <p className="opacity-70">
            Upload multiple text files and customise each phrasebook name.
          </p>
        </div>

        <FileUploader onFilesChange={handleChildFiles} />

        {uploadedFiles.length > 0 && (
          <div className="w-full max-w-xl space-y-3">
            <p className="text-sm opacity-70">
              {uploadedFiles.length} file
              {uploadedFiles.length === 1 ? "" : "s"} selected. Edit your
              phrasebook names below.
            </p>

            {uploadedFiles.map(({ id, file }) => (
              <div
                key={id}
                className="flex flex-col gap-3 rounded-xl border border-[#E6DCCB] bg-white p-4 sm:flex-row sm:items-center"
              >
                <div className="flex min-w-0 flex-1 items-center gap-3">
                  <FileText size={22} className="shrink-0 text-[#287D78]" />

                  <div className="min-w-0">
                    <p className="truncate font-medium">{file.name}</p>

                    <p className="text-xs text-gray-500">
                      {(file.size / 1024).toFixed(1)} KB
                    </p>
                  </div>
                </div>

                <div className="w-full sm:w-56">
                  <label
                    htmlFor={`phrasebook-name-${id}`}
                    className="mb-1 block text-xs font-medium text-gray-600"
                  >
                    Phrasebook name
                  </label>

                  <input
                    id={`phrasebook-name-${id}`}
                    type="text"
                    maxLength={100}
                    value={phrasebookNames[id] ?? ""}
                    onChange={(event) => {
                      const name = event.target.value;

                      setPhrasebookNames((current) => ({
                        ...current,
                        [id]: name,
                      }));
                    }}
                    placeholder="e.g. Seoul Food Guide"
                    className="w-full rounded-lg border border-[#E6DCCB] px-3 py-2 text-sm outline-none transition focus:border-[#287D78]"
                  />
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Step 3: Generate PDFs and track jobs */}
      <section
        id="generate-pdf"
        className="relative flex min-h-screen snap-start flex-col items-center justify-center gap-8 p-6 sm:p-10"
      >
        <button
          type="button"
          onClick={() => scrollToSection("add-phrases")}
          className="absolute left-6 top-6 flex items-center gap-2 opacity-60 transition hover:opacity-100 sm:left-10 sm:top-10"
        >
          <ArrowLeft size={20} />
          Back
        </button>

        <button
          type="button"
          onClick={() => {
            setUploadedFiles([]);
            setPhrasebookNames({});
            setError("");
            scrollToSection("setup");
          }}
          className="absolute right-6 top-6 flex items-center gap-2 opacity-60 transition hover:opacity-100 sm:right-10 sm:top-10"
        >
          <RotateCcw size={20} />
          Submit more
        </button>

        <div className="flex w-full max-w-2xl flex-col items-center gap-3 text-center">
          <p className="text-sm uppercase tracking-[0.3em] opacity-60">
            Step 03
          </p>

          <h2 className="text-4xl font-bold md:text-5xl">Generate your PDFs</h2>

          <p className="opacity-70">
            Submit your phrasebooks and track each job below.
          </p>

          <p className="text-sm text-gray-500">
            {uploadedFiles.length} phrasebook
            {uploadedFiles.length === 1 ? "" : "s"} ready to submit
          </p>

          <button
            type="button"
            onClick={handleSubmit}
            disabled={loading}
            className="mt-3 w-full rounded-lg bg-[#287D78] p-4 font-bold text-white shadow-md transition duration-300 hover:scale-[1.02] disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:scale-100"
          >
            {loading ? "Submitting phrasebooks..." : "Generate phrasebooks"}
          </button>

          {error && (
            <p
              role="alert"
              aria-live="polite"
              className="w-full whitespace-pre-line text-sm text-red-600"
            >
              {error}
            </p>
          )}
        </div>

        {/* Job history */}
        <div className="w-full max-w-2xl overflow-hidden rounded-xl border border-[#E6DCCB] bg-white shadow-sm">
          <div className="flex items-center justify-between border-b border-[#E6DCCB] px-5 py-4">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[#F3EBDD]">
                <FileText size={20} className="text-[#287D78]" />
              </div>

              <div className="text-left">
                <h3 className="font-semibold">Your phrasebooks</h3>

                <p className="text-sm text-gray-500">
                  Jobs submitted in this session
                </p>
              </div>
            </div>

            <span className="rounded-full bg-[#F3EBDD] px-3 py-1 text-sm font-semibold text-[#287D78]">
              {jobs.length}
            </span>
          </div>

          <div className="max-h-72 space-y-3 overflow-y-auto p-4 sm:p-5">
            {jobs.length > 0 ? (
              jobs.map((job) => (
                <div key={job.jobId} className="space-y-1">
                  {job.phrasebookName && (
                    <p className="truncate px-1 text-sm font-semibold">
                      {job.phrasebookName}
                    </p>
                  )}

                  {job.sourceFile && (
                    <p className="truncate px-1 text-xs text-gray-500">
                      From: {job.sourceFile}
                    </p>
                  )}

                  <JobCard
                    jobId={job.jobId}
                    jobStatus={job.jobStatus}
                    targetLanguage={job.targetLanguage}
                    downloadUrl={job.downloadUrl}
                  />
                </div>
              ))
            ) : (
              <div className="flex flex-col items-center gap-3 py-8 text-center">
                <div className="flex h-12 w-12 items-center justify-center rounded-full bg-[#F2F3F7]">
                  <Clock size={22} className="text-gray-400" />
                </div>

                <div>
                  <p className="font-medium">No phrasebooks yet</p>

                  <p className="mt-1 text-sm text-gray-500">
                    Your submitted phrasebooks will appear here.
                  </p>
                </div>
              </div>
            )}
          </div>
        </div>
      </section>
    </main>
  );
}

export default App;
