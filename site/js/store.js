// Analyst decisions on discrepancies, kept per viewer in localStorage.
// Storage can be unavailable (private mode, blocked cookies); the page still works, decisions just do not persist.

const PREFIX = "dealscreen.v1.decisions.";
const memory = new Map();

function read(dealId) {
  try {
    const raw = window.localStorage.getItem(PREFIX + dealId);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return memory.get(dealId) || {};
  }
}

function write(dealId, value) {
  memory.set(dealId, value);
  try {
    window.localStorage.setItem(PREFIX + dealId, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}

export function decisions(dealId) {
  return read(dealId);
}

export function setDecision(dealId, discId, state, note) {
  const all = read(dealId);
  if (!state) delete all[discId];
  else all[discId] = { state, note: note || "", at: new Date().toISOString() };
  return write(dealId, all);
}

export function setNote(dealId, discId, note) {
  const all = read(dealId);
  if (!all[discId]) return false;
  all[discId].note = note;
  return write(dealId, all);
}

export function clearDeal(dealId) {
  memory.delete(dealId);
  try { window.localStorage.removeItem(PREFIX + dealId); } catch { /* ignore */ }
}
