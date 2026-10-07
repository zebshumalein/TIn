const defaultApiBase = (() => {
  const fromWindow = window.PCDA_API_BASE;
  if (typeof fromWindow === 'string' && fromWindow.trim()) return fromWindow.trim();

  return '';
})();

const state = {
  sessionId: null,
  filename: '',
  pendingUploadId: null,
  apiBase: defaultApiBase,
};

const els = {
  fileInput: document.getElementById('file-input'),
  dropzone: document.getElementById('dropzone'),
  sampleBtn: document.getElementById('sample-btn'),
  removeBtn: document.getElementById('remove-btn'),
  chipName: document.getElementById('chip-name'),
  chipMeta: document.getElementById('chip-meta'),
  chipSources: document.getElementById('chip-sources'),
  filechip: document.getElementById('filechip'),
  preview: document.getElementById('preview'),
  previewTable: document.getElementById('preview-table'),
  uploadError: document.getElementById('upload-error'),
  accessToken: document.getElementById('access-token'),
  joinConfig: document.getElementById('join-config'),
  joinType: document.getElementById('join-type'),
  joinList: document.getElementById('join-list'),
  joinBtn: document.getElementById('join-btn'),
  promptInput: document.getElementById('prompt-input'),
  examples: document.getElementById('examples'),
  addBtn: document.getElementById('add-btn'),
  sendBtn: document.getElementById('send-btn'),
  doubleCheck: document.getElementById('double-check'),
  result: document.getElementById('result'),
  stateLoading: document.getElementById('state-loading'),
  stateVerified: document.getElementById('state-verified'),
  stateCannot: document.getElementById('state-cannot'),
  stateError: document.getElementById('state-error'),
  answerText: document.getElementById('answer-text'),
  vbadgeTitle: document.getElementById('vbadge-title'),
  vbadgeNote: document.getElementById('vbadge-note'),
  codeBlock: document.getElementById('code-block'),
  evidenceBody: document.getElementById('evidence-body'),
  evidenceNote: document.getElementById('evidence-note'),
  checkText: document.getElementById('check-text'),
  runs: document.getElementById('runs'),
  answerBody: document.getElementById('answer-body'),
  inlineAnswer: document.getElementById('inline-answer'),
  cannotReason: document.getElementById('cannot-reason'),
  cannotSuggest: document.getElementById('cannot-suggest'),
  errorText: document.getElementById('error-text'),
  copyBtn: document.getElementById('copy-btn'),
  againBtn: document.getElementById('again-btn'),
  retryBtn: document.getElementById('retry-btn'),
  srStatus: document.getElementById('sr-status'),
  menuToggle: document.getElementById('menu-toggle'),
  siteMenu: document.getElementById('site-menu'),
};

const tabIds = ['tab-answer', 'tab-code', 'tab-evidence', 'tab-check'];

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function setUploadError(message) {
  if (!message) {
    els.uploadError.hidden = true;
    els.uploadError.textContent = '';
    return;
  }
  els.uploadError.textContent = message;
  els.uploadError.hidden = false;
}

function clearUploadError() {
  setUploadError('');
}

function updateSendButton() {
  const hasQuestion = els.promptInput.value.trim().length > 0;
  els.sendBtn.disabled = !(state.sessionId && hasQuestion);
}

async function apiFetch(url, options = {}) {
  const headers = new Headers(options.headers || {});
  const token = els.accessToken.value.trim();
  if (token) headers.set('Authorization', `Bearer ${token}`);
  return fetch(url, { ...options, headers });
}

function setInlineAnswer(message, state = 'answer') {
  els.inlineAnswer.textContent = message;
  els.inlineAnswer.className = `inline-answer inline-answer--${state}`;
  els.inlineAnswer.hidden = !message;
}

function setResultState(name) {
  const states = {
    loading: els.stateLoading,
    verified: els.stateVerified,
    cannot: els.stateCannot,
    error: els.stateError,
  };

  Object.values(states).forEach((node) => {
    if (node) node.hidden = true;
  });

  els.result.hidden = false;

  if (name && states[name]) {
    const activeState = states[name];
    activeState.hidden = false;
    activeState.classList.remove('rise-in');
    void activeState.offsetWidth;
    activeState.classList.add('rise-in');
  }
}

function setSessionFromResponse(payload) {
  state.sessionId = payload.session_id;
  state.pendingUploadId = null;
  state.filename = payload.filename || 'uploaded-file';

  els.chipName.textContent = state.filename;
  const sourceNames = Array.isArray(payload.source_names) ? payload.source_names : [];
  const sourceLabel = sourceNames.length > 1 ? `${sourceNames.length} joined files • ` : '';
  els.chipMeta.textContent = `${sourceLabel}${payload.rows} rows • ${payload.columns} columns`;
  els.chipSources.textContent = sourceNames.length > 1 ? `Files: ${sourceNames.join(' · ')}` : '';
  els.chipSources.hidden = sourceNames.length < 2;
  els.filechip.hidden = false;
  els.preview.hidden = false;
  els.joinConfig.hidden = true;
  els.joinList.replaceChildren();

  const columns = Array.isArray(payload.column_names) ? payload.column_names : [];
  const previewRows = Array.isArray(payload.preview) ? payload.preview : [];
  renderTable(els.previewTable, columns, previewRows);
  renderExamples(columns, previewRows);

  clearUploadError();
  updateSendButton();
}

function addSelectOption(select, value, label) {
  const option = document.createElement('option');
  option.value = value;
  option.textContent = label;
  select.appendChild(option);
}

function updateJoinButton() {
  const selects = [...els.joinList.querySelectorAll('select')];
  els.joinBtn.disabled = !state.pendingUploadId
    || selects.length === 0
    || selects.some((select) => !select.value);
}

function showJoinConfig(payload) {
  state.pendingUploadId = payload.upload_id;
  els.filechip.hidden = true;
  els.preview.hidden = true;
  els.joinList.replaceChildren();

  const base = payload.files[0];
  payload.files.slice(1).forEach((file, index) => {
    const fileIndex = index + 1;
    const fieldset = document.createElement('fieldset');
    fieldset.className = 'join-pair';
    const legend = document.createElement('legend');
    legend.textContent = `${base.filename} (${base.rows} rows) ↔ ${file.filename} (${file.rows} rows)`;
    fieldset.appendChild(legend);

    const leftLabel = document.createElement('label');
    leftLabel.textContent = `Column in ${base.filename}`;
    const leftSelect = document.createElement('select');
    leftSelect.dataset.fileIndex = String(fileIndex);
    leftSelect.dataset.side = 'left';
    addSelectOption(leftSelect, '', 'Choose a column');
    base.column_names.forEach((column) => addSelectOption(leftSelect, column, column));
    leftLabel.appendChild(leftSelect);

    const rightLabel = document.createElement('label');
    rightLabel.textContent = `Matching column in ${file.filename}`;
    const rightSelect = document.createElement('select');
    rightSelect.dataset.fileIndex = String(fileIndex);
    rightSelect.dataset.side = 'right';
    addSelectOption(rightSelect, '', 'Choose a column');
    file.column_names.forEach((column) => addSelectOption(rightSelect, column, column));
    rightLabel.appendChild(rightSelect);

    const sharedColumn = base.column_names.find((column) => file.column_names.includes(column));
    if (sharedColumn) {
      leftSelect.value = sharedColumn;
      rightSelect.value = sharedColumn;
    }

    fieldset.append(leftLabel, rightLabel);
    els.joinList.appendChild(fieldset);
  });

  els.joinConfig.hidden = false;
  els.joinBtn.textContent = `Join ${payload.files.length} files`;
  updateJoinButton();
}

function renderExamples(columns, rows) {
  if (!els.examples) return;

  const numericColumns = columns.filter((column) => {
    const values = rows.map((row) => row[column]).filter((value) => value != null && value !== '');
    return values.length > 0 && values.every((value) => Number.isFinite(Number(value)));
  });
  const numericColumn = numericColumns.find((column) => /revenue|sales|amount|value|price|total|profit|cost/i.test(column))
    || numericColumns[0];
  const dateColumn = columns.find((column) => /date|time|month|year/i.test(column));
  const categoryColumn = columns.find((column) => (
    column !== numericColumn && column !== dateColumn
  ));
  const questions = ['How many rows are in my data?'];

  if (numericColumn) {
    questions.push(`What is the total ${numericColumn}?`);
    if (categoryColumn) {
      questions.push(`Which ${categoryColumn} has the highest ${numericColumn}?`);
    } else if (dateColumn) {
      questions.push(`How did ${numericColumn} change over time?`);
    }
  }

  if (questions.length < 3) {
    const columnList = columns.slice(0, 3).join(', ');
    questions.push(
      columnList ? `What can you tell me about ${columnList}?` : 'Summarize my data',
    );
    questions.push(columnList ? `Show the columns in my data: ${columnList}` : 'Summarize my data');
  }

  els.examples.replaceChildren();
  questions.slice(0, 3).forEach((question) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'chip';
    button.textContent = question;
    els.examples.appendChild(button);
  });
}

function renderTable(table, columns, rows) {
  table.innerHTML = '';

  if (!columns.length || !rows.length) {
    const row = document.createElement('tr');
    const cell = document.createElement('td');
    cell.textContent = 'No preview available';
    row.appendChild(cell);
    table.appendChild(row);
    return;
  }

  const thead = document.createElement('thead');
  const headRow = document.createElement('tr');
  columns.forEach((col) => {
    const th = document.createElement('th');
    th.textContent = col;
    headRow.appendChild(th);
  });
  thead.appendChild(headRow);
  table.appendChild(thead);

  const tbody = document.createElement('tbody');
  rows.forEach((row) => {
    const tr = document.createElement('tr');
    columns.forEach((col) => {
      const td = document.createElement('td');
      const value = row[col];
      td.textContent = value == null ? '—' : String(value);
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
}

async function loadSampleData() {
  const response = await apiFetch(`${state.apiBase}/api/sample`);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || 'Sample data could not be loaded.');
  }

  setSessionFromResponse(payload);
  setUploadError('');
}

function renderEvidence(data, columns) {
  const content = Array.isArray(data) ? data : [];
  const header = Array.isArray(columns) && columns.length ? columns : ['value'];
  if (!content.length) {
    els.evidenceBody.innerHTML = '<p class="note">No evidence rows were returned.</p>';
    return;
  }

  const table = document.createElement('table');
  table.className = 'table-wrap table-wrap--small';

  const thead = document.createElement('thead');
  const headRow = document.createElement('tr');
  header.forEach((col) => {
    const th = document.createElement('th');
    th.textContent = col;
    headRow.appendChild(th);
  });
  thead.appendChild(headRow);
  table.appendChild(thead);

  const tbody = document.createElement('tbody');
  content.forEach((row) => {
    const tr = document.createElement('tr');
    header.forEach((col) => {
      const td = document.createElement('td');
      const value = row[col];
      td.textContent = value == null ? '—' : String(value);
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);

  els.evidenceBody.innerHTML = '';
  els.evidenceBody.appendChild(table);
}

function renderRuns(runs) {
  if (!Array.isArray(runs) || !runs.length) {
    els.runs.innerHTML = '<p class="note">No run details were returned.</p>';
    return;
  }

  const html = runs
    .map((run, index) => {
      const display = run.display ?? 'No display output';
      const result = run.result ?? {};
      const resultText = typeof result === 'object' ? JSON.stringify(result, null, 2) : String(result);
      return `
        <div class="run">
          <p class="run__label">Run ${index + 1}</p>
          <p class="run__display">${escapeHtml(display)}</p>
          <pre class="run__result">${escapeHtml(resultText)}</pre>
        </div>
      `;
    })
    .join('');

  els.runs.innerHTML = html;
}

async function askQuestion() {
  const question = els.promptInput.value.trim();
  if (!question) {
    setUploadError('Please type a question first.');
    return;
  }

  if (!state.sessionId) {
    setUploadError('Upload a file or use the sample data first.');
    return;
  }

  setInlineAnswer('Working on your question...', 'loading');
  setResultState('loading');
  els.srStatus.textContent = 'Working on your question';

  try {
    const response = await apiFetch(`${state.apiBase}/api/ask`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: state.sessionId,
        question,
        double_check: els.doubleCheck.checked,
      }),
    });

    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.detail || 'The server could not answer that question.');
    }

    if (payload.status === 'verified' || payload.status === 'answered') {
      els.answerText.textContent = payload.answer_text || 'Answer';
      els.answerBody.innerHTML = `<p class="answer__value">${escapeHtml(payload.answer_text || '')}</p>`;
      setInlineAnswer(
        `${payload.answer_text || 'Answer'}${payload.status === 'verified' ? ' - verified' : ''}`,
        'success',
      );
      els.vbadgeTitle.textContent = payload.status === 'verified' ? 'Verified ✓' : 'Answered';
      els.vbadgeNote.textContent = payload.status === 'verified'
        ? 'Two independent runs matched'
        : 'Single run mode';
      els.codeBlock.textContent = payload.code || '';
      els.evidenceNote.textContent = payload.evidence_total_rows
        ? `${payload.evidence_total_rows} evidence rows were used.`
        : 'No evidence rows were returned.';
      renderEvidence(payload.evidence || [], payload.evidence_columns || []);
      renderRuns(payload.runs || []);
      els.checkText.textContent = payload.reason || 'The calculation was checked successfully.';
      setResultState('verified');
      els.srStatus.textContent = payload.status === 'verified' ? 'Answer verified' : 'Answer returned';
      switchTab('tab-answer');
      return;
    }

    if (payload.status === 'cannot_prove') {
      els.cannotReason.textContent = payload.reason || 'This question cannot be proven from the current data.';
      setInlineAnswer(els.cannotReason.textContent, 'notice');
      const suggestions = Array.isArray(payload.suggestions) ? payload.suggestions : [];
      els.cannotSuggest.innerHTML = suggestions.length
        ? `<ul>${suggestions.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul>`
        : '<p class="note">Try a different question about the current dataset.</p>';
      setResultState('cannot');
      els.srStatus.textContent = 'Unable to prove the answer';
      return;
    }

    throw new Error(payload.reason || 'The server returned an unsupported result.');
  } catch (error) {
    els.errorText.textContent = error.message || 'Something went wrong while processing your question.';
    setInlineAnswer(els.errorText.textContent, 'error');
    setResultState('error');
    els.srStatus.textContent = 'There was an error';
  }
}

function switchTab(tabId) {
  tabIds.forEach((id) => {
    const tab = document.getElementById(id);
    const panel = document.getElementById(id.replace('tab-', 'panel-'));

    if (!tab || !panel) return;
    const active = id === tabId;
    tab.setAttribute('aria-selected', String(active));
    tab.tabIndex = active ? 0 : -1;
    panel.hidden = !active;
  });
}

async function handleFileSelection(files) {
  const selectedFiles = Array.from(files || []);
  if (!selectedFiles.length) return;
  if (selectedFiles.length > 5) {
    setUploadError('You can combine up to 5 files at a time.');
    return;
  }
  if (selectedFiles.some((file) => !['.csv', '.xlsx', '.xls'].includes(`.${file.name.split('.').pop().toLowerCase()}`))) {
    setUploadError('Please select only CSV or Excel files.');
    return;
  }
  if (selectedFiles.some((file) => file.size > 10 * 1024 * 1024)
    || selectedFiles.reduce((total, file) => total + file.size, 0) > 20 * 1024 * 1024) {
    setUploadError('Each file must be under 10 MB and the combined upload under 20 MB.');
    return;
  }

  try {
    clearUploadError();
    state.sessionId = null;
    state.pendingUploadId = null;
    state.filename = '';
    els.filechip.hidden = true;
    els.preview.hidden = true;
    els.joinConfig.hidden = true;
    updateSendButton();
    const formData = new FormData();
    selectedFiles.forEach((file) => formData.append('files', file));
    const response = await apiFetch(`${state.apiBase}/api/upload`, { method: 'POST', body: formData });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || 'Upload failed.');
    if (payload.needs_join) showJoinConfig(payload);
    else setSessionFromResponse(payload);
  } catch (error) {
    setUploadError(error.message || 'The file could not be uploaded.');
  }
}

function bindEvents() {
  if (els.examples) {
    els.examples.addEventListener('click', (event) => {
      const button = event.target.closest('.chip');
      if (!button) return;
      els.promptInput.value = button.textContent || '';
      updateSendButton();
      els.promptInput.focus();
    });
  }

  els.fileInput.addEventListener('change', (event) => {
    handleFileSelection(event.target.files);
    event.target.value = '';
  });

  els.addBtn.addEventListener('click', () => els.fileInput.click());
  els.dropzone.addEventListener('click', () => els.fileInput.click());
  els.dropzone.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      els.fileInput.click();
    }
  });

  els.dropzone.addEventListener('dragover', (event) => {
    event.preventDefault();
    els.dropzone.classList.add('is-dragover');
  });

  els.dropzone.addEventListener('dragleave', () => {
    els.dropzone.classList.remove('is-dragover');
  });

  els.dropzone.addEventListener('drop', (event) => {
    event.preventDefault();
    els.dropzone.classList.remove('is-dragover');
    handleFileSelection(event.dataTransfer && event.dataTransfer.files);
  });

  els.joinList.addEventListener('change', updateJoinButton);
  els.joinBtn.addEventListener('click', async () => {
    if (!state.pendingUploadId) return;
    const pairs = new Map();
    els.joinList.querySelectorAll('select').forEach((select) => {
      const fileIndex = Number(select.dataset.fileIndex);
      const pair = pairs.get(fileIndex) || {};
      pair[select.dataset.side === 'left' ? 'left_on' : 'right_on'] = select.value;
      pairs.set(fileIndex, pair);
    });
    els.joinBtn.disabled = true;
    clearUploadError();
    try {
      const response = await apiFetch(`${state.apiBase}/api/join`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          upload_id: state.pendingUploadId,
          how: els.joinType.value,
          joins: [...pairs.values()],
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || 'The files could not be joined.');
      setSessionFromResponse(payload);
    } catch (error) {
      setUploadError(error.message || 'The files could not be joined.');
      updateJoinButton();
    }
  });

  els.sampleBtn.addEventListener('click', async () => {
    state.sessionId = null;
    state.pendingUploadId = null;
    els.filechip.hidden = true;
    els.preview.hidden = true;
    els.joinConfig.hidden = true;
    updateSendButton();
    try {
      await loadSampleData();
    } catch (error) {
      setUploadError(error.message || 'Sample data could not be loaded.');
    }
  });

  els.removeBtn.addEventListener('click', () => {
    state.sessionId = null;
    state.pendingUploadId = null;
    state.filename = '';
    els.filechip.hidden = true;
    els.preview.hidden = true;
    els.joinConfig.hidden = true;
    els.joinList.replaceChildren();
    els.previewTable.innerHTML = '';
    els.promptInput.value = '';
    updateSendButton();
  });

  els.promptInput.addEventListener('input', updateSendButton);

  document.getElementById('try').addEventListener('submit', (event) => {
    event.preventDefault();
    askQuestion();
  });

  els.copyBtn.addEventListener('click', async () => {
    const text = els.codeBlock.textContent || '';
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      els.copyBtn.textContent = 'Copied';
      setTimeout(() => {
        els.copyBtn.textContent = 'Copy';
      }, 1200);
    } catch (_error) {
      els.copyBtn.textContent = 'Copy failed';
    }
  });

  els.againBtn.addEventListener('click', () => {
    els.promptInput.value = '';
    els.result.hidden = true;
    setInlineAnswer('');
    updateSendButton();
  });

  els.retryBtn.addEventListener('click', () => {
    askQuestion();
  });

  tabIds.forEach((id) => {
    const button = document.getElementById(id);
    if (!button) return;
    button.addEventListener('click', () => switchTab(id));
  });

  if (els.menuToggle && els.siteMenu) {
    els.menuToggle.addEventListener('click', () => {
      const expanded = els.menuToggle.getAttribute('aria-expanded') === 'true';
      els.menuToggle.setAttribute('aria-expanded', String(!expanded));
      document.body.classList.toggle('menu-open', !expanded);
      els.siteMenu.classList.toggle('is-open', !expanded);
      els.menuToggle.setAttribute('aria-label', expanded ? 'Open menu' : 'Close menu');
    });

    els.siteMenu.querySelectorAll('a').forEach((link) => {
      link.addEventListener('click', () => {
        els.menuToggle.setAttribute('aria-expanded', 'false');
        els.menuToggle.setAttribute('aria-label', 'Open menu');
        document.body.classList.remove('menu-open');
        els.siteMenu.classList.remove('is-open');
      });
    });
  }
}

function initScrollReveals() {
  const revealItems = [...document.querySelectorAll('.reveal')];
  if (!revealItems.length) return;

  const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
  if (reduceMotion || !window.IntersectionObserver) {
    revealItems.forEach((item) => item.classList.add('in'));
    return;
  }

  const observer = new window.IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;
      entry.target.classList.add('in');
      observer.unobserve(entry.target);
    });
  }, { threshold: 0.12, rootMargin: '0px 0px -32px 0px' });

  revealItems.forEach((item) => {
    const bounds = item.getBoundingClientRect();
    if (bounds.top < window.innerHeight && bounds.bottom > 0) {
      item.classList.add('in');
    } else {
      observer.observe(item);
    }
  });
  document.documentElement.classList.add('js');
}

window.addEventListener('DOMContentLoaded', () => {
  bindEvents();
  initScrollReveals();
  updateSendButton();
  els.result.hidden = true;
  setInlineAnswer('');
  els.filechip.hidden = true;
  els.preview.hidden = true;

  const auroraContainer = document.querySelector('.hero__bg');
  if (auroraContainer) {
    import('./soft-aurora.js')
      .then(({ initSoftAurora }) => initSoftAurora(auroraContainer, {
        color1: '#86efac',
        color2: '#16a34a',
        scale: 1.2,
        bandSpread: 0.55,
        lightMode: false,
      }))
      .catch((error) => {
        console.error('Aurora background failed to load; the app remains available.', error);
      });
  }
});
