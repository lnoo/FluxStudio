import { useCallback } from "react";
import { Button, Card, Chip, Input, Label, Slider, TextArea, Tooltip } from "@heroui/react";
import { CircleInfo, ArrowUpFromLine, ArrowUpToLine } from "@gravity-ui/icons";
import { useStore } from "../store/appStore";

function Hint({ text }: { text: string }) {
  return (
    <Tooltip.Root delay={400}>
      <Button isIconOnly variant="ghost">
        <CircleInfo />
      </Button>
      <Tooltip.Content>{text}</Tooltip.Content>
    </Tooltip.Root>
  );
}

export function BatchPanel() {
  const backgrounds = useStore((s) => s.batchBackgrounds);
  const objects = useStore((s) => s.batchObjects);
  const pendingFiles = useStore((s) => s.batchPendingFiles);
  const batchTag = useStore((s) => s.batchTag);
  const params = useStore((s) => s.batchParams);
  const uploading = useStore((s) => s.batchUploading);
  const batchSubmitting = useStore((s) => s.batchSubmitting);
  const batchError = useStore((s) => s.batchError);
  const tasks = useStore((s) => s.tasks);
  const setBatchPendingFiles = useStore((s) => s.setBatchPendingFiles);
  const setBatchTag = useStore((s) => s.setBatchTag);
  const setBatchK = useStore((s) => s.setBatchK);
  const setBatchRounds = useStore((s) => s.setBatchRounds);
  const setBatchPrompt = useStore((s) => s.setBatchPrompt);
  const setBatchSteps = useStore((s) => s.setBatchSteps);
  const setBatchGuidance = useStore((s) => s.setBatchGuidance);
  const setBatchWidth = useStore((s) => s.setBatchWidth);
  const setBatchHeight = useStore((s) => s.setBatchHeight);
  const uploadBatch = useStore((s) => s.uploadBatch);
  const submitBatch = useStore((s) => s.submitBatch);
  const resetBatch = useStore((s) => s.resetBatch);
  const setBatchError = useStore((s) => s.setBatchError);

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      if (e.dataTransfer.files?.length) setBatchPendingFiles(e.dataTransfer.files);
    },
    [setBatchPendingFiles]
  );

  const totalTasks = backgrounds.length * params.rounds;
  const avgSecPerStep = tasks.find((t) => t.avg_sec_per_step != null)?.avg_sec_per_step ?? null;
  const etaMin = avgSecPerStep != null
    ? Math.round((totalTasks * params.steps * avgSecPerStep) / 60)
    : null;

  const validateAndSubmit = async () => {
    if (params.width != null && (params.width < 8 || params.width > 4096)) {
      setBatchError("输出宽度必须介于 8 与 4096 像素之间");
      return;
    }
    if (params.height != null && (params.height < 8 || params.height > 4096)) {
      setBatchError("输出高度必须介于 8 与 4096 像素之间");
      return;
    }
    if (params.steps < 1 || params.steps > 60) {
      setBatchError("生成步数必须介于 1 与 60 之间");
      return;
    }
    setBatchError(null);
    await submitBatch();
  };

  return (
    <Card>
      <Card.Content className="gap-5 p-5">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">批量生成</h2>
          <Button size="sm" variant="secondary" onPress={resetBatch}>
            重置
          </Button>
        </div>

        {/* Role toggle + upload */}
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant={batchTag === "background" ? "primary" : "secondary"}
              onPress={() => setBatchTag("background")}
            >
              背景图
            </Button>
            <Button
              size="sm"
              variant={batchTag === "object" ? "primary" : "secondary"}
              onPress={() => setBatchTag("object")}
            >
              单图物体
            </Button>
            <span className="text-xs text-muted">当前：{batchTag === "background" ? "背景图" : batchTag === "object" ? "单图物体" : "未选择"}</span>
          </div>

          <label
            onDragOver={(e) => e.preventDefault()}
            onDrop={onDrop}
            className="flex h-24 cursor-pointer items-center justify-center rounded-lg border-2 border-dashed border-border hover:border-accent"
          >
            <input
              type="file"
              multiple
              accept="image/*"
              className="hidden"
              onChange={(e) => setBatchPendingFiles(e.target.files)}
            />
            <span className="text-sm text-muted">
              {batchTag
                ? `拖拽或点击选择${batchTag === "background" ? "背景图" : "单图物体"}（可整个文件夹多选）`
                : "先选择上传类型（背景图 / 单图物体）"}
            </span>
          </label>

          <div className="flex flex-wrap items-center gap-2">
            <Chip color="accent" variant="soft">背景 {backgrounds.length} 张</Chip>
            <Chip color="accent" variant="soft">物体 {objects.length} 张</Chip>
            {pendingFiles.length > 0 && (
              <Chip color="warning" variant="soft">待上传 {pendingFiles.length} 张</Chip>
            )}
            {uploading && (
              <Chip color="accent" variant="soft">
                上传中 {uploading.done}/{uploading.total}
              </Chip>
            )}
            <Button
              size="sm"
              variant="primary"
              isDisabled={!batchTag || pendingFiles.length === 0 || uploading != null}
              onPress={uploadBatch}
            >
              <ArrowUpToLine />
              上传{uploading ? "中…" : ""}
            </Button>
          </div>
          <p className="text-xs text-muted">
            支持整个文件夹多选，前端自动分批上传（每批 25 张）。
          </p>
        </div>

        {/* Batch params */}
        <Slider.Root
          aria-label="每张背景融合物体数 K"
          step={1}
          minValue={1}
          maxValue={7}
          value={params.k}
          onChange={(v) => setBatchK(Number(v))}
        >
          <div className="flex w-full items-center justify-between gap-4">
            <div className="flex items-center">
              <Label>每张背景融合物体数 K</Label>
              <Hint text="每张背景图随机抽取 K 个物体进行融合，模型按提示词自然摆放。" />
            </div>
            <Slider.Output className="text-accent text-sm font-medium" />
          </div>
          <Slider.Track>
            <Slider.Fill />
            <Slider.Thumb />
          </Slider.Track>
        </Slider.Root>

        <Slider.Root
          aria-label="每张背景生成变体数"
          step={1}
          minValue={1}
          maxValue={10}
          value={params.rounds}
          onChange={(v) => setBatchRounds(Number(v))}
        >
          <div className="flex w-full items-center justify-between gap-4">
            <div className="flex items-center">
              <Label>每张背景变体数</Label>
              <Hint text="每张背景生成多张变体（每轮重新随机抽样物体组合），用于挑选最优结果。" />
            </div>
            <Slider.Output className="text-accent text-sm font-medium" />
          </div>
          <Slider.Track>
            <Slider.Fill />
            <Slider.Thumb />
          </Slider.Track>
        </Slider.Root>

        <div className="flex flex-col gap-1">
          <Label>提示词</Label>
          <TextArea
            aria-label="批量提示词"
            placeholder="描述物体应如何融入背景…"
            value={params.prompt}
            onChange={(e) => setBatchPrompt(e.target.value)}
            rows={3}
            fullWidth
            variant="secondary"
            className="resize-y"
          />
        </div>

        <Slider.Root
          aria-label="批量步数"
          step={1}
          minValue={1}
          maxValue={60}
          value={params.steps}
          onChange={(v) => setBatchSteps(Number(v))}
        >
          <div className="flex w-full items-center justify-between gap-4">
            <div className="flex items-center">
              <Label>步数</Label>
              <Hint text="数值越大：生成更精细，但耗时更长。范围 1–60，常用 20–30。" />
            </div>
            <Slider.Output className="text-accent text-sm font-medium" />
          </div>
          <Slider.Track>
            <Slider.Fill />
            <Slider.Thumb />
          </Slider.Track>
        </Slider.Root>

        <Slider.Root
          aria-label="批量引导强度"
          step={0.1}
          minValue={1}
          maxValue={10}
          value={params.guidance}
          onChange={(v) => setBatchGuidance(Number(v))}
          formatOptions={{ maximumFractionDigits: 1 }}
        >
          <div className="flex w-full items-center justify-between gap-4">
            <div className="flex items-center">
              <Label>引导强度</Label>
              <Hint text="数值越大：图像越严格遵循提示词。范围 1–10，常用 3–7。" />
            </div>
            <Slider.Output className="text-accent text-sm font-medium" />
          </div>
          <Slider.Track>
            <Slider.Fill />
            <Slider.Thumb />
          </Slider.Track>
        </Slider.Root>

        <div className="flex flex-col gap-1">
          <Label>输出尺寸（像素，可留空）</Label>
          <div className="flex items-center gap-2">
            <Input
              type="number"
              min={8}
              max={4096}
              variant="secondary"
              step={16}
              placeholder="宽"
              aria-label="批量宽度"
              value={params.width == null ? "" : String(params.width)}
              onChange={(e) => {
                const v = e.target.value;
                const n = Number(v);
                setBatchWidth(v === "" || Number.isNaN(n) ? null : n);
              }}
            />
            <span className="text-muted">×</span>
            <Input
              type="number"
              min={8}
              max={4096}
              variant="secondary"
              step={16}
              placeholder="高"
              aria-label="批量高度"
              value={params.height == null ? "" : String(params.height)}
              onChange={(e) => {
                const v = e.target.value;
                const n = Number(v);
                setBatchHeight(v === "" || Number.isNaN(n) ? null : n);
              }}
            />
          </div>
        </div>

        <p className="text-center text-xs text-muted">
          共 <span className="font-semibold text-accent">{totalTasks}</span> 个任务
          {etaMin != null && totalTasks > 0 && ` · 预估耗时约 ${etaMin} 分钟`}
        </p>

        {batchError && <p className="text-sm text-danger">{batchError}</p>}

        <Button
          variant="primary"
          size="lg"
          fullWidth
          isDisabled={
            batchSubmitting ||
            backgrounds.length === 0 ||
            objects.length === 0 ||
            uploading != null
          }
          onPress={() => void validateAndSubmit()}
        >
          <ArrowUpFromLine />
          {batchSubmitting ? "提交中…" : `批量生成 ${totalTasks} 张`}
        </Button>
      </Card.Content>
    </Card>
  );
}
