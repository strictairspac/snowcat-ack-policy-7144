import { request } from "./http.js";

export const api = {
  config: () => request("/workbench"),
  login: data => request("/auth/login", {method: "POST", data}),
  cases: () => request("/cases"),
  case: id => request(`/cases/${id}`),
  createCase: data => request("/cases", {method: "POST", data}),
  runs: () => request("/runs"),
  run: (id, signal) => request(`/runs/${id}`, {signal}),
  enqueue: (id, data) => request(`/cases/${id}/runs`, {method: "POST", data}),
  review: id => request(`/runs/${id}/review`),
  submitReview: (id, data) => request(`/runs/${id}/review`, {method: "POST", data}),
  export: id => request(`/runs/${id}/export`, {raw: true}),
  handoffs: () => request("/handoffs"),
  handoff: id => request(`/handoffs/${id}`),
  runHandoff: runId => request(`/runs/${runId}/handoff`),
  createRunHandoff: (runId, data) => request(`/runs/${runId}/handoff`, {method: "POST", data}),
  continueRun: (runId, data) => request(`/runs/${runId}/continue`, {method: "POST", data}),
  retryRun: runId => request(`/runs/${runId}/retry`, {method: "POST"}),
  audit: () => request("/audit", {signal: AbortSignal.timeout(5000)}),
};
