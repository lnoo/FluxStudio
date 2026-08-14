import { create } from "zustand";
import {
  cancelTask as apiCancel,
  createTask as apiCreate,
  deleteTask as apiDelete,
  retryTask as apiRetry,
  getTask,
  listTasks,
  uploadImages,
  type TaskStatus,
} from "../api/client";

interface PendingFile {
  file: File;
  previewUrl: string;
  storedFilename?: string; // set after upload
}

interface GenerationParams {
  prompt: string;
  steps: number;
  guidance: number;
  // null = 不指定，由模型使用默认尺寸（文生图 1024×1024，图生图跟随背景图）
  width: number | null;
  height: number | null;
}

interface AppState {
  // theme
  theme: "light" | "dark";
  toggleTheme: () => void;

  // uploads
  pendingFiles: PendingFile[];
  addFiles: (files: FileList) => void;
  removeFile: (idx: number) => void;
  clearFiles: () => void;

  // params
  params: GenerationParams;
  setPrompt: (v: string) => void;
  setSteps: (v: number) => void;
  setGuidance: (v: number) => void;
  setWidth: (v: number | null) => void;
  setHeight: (v: number | null) => void;
  resetParams: () => void;
  setError: (err: string | null) => void;

  // tasks
  tasks: TaskStatus[];
  submitting: boolean;
  error: string | null;
  submit: () => Promise<string | null>;
  cancel: (id: string) => Promise<void>;
  retry: (id: string) => Promise<void>;
  remove: (id: string) => Promise<void>;
  refreshTasks: () => Promise<void>;
  pollActive: boolean;

  // polling
  startPolling: () => void;
  stopPolling: () => void;
}

let pollTimer: ReturnType<typeof setInterval> | null = null;

const THEME_KEY = "flux-studio-theme";

function getInitialTheme(): "light" | "dark" {
  const saved = localStorage.getItem(THEME_KEY);
  return saved === "dark" ? "dark" : "light";
}

export const useStore = create<AppState>((set, get) => ({
  theme: getInitialTheme(),
  toggleTheme: () =>
    set((s) => {
      const next: "light" | "dark" = s.theme === "dark" ? "light" : "dark";
      localStorage.setItem(THEME_KEY, next);
      document.documentElement.classList.toggle("dark", next === "dark");
      return { theme: next };
    }),

  pendingFiles: [],
  addFiles: (files) => {
    const newOnes: PendingFile[] = Array.from(files).map((file) => ({
      file,
      previewUrl: URL.createObjectURL(file),
    }));
    set((s) => ({ pendingFiles: [...s.pendingFiles, ...newOnes] }));
  },
  removeFile: (idx) =>
    set((s) => {
      const removed = s.pendingFiles[idx];
      if (removed) URL.revokeObjectURL(removed.previewUrl);
      return { pendingFiles: s.pendingFiles.filter((_, i) => i !== idx) };
    }),
  clearFiles: () =>
    set((s) => {
      s.pendingFiles.forEach((f) => URL.revokeObjectURL(f.previewUrl));
      return { pendingFiles: [] };
    }),

  params: { prompt: "", steps: 20, guidance: 3.5, width: null, height: null },
  setPrompt: (v) => set((s) => ({ params: { ...s.params, prompt: v } })),
  setSteps: (v) => set((s) => ({ params: { ...s.params, steps: v } })),
  setGuidance: (v) => set((s) => ({ params: { ...s.params, guidance: v } })),
  setWidth: (v) => set((s) => ({ params: { ...s.params, width: v } })),
  setHeight: (v) => set((s) => ({ params: { ...s.params, height: v } })),
  resetParams: () =>
    set({ params: { prompt: "", steps: 20, guidance: 3.5, width: null, height: null } }),
  setError: (err) => set({ error: err }),

  tasks: [],
  submitting: false,
  error: null,
  pollActive: false,

  submit: async () => {
    const { pendingFiles, params, clearFiles, resetParams } = get();
    set({ submitting: true, error: null });
    try {
      const storedNames =
        pendingFiles.length > 0 ? await uploadImages(pendingFiles.map((f) => f.file)) : [];

      const res = await apiCreate({ images: storedNames, ...params });
      clearFiles();
      resetParams();
      await get().refreshTasks();
      return res.task_id;
    } catch (e: any) {
      set({ error: e?.message ?? "提交失败" });
      return null;
    } finally {
      set({ submitting: false });
    }
  },

  refreshTasks: async () => {
    try {
      const tasks = await listTasks();
      set({ tasks });
      // Auto-start polling if any task is in an active (non-terminal) state.
      // This ensures polling resumes after a browser refresh.
      const hasActive = tasks.some(
        (t: TaskStatus) => t.status === "queued" || t.status === "running"
      );
      if (hasActive && !get().pollActive) {
        get().startPolling();
      }
    } catch {
      /* ignore transient errors */
    }
  },

  cancel: async (id) => {
    try {
      await apiCancel(id);
      await get().refreshTasks();
    } catch (e: any) {
      set({ error: e?.message ?? "取消失败" });
    }
  },

  retry: async (id) => {
    try {
      await apiRetry(id);
      await get().refreshTasks();
      get().startPolling();
    } catch (e: any) {
      set({ error: e?.message ?? "重试失败" });
    }
  },

  remove: async (id) => {
    try {
      await apiDelete(id);
      await get().refreshTasks();
    } catch (e: any) {
      set({ error: e?.message ?? "删除失败" });
    }
  },

  startPolling: () => {
    if (pollTimer) return;
    set({ pollActive: true });
    const tick = async () => {
      await get().refreshTasks();
      const active = get().tasks.some(
        (t: TaskStatus) => t.status === "queued" || t.status === "running"
      );
      if (!active) {
        get().stopPolling();
      }
    };
    void tick();
    pollTimer = setInterval(() => void tick(), 5000);
  },
  stopPolling: () => {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
    set({ pollActive: false });
  },
}));
