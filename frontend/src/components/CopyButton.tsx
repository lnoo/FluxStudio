import { useEffect, useRef, useState } from "react";
import { Button, Tooltip } from "@heroui/react";
import { Check, Copy, Xmark } from "@gravity-ui/icons";

interface CopyButtonProps {
  value: string;
  label?: string;
  copiedLabel?: string;
  failedLabel?: string;
  size?: "sm" | "md" | "lg";
  variant?: "primary" | "secondary" | "tertiary" | "ghost" | "outline" | "danger" | "danger-soft";
  className?: string;
}

type CopyState = "idle" | "copied" | "failed";

async function writeClipboard(value: string): Promise<boolean> {
  if (typeof navigator === "undefined") return false;
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(value);
      return true;
    } catch {
      return false;
    }
  }
  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.select();
  const ok = document.execCommand("copy");
  document.body.removeChild(textarea);
  return ok;
}

export function CopyButton({
  value,
  label = "复制",
  copiedLabel = "已复制",
  failedLabel = "复制失败",
  size,
  variant = "ghost",
  className,
}: CopyButtonProps) {
  const [state, setState] = useState<CopyState>("idle");
  const timerRef = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (timerRef.current != null) window.clearTimeout(timerRef.current);
    },
    []
  );

  const resetSoon = () => {
    if (timerRef.current != null) window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => setState("idle"), 2000);
  };

  const handleCopy = async () => {
    const ok = await writeClipboard(value);
    setState(ok ? "copied" : "failed");
    resetSoon();
  };

  const currentLabel = state === "copied" ? copiedLabel : state === "failed" ? failedLabel : label;

  return (
    <>
      <Tooltip.Root delay={400}>
        <Button
          size={size}
          variant={variant}
          isIconOnly
          aria-label={currentLabel}
          onPress={() => void handleCopy()}
          className={className}
        >
          {state === "copied" ? (
            <Check className="text-success" />
          ) : state === "failed" ? (
            <Xmark className="text-danger" />
          ) : (
            <Copy />
          )}
        </Button>
        <Tooltip.Content>{currentLabel}</Tooltip.Content>
      </Tooltip.Root>
      <span className="sr-only" role="status" aria-live="polite">
        {state !== "idle" ? currentLabel : ""}
      </span>
    </>
  );
}