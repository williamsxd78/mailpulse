import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

export const api = axios.create({ baseURL: API });

export const validateEmails = (payload) => api.post("/validate", payload).then((r) => r.data);
export const getHistory = () => api.get("/history").then((r) => r.data);
export const getBatch = (id) => api.get(`/history/${id}`).then((r) => r.data);
export const deleteBatch = (id) => api.delete(`/history/${id}`).then((r) => r.data);
