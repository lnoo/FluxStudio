import { useState, useEffect } from "react";
import { Button, Card, Chip, ProgressBar, Tooltip } from "@heroui/react";
import { ArrowDownToLine, ArrowRotateLeft, CircleStop, TrashBin } from "@gravity-ui/icons";
import { useStore } from "../store/appStore";
import { downloadUrl, imageUrl, type TaskStatus } from "../api/client";
import { CopyButton } from "./CopyButton";
import { ImageLightbox } from "./ImageLightbox";

const statusColor: Record<TaskStatus["status"], "accent" | "danger" | "default" | "success"> = {
  queued: "default",
  running: "accent",
  completed: "success",
  failed: "danger",
  cancelled: "default",
};

const statusLabel: Record<TaskStatus["status"], string> = {
  queued: "排队中",
  running: "生成中",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

type ConfirmAction = "cancel" | "retry" | "delete";

interface ConfirmState {
  action: ConfirmAction;
  taskId: string;
  title: string;
  message: string;
}

function formatEta(
  status: TaskStatus["status"],
  progress: number,
  steps: number,
  avgSecPerStep?: number | null
): string | null {
  // Jenkins strategy: If no historical completed task step speed exists, do NOT estimate!
  if (avgSecPerStep == null || avgSecPerStep <= 0) {
    return null;
  }

  const stepCount = steps || 30;
  if (status === "queued") {
    const totalSecs = Math.round(stepCount * avgSecPerStep);
    return `等待排队 · 预估耗时 ${totalSecs}s`;
  }
  const remainingPct = Math.max(0, 100 - progress);
  const totalSeconds = stepCount * avgSecPerStep;
  const remainingSeconds = Math.round((remainingPct / 100) * totalSeconds);

  if (remainingSeconds <= 0) return "即将完成...";
  if (remainingSeconds < 60) return `预估剩余 ${remainingSeconds} 秒`;
  const mins = Math.floor(remainingSeconds / 60);
  const secs = remainingSeconds % 60;
  return secs > 0 ? `预估剩余 ${mins} 分 ${secs} 秒` : `预估剩余 ${mins} 分钟`;
}

export function TaskList() {
  const tasks = useStore((s) => s.tasks);
  const refresh = useStore((s) => s.refreshTasks);
  const cancel = useStore((s) => s.cancel);
  const retry = useStore((s) => s.retry);
  const remove = useStore((s) => s.remove);

  const [confirmState, setConfirmState] = useState<ConfirmState | null>(null);
  const [previewSrc, setPreviewSrc] = useState<string | null>(null);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleConfirmAction = async () => {
    if (!confirmState) return;
    const { action, taskId } = confirmState;
    setConfirmState(null);
    if (action === "cancel") await cancel(taskId);
    else if (action === "retry") await retry(taskId);
    else if (action === "delete") await remove(taskId);
  };

  return (
    <>
      <Card>
        <Card.Content className="gap-3">
          <h2 className="text-lg font-semibold">任务列表</h2>
          {tasks.length === 0 && <p className="text-sm text-muted">暂无任务。</p>}
          <div className="flex flex-col gap-3">
            {tasks.map((t) => (
              <div key={t.task_id} className="rounded-lg border border-border p-3">
                <div className="flex items-center justify-between">
                  <Chip color={statusColor[t.status]} variant="soft" size="sm">
                    {statusLabel[t.status]}
                  </Chip>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-muted">
                      {t.task_id.slice(0, 8)}
                    </span>
                    {(t.status === "failed" || t.status === "cancelled" || t.status === "completed") && (
                      <Tooltip.Root delay={400}>
                        <Button
                          size="sm"
                          variant="secondary"
                          isIconOnly
                          aria-label="重试任务"
                          onPress={() =>
                            setConfirmState({
                              action: "retry",
                              taskId: t.task_id,
                              title: "确认重试任务？",
                              message: `确定要重新生成任务 ${t.task_id.slice(0, 8)} 吗？任务将被重新推入队列。`,
                            })
                          }
                        >
                          <ArrowRotateLeft />
                        </Button>
                        <Tooltip.Content>重试任务</Tooltip.Content>
                      </Tooltip.Root>
                    )}
                    {t.status === "completed" && t.output_image && (
                      <a href={downloadUrl(t.output_image, `flux-${t.task_id.slice(0, 8)}`)}>
                        <Tooltip.Root delay={400}>
                          <Button size="sm" variant="secondary" isIconOnly aria-label="下载图片">
                            <ArrowDownToLine />
                          </Button>
                          <Tooltip.Content>下载图片</Tooltip.Content>
                        </Tooltip.Root>
                      </a>
                    )}
                    <Tooltip.Root delay={400}>
                      <Button
                        size="sm"
                        variant="secondary"
                        isIconOnly
                        aria-label="删除任务"
                        onPress={() =>
                          setConfirmState({
                            action: "delete",
                            taskId: t.task_id,
                            title: "确认删除任务？",
                            message: `确定要删除任务 ${t.task_id.slice(0, 8)} 吗？删除后任务及相关数据将被永久移除。`,
                          })
                        }
                      >
                        <TrashBin />
                      </Button>
                      <Tooltip.Content>删除任务</Tooltip.Content>
                    </Tooltip.Root>
                  </div>
                </div>

                {(t.status === "queued" || t.status === "running") && (
                  <div className="mt-2.5 flex flex-col gap-1">
                    <div className="flex items-center gap-2">
                      <div className="w-full">
                        <div className="flex items-center justify-between text-xs p-1 tabular-nums">
                          <span className="font-semibold text-accent">{t.progress}%</span>
                          {(() => {
                            const etaText = formatEta(t.status, t.progress, t.params.steps || 30, t.avg_sec_per_step);
                            return etaText ? (
                              <span className="text-muted font-normal">{etaText}</span>
                            ) : null;
                          })()}
                        </div>
                        <ProgressBar.Root value={t.progress} size="sm" className="flex-1">
                          <ProgressBar.Track>
                            <ProgressBar.Fill />
                          </ProgressBar.Track>
                        </ProgressBar.Root>
                      </div>
                      <Tooltip.Root delay={400}>
                        <Button
                          size="sm"
                          className="shrink-0"
                          variant="danger-soft"
                          isIconOnly
                          aria-label="取消任务"
                          onPress={() =>
                            setConfirmState({
                              action: "cancel",
                              taskId: t.task_id,
                              title: "确认取消任务？",
                              message: `确定要取消任务 ${t.task_id.slice(0, 8)} 吗？生成进度将被中止。`,
                            })
                          }
                        >
                          <CircleStop />
                        </Button>
                        <Tooltip.Content>取消任务</Tooltip.Content>
                      </Tooltip.Root>
                    </div>
                  </div>
                )}

                {t.params.input_images.length > 0 && (
                  <div className="mt-2 flex gap-1.5">
                    {t.params.input_images.map((fn) => (
                      <img
                        key={fn}
                        src={imageUrl(fn)}
                        loading="lazy"
                        alt="输入图片"
                        onClick={() => setPreviewSrc(imageUrl(fn))}
                        className="h-14 w-14 cursor-pointer rounded border border-border object-cover"
                      />
                    ))}
                  </div>
                )}

                {t.params.prompt && (
                  <div className="group mt-2 flex items-center gap-1">
                    <p
                      className="line-clamp-2 min-w-0 text-sm text-foreground"
                    >
                      {t.params.prompt}
                    </p>
                    <CopyButton
                      value={t.params.prompt}
                      label="复制 prompt"
                      size="sm"
                      variant="ghost"
                      className="shrink-0 opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
                    />
                  </div>
                )}

                <p className="mt-1 text-xs text-muted">
                  步数：{t.params.steps}
                  {t.params.guidance != null && ` · 引导强度：${t.params.guidance}`}
                  {t.params.width != null && t.params.height != null &&
                    ` · 尺寸：${t.params.width}×${t.params.height}`}
                  {t.duration_seconds != null && ` · 耗时：${t.duration_seconds}s`}
                </p>

                {t.status === "failed" && t.error && (
                  <p className="mt-2 text-xs text-danger">{t.error}</p>
                )}

                {t.status === "completed" && t.output_image && (
                  <img
                    src={imageUrl(t.output_image)}
                    loading="lazy"
                    alt="输出图片"
                    onClick={() => setPreviewSrc(imageUrl(t.output_image!))}
                    className="mt-2 w-full cursor-pointer rounded object-contain"
                  />
                )}
              </div>
            ))}
          </div>
        </Card.Content>
      </Card>

      {previewSrc && (
        <ImageLightbox
          src={previewSrc}
          onClose={() => setPreviewSrc(null)}
        />
      )}

      {confirmState && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-xs p-4">
          <div className="w-full max-w-sm space-y-4 rounded-xl border border-border bg-background p-5 shadow-2xl">
            <h3 className="text-lg font-semibold text-foreground">{confirmState.title}</h3>
            <p className="text-sm text-muted">{confirmState.message}</p>
            <div className="flex justify-end gap-3 pt-2">
              <Button
                size="sm"
                variant="secondary"
                onPress={() => setConfirmState(null)}
              >
                取消
              </Button>
              <Button
                size="sm"
                variant={confirmState.action === "retry" ? "primary" : "danger"}
                onPress={() => void handleConfirmAction()}
              >
                确认
              </Button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}