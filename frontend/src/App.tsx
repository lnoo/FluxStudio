import { useEffect } from "react";
import { Button, ScrollShadow } from "@heroui/react";
import { Sun, Moon } from "@gravity-ui/icons";
import { UploadPanel } from "./components/UploadPanel";
import { ParamsPanel } from "./components/ParamsPanel";
import { TaskList } from "./components/TaskList";
import { BackToTop } from "./components/BackToTop";
import { useStore } from "./store/appStore";

export default function App() {
  const theme = useStore((s) => s.theme);
  const toggleTheme = useStore((s) => s.toggleTheme);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
  }, [theme]);

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="flex items-center justify-between border-b border-border px-6 py-4">
        <div>
          <h1 className="text-2xl font-bold">FLUX Studio</h1>
          <p className="text-sm text-muted">FLUX.2-dev 图像生成平台</p>
        </div>
        <Button
          variant="secondary"
          isIconOnly
          aria-label={theme === "dark" ? "切换到亮色模式" : "切换到暗色模式"}
          onPress={toggleTheme}
        >
          {theme === "dark" ? <Sun /> : <Moon />}
        </Button>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-6">
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
          <ScrollShadow
            hideScrollBar
            className="flex flex-col gap-6 md:sticky md:top-6 md:self-start md:max-h-[calc(100vh-3rem)]"
          >

            <UploadPanel />
            <ParamsPanel />
          </ScrollShadow>
          <TaskList />
        </div>
      </main>

      <BackToTop />
    </div>
  );
}
