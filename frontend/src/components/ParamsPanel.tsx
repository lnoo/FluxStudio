import { Button, Card, Input, Label, Slider, TextArea, Tooltip } from "@heroui/react";
import { CircleInfo, Sparkles } from "@gravity-ui/icons";
import { useStore } from "../store/appStore";

function Hint({ text }: { text: string }) {
  return (
    <Tooltip.Root delay={400}>
      <Button isIconOnly variant="ghost">
        <CircleInfo />
      </Button>
      <Tooltip.Content>
        {text}
      </Tooltip.Content>
    </Tooltip.Root>
  );
}

export function ParamsPanel() {
  const params = useStore((s) => s.params);
  const pendingCount = useStore((s) => s.pendingFiles.length);
  const setPrompt = useStore((s) => s.setPrompt);
  const setSteps = useStore((s) => s.setSteps);
  const setGuidance = useStore((s) => s.setGuidance);
  const setWidth = useStore((s) => s.setWidth);
  const setHeight = useStore((s) => s.setHeight);
  const submit = useStore((s) => s.submit);
  const submitting = useStore((s) => s.submitting);
  const error = useStore((s) => s.error);
  const setError = useStore((s) => s.setError);
  const startPolling = useStore((s) => s.startPolling);

  const onSubmit = async () => {
    if (!params.prompt || !params.prompt.trim()) {
      setError("提示词不能为空，请输入场景或提示描述");
      return;
    }
    if (params.width != null && (params.width < 8 || params.width > 4096)) {
      setError("输出宽度必须介于 8 与 4096 像素之间");
      return;
    }
    if (params.height != null && (params.height < 8 || params.height > 4096)) {
      setError("输出高度必须介于 8 与 4096 像素之间");
      return;
    }
    if (params.steps < 1 || params.steps > 60) {
      setError("生成步数必须介于 1 与 60 之间");
      return;
    }

    setError(null);
    const id = await submit();
    if (id) startPolling();
  };

  return (
    <Card>
      <Card.Content className="gap-6 p-5">
        <h2 className="text-lg font-semibold">生成设置</h2>

        <div className="flex flex-col gap-1">
          <Label>提示词</Label>
          <TextArea
            aria-label="提示词"
            placeholder="描述场景或物体的摆放方式…"
            value={params.prompt}
            onChange={(e) => setPrompt(e.target.value)}
            rows={5}
            fullWidth
            variant="secondary"
            className="resize-y"
          />
        </div>

        <Slider.Root
          aria-label="步数"
          step={1}
          minValue={1}
          maxValue={60}
          value={params.steps}
          onChange={(v) => setSteps(Number(v))}
        >
          <div className="flex w-full items-center justify-between gap-4">
            <div className="flex items-center">
              <Label>步数</Label>
              <Hint text="数值越大：生成更精细、细节更丰富，但耗时更长；数值越小：生成更快，但细节和稳定性下降。范围 1–60，常用 20–30。" />
            </div>
            <Slider.Output className="text-accent text-sm font-medium" />
          </div>
          <Slider.Track>
            <Slider.Fill />
            <Slider.Thumb />
          </Slider.Track>
        </Slider.Root>

        <Slider.Root
          aria-label="引导强度"
          step={0.1}
          minValue={1}
          maxValue={10}
          value={params.guidance}
          onChange={(v) => setGuidance(Number(v))}
          formatOptions={{ maximumFractionDigits: 1 }}
        >
          <div className="flex w-full items-center justify-between gap-4">
            <div className="flex items-center">
              <Label>引导强度</Label>
              <Hint text="数值越大：图像越严格遵循提示词，但可能过饱和、僵硬；数值越小：生成更自由多样，但可能与提示词偏离。范围 1–10，常用 3–7。" />
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
              aria-label="宽度"
              value={params.width == null ? "" : String(params.width)}
              onChange={(e) => {
                const v = e.target.value;
                const n = Number(v);
                setWidth(v === "" || Number.isNaN(n) ? null : n);
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
              aria-label="高度"
              value={params.height == null ? "" : String(params.height)}
              onChange={(e) => {
                const v = e.target.value;
                const n = Number(v);
                setHeight(v === "" || Number.isNaN(n) ? null : n);
              }}
            />
          </div>
        </div>

        <p className="text-xs text-muted">
          {pendingCount > 0
            ? "图像编辑/融合模式：基于上传的图片生成，留空尺寸则跟随背景图"
            : "文生图模式：直接根据提示词生成，留空尺寸默认 1024×1024"}
        </p>

        {error && <p className="text-sm text-danger">{error}</p>}

        <Button
          variant="primary"
          size="lg"
          fullWidth
          isDisabled={submitting}
          onPress={onSubmit}
        >
          <Sparkles />
          {submitting ? "生成中…" : "生成"}
        </Button>
      </Card.Content>
    </Card>
  );
}