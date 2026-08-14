import { create } from "zustand";
import {
  cancelTask as apiCancel,
  createBatch as apiCreateBatch,
  createTask as apiCreate,
  deleteTask as apiDelete,
  retryTask as apiRetry,
  getTask,
  listTasks,
  uploadBulk,
  uploadImages,
  type BulkUploadItem,
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

interface BatchParams {
  k: number;      // objects sampled per background
  rounds: number; // variants per background
  prompt: string;
  steps: number;
  guidance: number;
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

  // batch
  batchBackgrounds: BulkUploadItem[];
  batchObjects: BulkUploadItem[];
  batchPendingFiles: File[];
  batchTag: "background" | "object" | null;
  batchParams: BatchParams;
  batchUploading: { done: number; total: number } | null;
  batchSubmitting: boolean;
  batchError: string | null;
  setBatchPendingFiles: (files: FileList | null) => void;
  setBatchTag: (tag: "background" | "object") => void;
  setBatchK: (v: number) => void;
  setBatchRounds: (v: number) => void;
  setBatchPrompt: (v: string) => void;
  setBatchSteps: (v: number) => void;
  setBatchGuidance: (v: number) => void;
  setBatchWidth: (v: number | null) => void;
  setBatchHeight: (v: number | null) => void;
  uploadBatch: () => Promise<void>;
  submitBatch: () => Promise<void>;
  resetBatch: () => void;
  setBatchError: (err: string | null) => void;

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

  batchBackgrounds: [],
  batchObjects: [],
  batchPendingFiles: [],
  batchTag: null,
  batchParams: {
    k: 3,
    rounds: 1,
    prompt: "将物体自然地融入背景图，保持光影和透视一致",
    steps: 20,
    guidance: 3.5,
    width: null,
    height: null,
  },
  batchUploading: null,
  batchSubmitting: false,
  batchError: null,

  setBatchPendingFiles: (files) => {
    if (!files || files.length === 0) return;
    set((s) => ({ batchPendingFiles: [...s.batchPendingFiles, ...Array.from(files)] }));
  },
  setBatchTag: (tag) => set({ batchTag: tag }),
  setBatchK: (v) => set((s) => ({ batchParams: { ...s.batchParams, k: v } })),
  setBatchRounds: (v) => set((s) => ({ batchParams: { ...s.batchParams, rounds: v } })),
  setBatchPrompt: (v) => set((s) => ({ batchParams: { ...s.batchParams, prompt: v } })),
  setBatchSteps: (v) => set((s) => ({ batchParams: { ...s.batchParams, steps: v } })),
  setBatchGuidance: (v) => set((s) => ({ batchParams: { ...s.batchParams, guidance: v } })),
  setBatchWidth: (v) => set((s) => ({ batchParams: { ...s.batchParams, width: v } })),
  setBatchHeight: (v) => set((s) => ({ batchParams: { ...s.batchParams, height: v } })),
  setBatchError: (err) => set({ batchError: err }),

  uploadBatch: async () => {
    const { batchPendingFiles, batchTag } = get();
    if (!batchTag || batchPendingFiles.length === 0) return;
    set({ batchError: null, batchUploading: { done: 0, total: batchPendingFiles.length } });
    try {
      const manifest = await uploadBulk(
        batchPendingFiles,
        batchTag,
        25,
        (done) => set({ batchUploading: { done, total: batchPendingFiles.length } })
      );
      set((s) => ({
        batchBackgrounds:
          batchTag === "background" ? [...s.batchBackgrounds, ...manifest] : s.batchBackgrounds,
        batchObjects:
          batchTag === "object" ? [...s.batchObjects, ...manifest] : s.batchObjects,
        batchPendingFiles: [],
        batchUploading: null,
        batchTag: null,
      }));
    } catch (e: any) {
      set({ batchError: e?.message ?? "批量上传失败", batchUploading: null });
    }
  },

  submitBatch: async () => {
    const { batchBackgrounds, batchObjects, batchParams } = get();
    if (batchBackgrounds.length === 0) {
      set({ batchError: "请先上传背景图" });
      return;
    }
    if (batchObjects.length === 0) {
      set({ batchError: "请先上传单图物体" });
      return;
    }
    if (!batchParams.prompt || !batchParams.prompt.trim()) {
      set({ batchError: "提示词不能为空" });
      return;
    }
    set({ batchSubmitting: true, batchError: null });
    try {
      await apiCreateBatch({
        background_images: batchBackgrounds.map((m) => m.filename),
        object_images: batchObjects.map((m) => m.filename),
        ...batchParams,
      });
      await get().refreshTasks();
      get().startPolling();
    } catch (e: any) {
      set({ batchError: e?.message ?? "批量任务提交失败" });
    } finally {
      set({ batchSubmitting: false });
    }
  },

  resetBatch: () =>
    set({
      batchBackgrounds: [],
      batchObjects: [],
      batchPendingFiles: [],
      batchTag: null,
      batchParams: {
        k: 3,
        rounds: 1,
        prompt: "将物体自然地融入背景图，保持光影和透视一致",
        steps: 20,
        guidance: 3.5,
        width: null,
        height: null,
      },
      batchError: null,
    }),

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
