// Client HTTP du panneau d'étude (`docs/API_CONTRACT.md`, `docs/STUDY_PANEL_SPEC.md` §7).
// Chemins relatifs : le navigateur n'appelle jamais un hôte fixe ; l'aperçu proxifie `/api`.
// Le jeton reste en mémoire de l'onglet ; il n'entre jamais dans une URL.

export class ApiError extends Error {
  constructor(status, problem) {
    super(problem?.message || `erreur HTTP ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.code = problem?.code || "http";
    this.field = problem?.field || null;
  }
}

const enc = encodeURIComponent;

export function createClient({ base = "", token = null, fetchImpl = globalThis.fetch } = {}) {
  async function request(method, path, body) {
    const headers = { Accept: "application/json" };
    if (token) headers.Authorization = `Bearer ${token}`;
    const init = { method, headers };
    if (body !== undefined) {
      headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(body);
    }
    const res = await fetchImpl(base + path, init);
    if (res.status === 204) return null;
    const text = await res.text();
    let data = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = null;
    }
    if (!res.ok) throw new ApiError(res.status, data);
    return data;
  }

  const s = (sid) => `/api/v1/sessions/${enc(sid)}`;
  return {
    listSessions: () => request("GET", "/api/v1/sessions"),
    createSession: (body) => request("POST", "/api/v1/sessions", body),
    deleteSession: (sid) => request("DELETE", s(sid)),
    topology: (sid) => request("GET", `${s(sid)}/topology`),
    addNode: (sid, node) => request("POST", `${s(sid)}/nodes`, node),
    removeNode: (sid, nodeId) => request("DELETE", `${s(sid)}/nodes/${enc(nodeId)}`),
    setSensor: (sid, nodeId, settings) =>
      request("POST", `${s(sid)}/nodes/${enc(nodeId)}/sensor`, settings),
    moveNode: (sid, nodeId, pos) => request("POST", `${s(sid)}/nodes/${enc(nodeId)}/position`, pos),
    cli: (sid, nodeId, command) => request("POST", `${s(sid)}/cli`, { node_id: nodeId, command }),
    simulate: (sid, seed) => request("POST", `${s(sid)}/simulate`, { seed }),
    bind: (sid, runId) => request("POST", `${s(sid)}/simulation`, { run_id: runId }),
    hint: (sid, exerciseId) => request("POST", `${s(sid)}/hints`, { exercise_id: exerciseId }),
    attempts: (sid) => request("GET", `${s(sid)}/attempts`),
    exercises: () => request("GET", "/api/v1/exercises"),
    submit: (exerciseId, sid) =>
      request("POST", `/api/v1/exercises/${enc(exerciseId)}/submit`, { session_id: sid }),
    run: (runId) => request("GET", `/api/v1/runs/${enc(runId)}`),
    summary: (runId) => request("GET", `/api/v1/runs/${enc(runId)}/summary`),
    eventsPage: (runId, cursor = 0, limit = 500) =>
      request("GET", `/api/v1/runs/${enc(runId)}/events?cursor=${cursor}&limit=${limit}`),
    devicesPage: (runId, cursor = 0, limit = 500) =>
      request("GET", `/api/v1/runs/${enc(runId)}/devices?cursor=${cursor}&limit=${limit}`),
  };
}
