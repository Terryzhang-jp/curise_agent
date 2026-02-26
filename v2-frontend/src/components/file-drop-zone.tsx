"use client";

import { useCallback, useMemo, useState, useRef } from "react";
import { cn } from "@/lib/utils";
import { Upload } from "lucide-react";

interface FileDropZoneProps {
  onFile: (file: File) => void;
  accept?: string;
  label?: string;
  disabled?: boolean;
}

export function FileDropZone({
  onFile,
  accept = ".xlsx,.pdf",
  label = "拖放文件到此处，或点击选择",
  disabled = false,
}: FileDropZoneProps) {
  const [isDragOver, setIsDragOver] = useState(false);
  const [fileName, setFileName] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const allowedExtensions = useMemo(
    () => accept.split(",").map((s) => s.trim().toLowerCase()),
    [accept]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragOver(false);
      if (disabled) return;
      const file = e.dataTransfer.files[0];
      if (
        file &&
        allowedExtensions.some((ext) => file.name.toLowerCase().endsWith(ext))
      ) {
        setFileName(file.name);
        onFile(file);
      }
    },
    [onFile, allowedExtensions, disabled]
  );

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) {
        setFileName(file.name);
        onFile(file);
      }
    },
    [onFile]
  );

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setIsDragOver(true);
      }}
      onDragLeave={() => setIsDragOver(false)}
      onDrop={handleDrop}
      onClick={() => !disabled && inputRef.current?.click()}
      className={cn(
        "border-2 border-dashed rounded-xl p-8 text-center transition-colors",
        isDragOver
          ? "border-primary bg-primary/5"
          : "border-border hover:border-muted-foreground",
        disabled ? "opacity-50 cursor-not-allowed" : "cursor-pointer"
      )}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        onChange={handleChange}
        className="hidden"
        disabled={disabled}
      />
      <Upload className="h-8 w-8 text-muted-foreground mx-auto mb-3" />
      {fileName ? (
        <div>
          <div className="text-sm font-medium">{fileName}</div>
          <div className="text-xs text-muted-foreground mt-1">点击重新选择</div>
        </div>
      ) : (
        <div>
          <div className="text-sm text-muted-foreground">{label}</div>
          <div className="text-xs text-muted-foreground/70 mt-1">
            支持 {accept.replace(/\./g, "").replace(/,/g, ", ").toUpperCase()} 格式
          </div>
        </div>
      )}
    </div>
  );
}
