import axios from "axios";

const BASE_URL = import.meta.env.VITE_API_BASE || "/api";

export const http = axios.create({ baseURL: BASE_URL, timeout: 60_000 });

export interface TaskParams {
  prompt: string;
  steps: number;
  guidance: number | null;
  input_images: string[];
  width?: number | null;
  height?: number | null;
}

export interface TaskStatus {
  task_id: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  progress: number;
  output_image?: string | null;
  error?: string | null;
  params: TaskParams;
  avg_sec_per_step?: number | null;
  duration_seconds?: number | null;
}

export interface GenerateResponse {
  task_id: string;
  status: string;
}

export async function uploadImages(files: File[]): Promise<string[]> {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  // Do NOT set Content-Type manually: axios must add the multipart boundary.
  const { data } = await http.post<{ images: string[] }>("/upload", form);
  return data.images;
}

export interface BulkUploadItem {
  filename: string;
  original_name: string;
  tag?: string | null;
}

/**
 * Upload a large set of files (e.g. a whole background/object folder) in
 * chunks to stay under the nginx body-size limit, tagging each file's role.
 * Returns the full manifest across all chunks.
 */
export async function uploadBulk(
  files: File[],
  tag: string,
  chunkSize = 25,
  onProgress?: (done: number, total: number) => void
): Promise<BulkUploadItem[]> {
  const manifest: BulkUploadItem[] = [];
  let done = 0;
  for (let i = 0; i < files.length; i += chunkSize) {
    const chunk = files.slice(i, i + chunkSize);
    const form = new FormData();
    for (const f of chunk) form.append("files", f);
    form.append("tag", tag);
    const { data } = await http.post<{ images: BulkUploadItem[] }>("/upload/bulk", form);
    manifest.push(...data.images);
    done += chunk.length;
    onProgress?.(done, files.length);
  }
  return manifest;
}

export interface GeneratePayload {
  images: string[];
  prompt: string;
  steps: number;
  guidance: number;
  width?: number | null;
  height?: number | null;
}

export async function createTask(payload: GeneratePayload): Promise<GenerateResponse> {
  const { data } = await http.post<GenerateResponse>("/generate", payload);
  return data;
}

export interface BatchGeneratePayload {
  background_images: string[];
  object_images: string[];
  k: number;
  rounds: number;
  prompt: string;
  steps: number;
  guidance: number;
  width?: number | null;
  height?: number | null;
}

export interface BatchGenerateResponse {
  task_ids: string[];
  count: number;
}

export async function createBatch(payload: BatchGeneratePayload): Promise<BatchGenerateResponse> {
  const { data } = await http.post<BatchGenerateResponse>("/batch/generate", payload);
  return data;
}

export async function getTask(id: string): Promise<TaskStatus> {
  const { data } = await http.get<TaskStatus>(`/tasks/${id}`);
  return data;
}

export async function listTasks(): Promise<TaskStatus[]> {
  const { data } = await http.get<TaskStatus[]>("/tasks");
  return data;
}

export async function cancelTask(id: string): Promise<void> {
  await http.post(`/tasks/${id}/cancel`);
}

export async function deleteTask(id: string): Promise<void> {
  await http.delete(`/tasks/${id}`);
}

export async function retryTask(id: string): Promise<TaskStatus> {
  const { data } = await http.post<TaskStatus>(`/tasks/${id}/retry`);
  return data;
}

export function imageUrl(filename: string): string {
  return `${BASE_URL}/images/by-name/${encodeURIComponent(filename)}`;
}

export function downloadUrl(filename: string, suggestedName?: string): string {
  const url = imageUrl(filename);
  if (!suggestedName) return url;
  return `${url}?name=${encodeURIComponent(suggestedName)}`;
}
