import { useCallback } from "react";
import { Button, Card, Chip, CloseButton } from "@heroui/react";
import { useStore } from "../store/appStore";

export function UploadPanel() {
  const pendingFiles = useStore((s) => s.pendingFiles);
  const addFiles = useStore((s) => s.addFiles);
  const removeFile = useStore((s) => s.removeFile);

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      if (e.dataTransfer.files?.length) addFiles(e.dataTransfer.files);
    },
    [addFiles]
  );

  return (
    <Card>
      <Card.Content className="gap-3">
        <h2 className="text-lg font-semibold">输入图片</h2>
        <label
          onDragOver={(e) => e.preventDefault()}
          onDrop={onDrop}
          className="flex h-32 cursor-pointer items-center justify-center rounded-lg border-2 border-dashed border-border hover:border-accent"
        >
          <input
            type="file"
            multiple
            accept="image/*"
            className="hidden"
            onChange={(e) => e.target.files && addFiles(e.target.files)}
          />
          <span className="text-sm text-muted">拖拽或点击上传图片</span>
        </label>

        <div className="grid grid-cols-4 gap-2">
          {pendingFiles.map((f, idx) => (
            <div
              key={idx}
              className="group relative aspect-square overflow-hidden rounded-lg border border-border bg-background"
            >
              <img
                src={f.previewUrl}
                alt={f.file.name}
                className="h-full w-full object-cover"
              />
              <CloseButton
                className="absolute right-1 top-1 w-5 h-5 opacity-0 shadow-sm transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
                onClick={() => removeFile(idx)}
                aria-label={`移除 ${f.file.name}`} />
            </div>
          ))}
        </div>

        {pendingFiles.length > 0 && (
          <Chip color="accent" variant="soft">
            {pendingFiles.length} 张图片已就绪
          </Chip>
        )}
      </Card.Content>
    </Card>
  );
}