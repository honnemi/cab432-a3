import { FileText, Download } from "lucide-react";

const statusStyles = {
  PENDING: "bg-amber-100 text-amber-700",
  PROCESSING: "bg-blue-100 text-blue-700",
  COMPLETED: "bg-green-100 text-green-700",
  FAILED: "bg-red-100 text-red-700",
};

export default function JobCard({
  jobId,
  jobStatus,
  targetLanguage,
  downloadUrl,
}) {
  const status = (jobStatus || "PENDING").toUpperCase();
  const badgeStyle =
    statusStyles[status] || "bg-gray-100 text-gray-700";

  const isCompleted = status === "COMPLETED";
  const isFailed = status === "FAILED";

  return (
    <div className="flex w-full items-center gap-3 rounded-lg border border-[#E6DCCB] bg-white p-4 transition duration-200 hover:border-[#287D78] hover:shadow-sm">
      <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-[#F3EBDD]">
        <FileText size={22} className="text-[#287D78]" />
      </div>

      <div className="min-w-0 flex-1 text-left">
        <p className="truncate font-semibold text-[#171A21]">
          {targetLanguage || "Phrasebook"} phrasebook
        </p>
        <p className="mt-1 truncate text-xs text-gray-500" title={jobId}>
          Job ID: {jobId}
        </p>
      </div>

      <div className="flex shrink-0 flex-col items-end gap-2">
        <span
          className={`rounded-full px-2.5 py-1 text-xs font-semibold ${badgeStyle}`}
        >
          {status.charAt(0) + status.slice(1).toLowerCase()}
        </span>

        {isCompleted && downloadUrl && (
          <a
            href={downloadUrl}
            download
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1.5 rounded-md bg-[#287D78] px-3 py-2 text-xs font-semibold text-white transition duration-300 hover:scale-[1.02]"
          >
            <Download size={14} />
            Download PDF
          </a>
        )}

        {isCompleted && !downloadUrl && (
          <span className="text-xs text-gray-500">
            PDF link unavailable
          </span>
        )}

        {isFailed && (
          <span className="text-xs text-red-600">
            Generation failed
          </span>
        )}
      </div>
    </div>
  );
}