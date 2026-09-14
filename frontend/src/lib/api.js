import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

export const api = axios.create({ baseURL: API });

export const validateEmails = (payload) => api.post("/validate", payload).then((r) => r.data);
export const getHistory = () => api.get("/history").then((r) => r.data);
export const getBatch = (id) => api.get(`/history/${id}`).then((r) => r.data);
export const deleteBatch = (id) => api.delete(`/history/${id}`).then((r) => r.data);

// --- Bulk jobs ---
export const createJob = (formData) =>
  api.post("/jobs", formData, { headers: { "Content-Type": "multipart/form-data" } }).then((r) => r.data);
export const listJobs = () => api.get("/jobs").then((r) => r.data);
export const getJob = (id) => api.get(`/jobs/${id}`).then((r) => r.data);
export const pauseJob = (id) => api.post(`/jobs/${id}/pause`).then((r) => r.data);
export const resumeJob = (id) => api.post(`/jobs/${id}/resume`).then((r) => r.data);
export const cancelJob = (id) => api.post(`/jobs/${id}/cancel`).then((r) => r.data);
export const deleteJob = (id) => api.delete(`/jobs/${id}`).then((r) => r.data);
export const downloadUrl = (id, category = "all") => `${API}/jobs/${id}/download?category=${category}`;

// --- Proxies ---
export const listProxies = () => api.get("/proxies").then((r) => r.data);
export const addProxy = (payload) => api.post("/proxies", payload).then((r) => r.data);
export const deleteProxy = (id) => api.delete(`/proxies/${id}`).then((r) => r.data);
export const testProxy = (payload) => api.post("/proxies/test", payload).then((r) => r.data);
