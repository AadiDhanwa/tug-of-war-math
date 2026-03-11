/* shared.js — auth helpers + toast used by all pages */

const MB = {
  token: localStorage.getItem('mb_token'),
  user:  JSON.parse(localStorage.getItem('mb_user') || 'null'),

  saveAuth(token, user) {
    this.token = token; this.user = user;
    localStorage.setItem('mb_token', token);
    localStorage.setItem('mb_user', JSON.stringify(user));
  },
  clearAuth() {
    this.token = null; this.user = null;
    localStorage.removeItem('mb_token');
    localStorage.removeItem('mb_user');
  },

  async fetch(url, opts={}) {
    opts.headers = opts.headers || {};
    if (this.token) opts.headers['X-Auth-Token'] = this.token;
    if (opts.body && typeof opts.body === 'object') {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(opts.body);
    }
    return fetch(url, opts);
  },

  async verifyAuth() {
    /* Returns user if token valid, else null */
    if (!this.token) return null;
    try {
      const res = await this.fetch('/api/auth/me');
      if (!res.ok) { this.clearAuth(); return null; }
      const data = await res.json();
      this.user = data.user;
      localStorage.setItem('mb_user', JSON.stringify(data.user));
      return data.user;
    } catch { this.clearAuth(); return null; }
  },

  logout() {
    this.clearAuth();
    window.location.href = '/';
  }
};

/* Toast */
let _toastTimer = null;
function showToast(msg, type='info') {
  let t = document.getElementById('toast');
  if (!t) {
    t = document.createElement('div');
    t.id = 'toast'; t.className = 'toast';
    document.body.appendChild(t);
  }
  t.textContent = msg;
  t.className = `toast toast-${type} show`;
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => t.classList.remove('show'), 2500);
}

/* Copy helpers */
function copyToClipboard(text, label='Copied!') {
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text)
      .then(() => showToast('📋 ' + label, 'info'))
      .catch(() => fallbackCopy(text, label));
  } else { fallbackCopy(text, label); }
}
function fallbackCopy(text, label='Copied!') {
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.cssText = 'position:fixed;top:0;left:0;opacity:0;font-size:16px;';
  document.body.appendChild(ta);
  ta.focus(); ta.select(); ta.setSelectionRange(0, 99999);
  try { document.execCommand('copy'); showToast('📋 ' + label, 'info'); }
  catch { showToast('Long-press to copy', 'info'); }
  document.body.removeChild(ta);
}
function shareOrCopy(text, title='MathBattle') {
  if (navigator.share) { navigator.share({title, text}).catch(()=>copyToClipboard(text)); }
  else { copyToClipboard(text); }
}
