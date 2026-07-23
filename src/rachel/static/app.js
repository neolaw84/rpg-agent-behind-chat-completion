var LS_KEY = 'rpg_proxy_api_key';
var _apiKey = localStorage.getItem(LS_KEY) || '';
var _currentSession = null;
var _keyVisible = false;

// ── Utilities ────────────────────────────────────────────────────────
function showToast(msg, type, duration) {
  type = type || 'ok'; duration = duration || 3000;
  var el = document.createElement('div');
  el.className = 'toast ' + type;
  el.textContent = msg;
  document.getElementById('toast-container').appendChild(el);
  setTimeout(function () { el.remove(); }, duration);
}

function showConfirm(title, msg, onOk) {
  var ov = document.getElementById('confirm-overlay');
  document.getElementById('confirm-title').textContent = title;
  document.getElementById('confirm-msg').textContent = msg;
  ov.classList.remove('hidden');
  function cleanup() { ov.classList.add('hidden'); }
  document.getElementById('confirm-ok').onclick = function () { cleanup(); onOk(); };
  document.getElementById('confirm-cancel').onclick = cleanup;
}

function apiFetch(path, opts) {
  opts = opts || {};
  var headers = Object.assign({ 'Authorization': 'Bearer ' + _apiKey, 'Content-Type': 'application/json' }, opts.headers || {});
  return fetch(path, Object.assign({}, opts, { headers: headers })).then(function (res) {
    if (res.status === 401) { showAuth('Invalid API key. Please reconnect.'); throw new Error('Unauthorized'); }
    return res;
  });
}

function syntaxHighlight(obj) {
  var json = JSON.stringify(obj, null, 2);
  return json.replace(/("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g, function (match) {
    var cls = 'json-num';
    if (/^"/.test(match)) cls = /:$/.test(match) ? 'json-key' : 'json-string';
    else if (/true|false/.test(match)) cls = 'json-bool';
    else if (/null/.test(match)) cls = 'json-null';
    return '<span class="' + cls + '">' + match + '</span>';
  });
}

function copyText(text, btn) {
  navigator.clipboard.writeText(text).then(function () {
    var orig = btn.textContent;
    btn.textContent = '✓ Copied'; btn.classList.add('copied');
    setTimeout(function () { btn.textContent = orig; btn.classList.remove('copied'); }, 2000);
  });
}

// ── Auth ─────────────────────────────────────────────────────────────
function showAuth(errMsg) {
  _apiKey = ''; localStorage.removeItem(LS_KEY);
  document.getElementById('auth-overlay').classList.remove('hidden');
  document.getElementById('auth-error').textContent = errMsg || '';
  document.getElementById('auth-key-input').value = '';
}
function hideAuth() { document.getElementById('auth-overlay').classList.add('hidden'); }

function tryConnect(key) {
  var errEl = document.getElementById('auth-error');
  errEl.textContent = 'Verifying…';
  fetch('/v1/status', { headers: { 'Authorization': 'Bearer ' + key } }).then(function (res) {
    if (res.ok) {
      _apiKey = key; localStorage.setItem(LS_KEY, key);
      hideAuth(); onConnected();
    } else {
      errEl.textContent = 'Invalid API key. Please check and try again.';
    }
  }).catch(function () {
    errEl.textContent = 'Connection failed. Is the proxy running?';
  });
}

// ── Providers ─────────────────────────────────────────────────────────
var _providersData = null;
var _selectedProvider = null;

var PROVIDER_NAMES = {
  'openrouter_byok': 'OpenRouter (BYOK Key)',
  'openrouter_pkce': 'OpenRouter (PKCE OAuth)',
  'openai_byok': 'OpenAI (BYOK Key)',
  'gemini_byok': 'Google Gemini (BYOK Key)',
  'deepseek_byok': 'DeepSeek (BYOK Key)'
};

function loadProviders() {
  var container = document.getElementById('provider-options');
  apiFetch('/v1/providers').then(function (res) { return res.json(); }).then(function (d) {
    _providersData = d;
    _selectedProvider = d.active_provider;
    var html = Object.keys(PROVIDER_NAMES).map(function (pk) {
      var info = d.providers[pk] || {};
      var checked = (pk === d.active_provider) ? 'checked' : '';
      var statusTag = info.configured ? ' <span style="color:var(--green);font-size:0.75rem;">(Key Set)</span>' : ' <span style="color:var(--muted);font-size:0.75rem;">(Not Set)</span>';
      return '<label style="text-transform:none;font-weight:normal;cursor:pointer;display:flex;align-items:center;gap:6px;background:rgba(12,16,36,0.6);padding:8px 12px;border-radius:var(--radius-sm);border:1px solid var(--border);">' +
        '<input type="radio" name="active_provider_radio" value="' + pk + '" ' + checked + ' onchange="onProviderRadioChange(\'' + pk + '\')"> ' +
        '<span>' + PROVIDER_NAMES[pk] + statusTag + '</span></label>';
    }).join('');
    container.innerHTML = html;
    updateProviderUI(_selectedProvider);
  }).catch(function (e) {
    if (e.message !== 'Unauthorized') showToast('Failed to load provider config', 'err');
  });
}

function onProviderRadioChange(providerKey) {
  _selectedProvider = providerKey;
  updateProviderUI(providerKey);
  apiFetch('/v1/providers/active', {
    method: 'POST',
    body: JSON.stringify({ provider: providerKey })
  }).then(function (res) { return res.json(); }).then(function () {
    showToast('Active provider updated: ' + PROVIDER_NAMES[providerKey], 'ok');
    loadStatus();
  }).catch(function (e) {
    if (e.message !== 'Unauthorized') showToast('Failed to set active provider', 'err');
  });
}

function updateProviderUI(providerKey) {
  var keyBox = document.getElementById('provider-key-container');
  var pkceBox = document.getElementById('pkce-container');
  if (providerKey === 'openrouter_pkce') {
    keyBox.classList.add('hidden');
    pkceBox.classList.remove('hidden');
  } else {
    keyBox.classList.remove('hidden');
    pkceBox.classList.add('hidden');
  }
}

function saveProviderKey() {
  var keyInput = document.getElementById('provider-key-input');
  var val = keyInput.value.trim();
  if (!val) { showToast('Please enter an API key.', 'warn'); return; }
  if (!_selectedProvider || _selectedProvider === 'openrouter_pkce') return;

  apiFetch('/v1/providers/credentials', {
    method: 'POST',
    body: JSON.stringify({ provider: _selectedProvider, api_key: val })
  }).then(function (res) { return res.json(); }).then(function () {
    showToast('API key saved for ' + PROVIDER_NAMES[_selectedProvider], 'ok');
    keyInput.value = '';
    loadProviders();
    loadStatus();
  }).catch(function (e) {
    if (e.message !== 'Unauthorized') showToast('Failed to save API key.', 'err');
  });
}

// ── Status ────────────────────────────────────────────────────────────
function loadStatus() {
  var spinner = document.getElementById('status-loading');
  var grid = document.getElementById('status-grid');
  var dot = document.getElementById('header-status-dot');
  var txt = document.getElementById('header-status-text');
  spinner.classList.remove('hidden');
  apiFetch('/v1/status').then(function (res) { return res.json(); }).then(function (d) {
    var cards = [
      { label: 'Active Provider', value: (PROVIDER_NAMES[d.active_provider] || d.active_provider) },
      { label: 'Provider Key', value: d.provider_key_set ? '✓ Set' : '✗ Missing', cls: d.provider_key_set ? 'ok' : 'err' },
      { label: 'Sandbox Engine', value: d.sandbox_engine || '—' },
      { label: 'Sandbox Timeout', value: d.sandbox_timeout + 's' },
      { label: 'Max Iterations', value: d.max_iterations },
      { label: 'Active Sessions', value: d.active_sessions_count },
    ];
    grid.innerHTML = cards.map(function (c) {
      return '<div class="stat-card"><div class="stat-label">' + c.label + '</div><div class="stat-value ' + (c.cls || '') + '">' + c.value + '</div></div>';
    }).join('');
    document.getElementById('cred-endpoint').textContent = d.api_endpoint || '—';
    if (d.provider_key_set) { dot.className = 'status-dot ok'; txt.textContent = 'Proxy OK'; }
    else { dot.className = 'status-dot warn'; txt.textContent = 'API key missing'; }
  }).catch(function (e) {
    if (e.message !== 'Unauthorized') { dot.className = 'status-dot err'; txt.textContent = 'Error'; }
  }).finally(function () { spinner.classList.add('hidden'); });
}

// ── Sessions ──────────────────────────────────────────────────────────
function loadSessions() {
  var listEl = document.getElementById('session-list');
  listEl.innerHTML = '<div class="session-empty"><span class="spinner"></span></div>';
  apiFetch('/v1/sessions').then(function (res) { return res.json(); }).then(function (data) {
    var sessions = data.sessions || [];
    if (!sessions.length) { listEl.innerHTML = '<div class="session-empty">No active sessions.</div>'; return; }
    listEl.innerHTML = sessions.map(function (id) {
      var safeId = id.replace(/'/g, "\\'");
      return '<div class="session-item" id="si-' + id + '" onclick="selectSession(\'' + safeId + '\')">' +
        '<span class="status-dot idle"></span>' +
        '<span class="session-name">' + id + '</span></div>';
    }).join('');
  }).catch(function (e) {
    if (e.message !== 'Unauthorized') listEl.innerHTML = '<div class="session-empty">Failed to load sessions.</div>';
  });
}

function selectSession(id) {
  _currentSession = id;
  document.querySelectorAll('.session-item').forEach(function (el) { el.classList.remove('active'); });
  var item = document.getElementById('si-' + id);
  if (item) item.classList.add('active');

  var title = document.getElementById('session-panel-title');
  var body = document.getElementById('session-body');
  var actions = document.getElementById('session-actions');
  title.textContent = '🗂 Session: ' + id;
  body.innerHTML = '<span class="spinner"></span>';
  actions.classList.add('hidden');

  apiFetch('/v1/sessions/' + encodeURIComponent(id)).then(function (res) {
    if (res.status === 404) {
      body.innerHTML = '<p class="text-muted text-sm">No state found for session <code>' + id + '</code>.</p>';
      return;
    }
    return res.json().then(function (d) {
      actions.classList.remove('hidden');
      var turnsHtml = d.turns.map(function (t, i) {
        return '<div class="turn-card">' +
          '<div class="turn-header" onclick="toggleTurn(this)">' +
          '<span class="turn-idx">#' + (i + 1) + '</span>' +
          '<span class="turn-key">' + t.turn_key + '</span>' +
          '<span class="spacer"></span>' +
          '<span class="text-muted">&#9658;</span></div>' +
          '<div class="turn-body">' +
          '<div class="turn-diff">' +
          '<div class="turn-diff-col"><div class="turn-diff-label">Before</div>' +
          '<pre class="json-block" style="max-height:200px;">' + syntaxHighlight(t.before) + '</pre></div>' +
          '<div class="turn-diff-col"><div class="turn-diff-label">After</div>' +
          '<pre class="json-block" style="max-height:200px;">' + syntaxHighlight(t.after) + '</pre></div>' +
          '</div></div></div>';
      }).join('');

      body.innerHTML =
        '<div style="margin-bottom:14px;">' +
        '<div class="panel-title text-sm" style="margin-bottom:8px;">Current State (latest turn)</div>' +
        '<pre class="json-block">' + syntaxHighlight(d.current_state) + '</pre></div>' +
        '<div class="panel-title text-sm" style="margin-bottom:8px;">Turn History (' + d.turn_count + ' turn' + (d.turn_count !== 1 ? 's' : '') + ')</div>' +
        '<div class="turn-list">' + turnsHtml + '</div>';
    });
  }).catch(function (e) {
    if (e.message !== 'Unauthorized') body.innerHTML = '<p class="text-muted text-sm">Failed to load session data.</p>';
  });
}

function toggleTurn(header) {
  var body = header.nextElementSibling;
  var arrow = header.querySelector('span:last-child');
  body.classList.toggle('open');
  arrow.innerHTML = body.classList.contains('open') ? '&#9660;' : '&#9658;';
}

function resetSession() {
  if (!_currentSession) return;
  showConfirm('Reset Session', 'Clear all state history for "' + _currentSession + '"? The session ID is preserved but all turn data will be wiped.', function () {
    apiFetch('/v1/sessions/' + encodeURIComponent(_currentSession) + '/reset', { method: 'POST' }).then(function (res) {
      if (res.ok) { showToast('Session "' + _currentSession + '" reset.', 'ok'); loadSessions(); selectSession(_currentSession); }
      else { showToast('Reset failed.', 'err'); }
    }).catch(function (e) { if (e.message !== 'Unauthorized') showToast('Reset failed.', 'err'); });
  });
}

function deleteSession() {
  if (!_currentSession) return;
  showConfirm('Delete Session', 'Permanently delete all data for "' + _currentSession + '"? This cannot be undone.', function () {
    apiFetch('/v1/sessions/' + encodeURIComponent(_currentSession), { method: 'DELETE' }).then(function (res) {
      if (res.ok) {
        showToast('Session "' + _currentSession + '" deleted.', 'ok');
        _currentSession = null;
        document.getElementById('session-panel-title').textContent = '🗂 Session Inspector';
        document.getElementById('session-body').innerHTML = '<p class="text-muted text-sm">Select a session from the sidebar to inspect it.</p>';
        document.getElementById('session-actions').classList.add('hidden');
        loadSessions();
      } else { showToast('Delete failed.', 'err'); }
    }).catch(function (e) { if (e.message !== 'Unauthorized') showToast('Delete failed.', 'err'); });
  });
}

function exportSession() {
  if (!_currentSession) return;
  apiFetch('/v1/sessions/' + encodeURIComponent(_currentSession) + '/export').then(function (res) {
    if (!res.ok) { throw new Error('Failed to export session data.'); }
    return res.json();
  }).then(function (data) {
    var blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = _currentSession + '.json';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    showToast('Session "' + _currentSession + '" exported successfully.', 'ok');
  }).catch(function (e) {
    if (e.message !== 'Unauthorized') {
      showToast('Export failed: ' + e.message, 'err');
    }
  });
}

function triggerImport() {
  document.getElementById('import-file-input').click();
}

function handleImportFile(event) {
  var file = event.target.files[0];
  if (!file) return;

  var reader = new FileReader();
  reader.onload = function (e) {
    try {
      var data = JSON.parse(e.target.result);
      var defaultSessionId = file.name.replace(/\.json$/i, '');
      var sessionId = prompt('Enter a Session ID to import as:', defaultSessionId);
      if (!sessionId) return;
      sessionId = sessionId.trim();
      if (!sessionId) {
        showToast('Invalid Session ID.', 'err');
        return;
      }

      var existingItem = document.getElementById('si-' + sessionId);
      if (existingItem) {
        showConfirm('Overwrite Session', 'A session named "' + sessionId + '" already exists. Do you want to overwrite it?', function () {
          sendImportRequest(sessionId, data);
        });
      } else {
        sendImportRequest(sessionId, data);
      }
    } catch (err) {
      showToast('Invalid JSON file: ' + err.message, 'err');
    }
  };
  reader.readAsText(file);
  event.target.value = ''; // Reset
}

function sendImportRequest(sessionId, data) {
  apiFetch('/v1/sessions/' + encodeURIComponent(sessionId) + '/import', {
    method: 'POST',
    body: JSON.stringify(data)
  }).then(function (res) {
    if (!res.ok) {
      return res.json().then(function (err) {
        throw new Error(err.detail || 'Import failed.');
      });
    }
    return res.json();
  }).then(function (resData) {
    showToast('Session "' + sessionId + '" imported successfully.', 'ok');
    loadSessions();
    setTimeout(function () { selectSession(sessionId); }, 150);
  }).catch(function (e) {
    if (e.message !== 'Unauthorized') {
      showToast('Import failed: ' + e.message, 'err');
    }
  });
}

// ── Init ──────────────────────────────────────────────────────────────
function onConnected() { loadStatus(); loadProviders(); loadSessions(); }

document.getElementById('auth-submit').onclick = function () {
  var key = document.getElementById('auth-key-input').value.trim();
  if (!key) { document.getElementById('auth-error').textContent = 'Please enter a key.'; return; }
  tryConnect(key);
};
document.getElementById('auth-key-input').onkeydown = function (e) {
  if (e.key === 'Enter') document.getElementById('auth-submit').click();
};
document.getElementById('btn-save-provider-key').onclick = saveProviderKey;
document.getElementById('btn-refresh-status').onclick = function () { loadStatus(); loadProviders(); };
document.getElementById('btn-refresh-sessions').onclick = loadSessions;
document.getElementById('btn-logout').onclick = function () { showAuth(); };
document.getElementById('btn-export-session').onclick = exportSession;
document.getElementById('btn-import-session').onclick = triggerImport;
document.getElementById('import-file-input').onchange = handleImportFile;
document.getElementById('btn-reset-session').onclick = resetSession;
document.getElementById('btn-delete-session').onclick = deleteSession;

document.getElementById('btn-reveal-key').onclick = function () {
  _keyVisible = !_keyVisible;
  var el = document.getElementById('cred-key');
  var btn = document.getElementById('btn-reveal-key');
  if (_keyVisible) { el.textContent = _apiKey; el.classList.remove('masked'); btn.textContent = 'Hide'; }
  else { el.innerHTML = '&#8226;&#8226;&#8226;&#8226;&#8226;&#8226;&#8226;&#8226;&#8226;&#8226;&#8226;&#8226;&#8226;&#8226;&#8226;&#8226;'; el.classList.add('masked'); btn.textContent = 'Show'; }
};
document.getElementById('btn-copy-endpoint').onclick = function () {
  copyText(document.getElementById('cred-endpoint').textContent.trim(), this);
};
document.getElementById('btn-copy-key').onclick = function () { copyText(_apiKey, this); };

// Boot
if (_apiKey) { tryConnect(_apiKey); } else { showAuth(); }
