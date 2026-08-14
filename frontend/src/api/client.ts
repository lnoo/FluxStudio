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
