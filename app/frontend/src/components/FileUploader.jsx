
import { useState, useRef } from "react";
import { LucideUpload, X, FileText } from "lucide-react";

function FileUploader({ onFilesChange }) {
  const [files, setFiles] = useState([]);
  const [isDragging, setIsDragging] = useState(false);
  const [error, setError] = useState("");
  const fileInputRef = useRef(null);

  const handleFiles = (selectedFiles) => {
    const selected = Array.from(selectedFiles || []);

    const textFiles = selected.filter((file) =>
      file.name.toLowerCase().endsWith(".txt")
    );

    const invalidCount = selected.length - textFiles.length;

    setError(
      invalidCount > 0
        ? `${invalidCount} unsupported file(s) skipped. Only .txt files are accepted.`
        : ""
    );

    if (textFiles.length === 0) return;

    // Append new files without adding duplicates.
    setFiles((current) => {
      const existingKeys = new Set(
        current.map((file) => `${file.name}-${file.size}-${file.lastModified}`)
      );

      const newFiles = textFiles.filter(
        (file) =>
          !existingKeys.has(
            `${file.name}-${file.size}-${file.lastModified}`
          )
      );

      const updated = [...current, ...newFiles];

      onFilesChange?.(updated);

      return updated;
    });
  };

  const removeFile = (indexToRemove) => {
    setFiles((current) => {
      const updated = current.filter(
        (_, index) => index !== indexToRemove
      );

      onFilesChange?.(updated);
      return updated;
    });

    setError("");
  };

  const clearFiles = () => {
    setFiles([]);
    setError("");
    onFilesChange?.([]);

    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setIsDragging(false);
    handleFiles(e.dataTransfer.files);
  };

  const handleFileSelect = (e) => {
    handleFiles(e.target.files);

    // Allow selecting the same file again.
    e.target.value = "";
  };

  return (
    <div className="flex w-full max-w-xl flex-col items-center gap-3">
      <input
        ref={fileInputRef}
        type="file"
        accept=".txt,text/plain"
        multiple
        onChange={handleFileSelect}
        className="hidden"
      />

      <button
        type="button"
        onClick={() => fileInputRef.current?.click()}
        onDrop={handleDrop}
        onDragOver={(e) => {
          e.preventDefault();
          setIsDragging(true);
        }}
        onDragEnter={(e) => {
          e.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={(e) => {
          if (!e.currentTarget.contains(e.relatedTarget)) {
            setIsDragging(false);
          }
        }}
        className={`flex w-full cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed p-6 text-center transition ${
          isDragging
            ? "border-[#287D78] bg-[#FAF7F0]"
            : "border-[#E6DCCB] bg-white hover:border-[#287D78] hover:bg-[#FAF7F0]"
        }`}
      >
        <LucideUpload size={32} className="text-[#287D78]" />

        <p className="font-medium">
          Click to browse or drag and drop text files
        </p>

        <p className="text-sm opacity-60">
          Select multiple .txt files or add more later
        </p>
      </button>

      {error && (
        <p role="alert" className="w-full text-sm text-red-600">
          {error}
        </p>
      )}

      {files.length > 0 && (
        <div className="w-full rounded-xl border border-[#E6DCCB] bg-white p-4">
          <div className="mb-3 flex items-center justify-between gap-3">
            <p className="font-semibold">
              Selected files ({files.length})
            </p>

            <button
              type="button"
              onClick={clearFiles}
              className="text-sm text-gray-500 transition hover:text-red-600"
            >
              Clear all
            </button>
          </div>

          <ul className="space-y-2">
            {files.map((file, index) => (
              <li
                key={`${file.name}-${file.size}-${file.lastModified}-${index}`}
                className="flex items-center gap-3 rounded-lg bg-[#FAF7F0] p-3"
              >
                <FileText
                  size={20}
                  className="shrink-0 text-[#287D78]"
                />

                <span className="min-w-0 flex-1 truncate text-sm">
                  {file.name}
                </span>

                <button
                  type="button"
                  aria-label={`Remove ${file.name}`}
                  onClick={() => removeFile(index)}
                  className="shrink-0 rounded-md p-1 text-gray-400 transition hover:bg-white hover:text-red-600"
                >
                  <X size={18} />
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <span className="text-sm opacity-60">
        .txt files accepted only.
      </span>
    </div>
  );
}

export default FileUploader;
