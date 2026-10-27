/* One presentation state for durable snapshots, SSE and local connection state. */
((root, factory) => {
  const api = factory();
  root.RunPresentation = api;
  if (typeof module !== 'undefined') module.exports = api;
})(globalThis, () => {
  const terminal = new Set(['completed', 'failed', 'cancelled', 'waiting_input']);
  const immutableTerminal = new Set(['completed', 'failed', 'cancelled']);
  const phases = new Set(['queued', 'running', ...terminal]);
  const timestamp = value => Number.isFinite(Date.parse(value)) ? Date.parse(value) : 0;
  function create(id, stage, now = Date.now()) {
    return {id, stage, status: 'queued', phase: 'queued', createdAt: now,
      startedAt: null, serverUpdatedAt: 0, eventId: 0};
  }
  function reduce(previous, action, now = Date.now()) {
    const state = {...previous};
    if (action.id && action.id !== state.id) return previous;
    if (immutableTerminal.has(state.status)) return previous;
    if (action.kind === 'connection.lost') return {...state, phase: 'reconnecting'};
    if (action.kind === 'connection.open') return {...state, phase: state.cancelRequested ? 'cancelling' : state.status};
    if (action.kind === 'cancel.requested') return {...state, phase: 'cancelling', cancelRequested: true, cancelUnconfirmed: false};
    if (action.kind === 'cancel.unconfirmed') return {...state, phase: 'cancelling', cancelRequested: true, cancelUnconfirmed: true};
    if (['saving', 'submitting'].includes(action.kind)) return {...state, phase: action.kind};
    let status, stage, updated;
    if (action.kind === 'snapshot') {
      const run = action.run;
      if (run.id && run.id !== state.id) return previous;
      updated = timestamp(run.updated_at);
      if (updated && updated < state.serverUpdatedAt) return previous;
      status = run.status; stage = run.stage;
      state.createdAt = timestamp(run.created_at) || state.createdAt;
      state.startedAt = timestamp(run.started_at) || state.startedAt;
    } else if (action.kind === 'event') {
      const id = Number(action.eventId) || 0;
      if (id && id <= state.eventId) return previous;
      updated = timestamp(action.createdAt);
      if (updated && updated < state.serverUpdatedAt) return previous;
      state.eventId = id || state.eventId;
      const type = action.type;
      if (type === 'run.recovered' || type === 'run.queued' || type === 'run.created') status = 'queued';
      else if (type.startsWith('run.') && phases.has(type.slice(4))) status = type.slice(4);
      else if (type === 'run.started' || type === 'stage.resolved' || type.startsWith('tool.')) status = 'running';
      if (type === 'run.started') state.startedAt = updated || now;
      if (type === 'stage.resolved') stage = action.payload?.stage;
    }
    if (phases.has(status)) state.status = status;
    if (stage) state.stage = stage;
    state.serverUpdatedAt = Math.max(state.serverUpdatedAt, updated || 0);
    state.phase = state.cancelRequested && !terminal.has(state.status) ? 'cancelling' : state.status;
    return state;
  }
  function title(state, label) {
    if (state?.cancelUnconfirmed && !terminal.has(state.status)) return '取消结果待确认';
    return ({saving: '正在保存修改', submitting: '正在确认提交', queued: '任务已排队',
      reconnecting: '连接中断，正在恢复', cancelling: '正在取消任务',
      completed: '本轮已完成', failed: '本轮未完成', cancelled: '任务已取消',
      waiting_input: '等待补充信息'})[state?.phase] || `正在执行：${label}`;
  }
  return {create, reduce, title, terminal: status => terminal.has(status)};
});
