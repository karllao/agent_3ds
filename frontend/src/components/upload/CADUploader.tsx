import { useCallback, useState } from "react";
import { useDropzone, FileRejection } from "react-dropzone";
import { Upload, FileText, X, CheckCircle2, AlertCircle } from "lucide-react";
import { cn, formatFileSize } from "@/lib/utils";
import type { UploadProgress } from "@/types";

interface CADUploaderProps {
  onFileSelect: (file: File) => void;
  onUpload?: (file: File) => Promise<void>;
  isUploading?: boolean;
  uploadProgress?: UploadProgress | null;
  uploadedFile?: File | null;
  error?: string | null;
  className?: string;
}

const ACCEPTED_TYPES = {
  "application/dxf": [".dxf"],
  "application/dwg": [".dwg"],
  "application/acad": [".dwg"],
  "image/vnd.dwg": [".dwg"],
  "image/x-dwg": [".dwg"],
};

export function CADUploader({
  onFileSelect,
  onUpload,
  isUploading = false,
  uploadProgress = null,
  uploadedFile = null,
  error = null,
  className,
}: CADUploaderProps) {
  const [dragError, setDragError] = useState<string | null>(null);

  const onDrop = useCallback(
    (acceptedFiles: File[], rejectedFiles: FileRejection[]) => {
      setDragError(null);

      if (rejectedFiles.length > 0) {
        setDragError("仅支持 .dxf 或 .dwg 格式的 CAD 文件");
        return;
      }

      if (acceptedFiles.length > 0) {
        const file = acceptedFiles[0];
        onFileSelect(file);
        onUpload?.(file);
      }
    },
    [onFileSelect, onUpload],
  );

  const { getRootProps, getInputProps, isDragActive, isDragReject } =
    useDropzone({
      onDrop,
      accept: ACCEPTED_TYPES,
      maxFiles: 1,
      maxSize: 100 * 1024 * 1024, // 100MB
      disabled: isUploading,
    });

  const displayError = error ?? dragError;

  if (uploadedFile && !isUploading) {
    return (
      <div
        className={cn(
          "flex items-center gap-4 rounded-xl border border-green-500/30 bg-green-500/5 p-4",
          className,
        )}
      >
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-green-500/10">
          <CheckCircle2 className="h-5 w-5 text-green-400" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="truncate text-sm font-medium text-white">
            {uploadedFile.name}
          </p>
          <p className="text-xs text-surface-200/50">
            {formatFileSize(uploadedFile.size)}
          </p>
        </div>
        <button
          onClick={() => onFileSelect(null as unknown as File)}
          className="shrink-0 rounded-lg p-1.5 text-surface-200/40 transition-colors hover:bg-white/5 hover:text-white"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    );
  }

  return (
    <div className={cn("space-y-2", className)}>
      <div
        {...getRootProps()}
        className={cn(
          "relative flex cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed p-8 text-center transition-all duration-200",
          isDragActive && !isDragReject
            ? "border-primary-500 bg-primary-500/5"
            : "border-surface-700 bg-surface-900/50 hover:border-primary-500/50 hover:bg-primary-500/5",
          isDragReject && "border-red-500 bg-red-500/5",
          isUploading && "cursor-not-allowed opacity-60",
        )}
      >
        <input {...getInputProps()} />

        <div
          className={cn(
            "flex h-14 w-14 items-center justify-center rounded-2xl transition-colors",
            isDragActive ? "bg-primary-500/20" : "bg-surface-700/50",
          )}
        >
          <Upload
            className={cn(
              "h-6 w-6 transition-colors",
              isDragActive ? "text-primary-400" : "text-surface-200/40",
            )}
          />
        </div>

        {isUploading ? (
          <div className="w-full space-y-2">
            <p className="text-sm font-medium text-white">正在上传…</p>
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-700">
              <div
                className="h-full rounded-full bg-primary-500 transition-all duration-300"
                style={{ width: `${uploadProgress?.percentage ?? 0}%` }}
              />
            </div>
            <p className="text-xs text-surface-200/50">
              {uploadProgress?.percentage ?? 0}%
            </p>
          </div>
        ) : (
          <>
            <div>
              <p className="text-sm font-medium text-white">
                {isDragActive ? "松开以上传文件" : "拖拽 CAD 文件到此处"}
              </p>
              <p className="mt-1 text-xs text-surface-200/50">
                或点击选择文件 · 支持 .dxf / .dwg · 最大 100MB
              </p>
            </div>

            <div className="flex items-center gap-3">
              <div className="flex items-center gap-1.5 rounded-lg bg-surface-700/50 px-3 py-1.5">
                <FileText className="h-3.5 w-3.5 text-blue-400" />
                <span className="text-xs text-surface-200/60">.dxf</span>
              </div>
              <div className="flex items-center gap-1.5 rounded-lg bg-surface-700/50 px-3 py-1.5">
                <FileText className="h-3.5 w-3.5 text-cyan-400" />
                <span className="text-xs text-surface-200/60">.dwg</span>
              </div>
            </div>
          </>
        )}
      </div>

      {displayError && (
        <div className="flex items-center gap-2 rounded-lg bg-red-500/10 px-3 py-2">
          <AlertCircle className="h-4 w-4 shrink-0 text-red-400" />
          <p className="text-xs text-red-400">{displayError}</p>
        </div>
      )}
    </div>
  );
}
