const state = {
  backendUrl: null,
  currentView: 'home',
  config: null,
  configSaveTimer: null,
  colorMode: 'auto',
  resetConfigInProgress: false,
  addInstrumentMenuCloseTimer: null,
  instruments: [],
  instances: {},
  activeInstanceId: '',
  launcherActionInstanceId: '',
  renamingInstrumentId: '',
  renameInstrumentSaving: false,
  dmmOptions: null,
  wlmOptions: null,
  connectionCheckingIds: new Set(),
  opmOptions: null,
  ufc: {
    ...waveformRuntimeFields(),
    running: false,
    frequencyValues: [],
    frequencyStartIndex: 0,
    frequencyBreakIndices: [],
    maxFrequencyPoints: 20000,
    frequencyDisplayScale: 1_000_000,
    frequencyDisplayUnit: 'MHz',
    frequencyChart: null,
    adevChart: null,
    frequencyNoiseChart: null
  },
  dmm: {
    ...waveformRuntimeFields(),
    running: false,
    trendChart: null,
    adevChart: null,
    values: [],
    maxPoints: 20000,
    unit: 'V'
  },
  wlm: {
    ...waveformRuntimeFields(),
    running: false,
    trendChart: null,
    adevChart: null,
    values: [],
    maxPoints: 20000
  },
  opm: {
    ...waveformRuntimeFields(),
    running: false,
    trendChart: null,
    adevChart: null,
    powerValuesW: [],
    adevPointsW: [],
    maxPoints: 20000,
    displayUnit: 'mW'
  },
  devices: {
    items: [],
    selectedId: '',
    loading: false,
    warnings: [],
    error: ''
  },
  library: {
    items: [],
    selectedFile: '',
    pendingDeleteFile: '',
    deleteInProgress: false,
    waveformChart: null,
    adevChart: null
  }
};

const $ = (id) => document.getElementById(id);
const SPEED_OF_LIGHT_M_S = 299792458;
const WLM_USB_RESOURCE = '10.199.199.1:23';
const FULL_WAVEFORM_REFRESH_MS = 2000;

const waveformUi = {
  ufc: { recentTab: 'ufcRecentWaveformTab', fullTab: 'ufcFullWaveformTab', panel: 'ufcWaveformPanel', status: 'ufcFullWaveformStatus' },
  dmm: { recentTab: 'dmmRecentWaveformTab', fullTab: 'dmmFullWaveformTab', panel: 'dmmWaveformPanel', status: 'dmmFullWaveformStatus' },
  wlm: { recentTab: 'wlmRecentWaveformTab', fullTab: 'wlmFullWaveformTab', panel: 'wlmWaveformPanel', status: 'wlmFullWaveformStatus' },
  opm: { recentTab: 'opmRecentWaveformTab', fullTab: 'opmFullWaveformTab', panel: 'opmWaveformPanel', status: 'opmFullWaveformStatus' }
};

function waveformRuntimeFields() {
  return {
    runPath: '',
    waveformTab: 'recent',
    fullWaveformPoints: [],
    fullWaveformTimer: null,
    fullWaveformBusy: false,
    fullWaveformRevision: 0,
    fullWaveformStatus: ''
  };
}

const instrumentTypeMeta = {
  ufc: {
    title: 'UNIVERSAL FREQUENCY COUNTER',
    htmlTitle: 'UNIVERSAL<br />FREQUENCY<br />COUNTER',
    icon: '../node_modules/lucide-static/icons/activity.svg',
    logoClass: 'ufc-logo'
  },
  dmm: {
    title: 'DIGITAL MULTIMETER',
    htmlTitle: 'DIGITAL<br />MULTIMETER',
    icon: '../node_modules/lucide-static/icons/gauge.svg',
    logoClass: 'dmm-logo'
  },
  wlm: {
    title: 'WAVELENGTH METER',
    htmlTitle: 'WAVELENGTH<br />METER',
    icon: '../node_modules/lucide-static/icons/waves.svg',
    logoClass: 'wlm-logo'
  },
  opm: {
    title: 'OPTICAL POWER METER',
    htmlTitle: 'OPTICAL<br />POWER<br />METER',
    icon: '../node_modules/lucide-static/icons/sun.svg',
    logoClass: 'opm-logo'
  }
};

function createRuntime(item) {
  const base = {
    id: item.id,
    type: item.type,
    display_name: item.display_name || '',
    settings: item.settings || {},
    running: Boolean(item.running),
    pendingAction: null,
    badge: item.running ? 'BUSY' : 'OFFLINE',
    statusText: item.running ? 'Acquisition running' : 'Offline',
    statusSeverity: 'info',
    launcherValue: '--'
  };
  if (item.type === 'ufc') {
    return {
      ...base,
      ...waveformRuntimeFields(),
      frequencyValues: [],
      frequencyStartIndex: 0,
      frequencyBreakIndices: [],
      maxFrequencyPoints: 20000,
      frequencyDisplayScale: 1_000_000,
      frequencyDisplayUnit: 'MHz',
      frequencyChart: state.ufc.frequencyChart,
      adevChart: state.ufc.adevChart,
      frequencyNoiseChart: state.ufc.frequencyNoiseChart,
      fnPoints: [],
      fnStatus: '',
      frequencyMetric: '--',
      frequencyUnit: 'MHz',
      sampleRateMetric: '--',
      elapsedMetric: '0.0',
      adevMetric: '--'
    };
  }
  if (item.type === 'dmm') {
    return {
      ...base,
      ...waveformRuntimeFields(),
      trendChart: state.dmm.trendChart,
      adevChart: state.dmm.adevChart,
      values: [],
      maxPoints: 20000,
      unit: 'V',
      valueMetric: '--',
      minMetric: '--',
      maxMetric: '--',
      avgMetric: '--',
      sampleRateMetric: '--'
    };
  }
  if (item.type === 'wlm') {
    return {
      ...base,
      ...waveformRuntimeFields(),
      trendChart: state.wlm.trendChart,
      adevChart: state.wlm.adevChart,
      values: [],
      adevPoints: [],
      maxPoints: 20000,
      valueMetric: '--',
      minMetric: '--',
      maxMetric: '--',
      avgMetric: '--',
      sampleRateMetric: '--',
      acquisitionName: ''
    };
  }
  if (item.type === 'opm') {
    return {
      ...base,
      ...waveformRuntimeFields(),
      trendChart: state.opm.trendChart,
      adevChart: state.opm.adevChart,
      powerValuesW: [],
      adevPointsW: [],
      statsW: null,
      maxPoints: 20000,
      displayUnit: item.settings?.display_unit || 'mW',
      valueMetric: '--',
      minMetric: '--',
      maxMetric: '--',
      avgMetric: '--',
      sampleRateMetric: '--',
      driverUnavailable: false,
      driverError: ''
    };
  }
  throw new Error(`Unsupported instrument type: ${item.type}`);
}

function upsertRuntime(item) {
  const existing = state.instances[item.id];
  if (!existing) {
    state.instances[item.id] = createRuntime(item);
  } else {
    existing.settings = item.settings || existing.settings || {};
    if (!existing.pendingAction) existing.running = Boolean(item.running || existing.running);
    if (Object.prototype.hasOwnProperty.call(item, 'display_name')) existing.display_name = item.display_name || '';
  }
  return state.instances[item.id];
}

function activeInstance() {
  return state.instances[state.activeInstanceId] || null;
}

function waveformChartFor(instance) {
  if (instance.type === 'ufc') return instance.frequencyChart || state.ufc.frequencyChart;
  return instance.trendChart || state[instance.type]?.trendChart;
}

function waveformRecentPoints(instance) {
  if (instance.type === 'ufc') {
    const sampleRate = Number(instance.settings?.sample_rate_hz || $('sampleRate')?.value || 1000);
    return ufcWaveformPoints(instance, sampleRate);
  }
  if (instance.type === 'dmm') return instance.values || [];
  if (instance.type === 'wlm') return instance.values || [];
  return (instance.powerValuesW || []).map((point) => ({
    x: point.x,
    y: powerValueForDisplay(point.y, currentOpmDisplayUnit(instance))
  }));
}

function waveformFullPoints(instance) {
  const scale = instance.type === 'ufc'
    ? (instance.frequencyDisplayScale || 1_000_000)
    : instance.type === 'dmm'
      ? currentDmmScaleAndUnit(instance).scale
      : 1;
  const displayUnit = instance.type === 'opm' ? currentOpmDisplayUnit(instance) : '';
  return (instance.fullWaveformPoints || []).map((point) => {
    const x = Number(point?.x);
    if (!Number.isFinite(x)) return null;
    if (point?.y === null) return { x, y: null };
    const raw = Number(point?.y);
    if (!Number.isFinite(raw)) return null;
    const y = instance.type === 'opm'
      ? powerValueForDisplay(raw, displayUnit)
      : instance.type === 'ufc' ? raw / scale : raw * scale;
    return y === null || Number.isFinite(y) ? { x, y } : null;
  }).filter(Boolean);
}

function waveformPointsForInstance(instance) {
  return instance.waveformTab === 'full' ? waveformFullPoints(instance) : waveformRecentPoints(instance);
}

function waveformYAxisTitle(instance) {
  if (instance.type === 'ufc') return instance.frequencyDisplayUnit || 'MHz';
  if (instance.type === 'dmm') return currentDmmScaleAndUnit(instance).unit;
  if (instance.type === 'wlm') return 'nm';
  return currentOpmDisplayUnit(instance);
}

function syncWaveformTabs(instance) {
  const ui = waveformUi[instance.type];
  if (!ui) return;
  const selected = instance.waveformTab === 'full' ? 'full' : 'recent';
  $(ui.recentTab)?.setAttribute('aria-selected', String(selected === 'recent'));
  $(ui.fullTab)?.setAttribute('aria-selected', String(selected === 'full'));
  if ($(ui.recentTab)) $(ui.recentTab).tabIndex = selected === 'recent' ? 0 : -1;
  if ($(ui.fullTab)) $(ui.fullTab).tabIndex = selected === 'full' ? 0 : -1;
  $(ui.panel)?.setAttribute('aria-labelledby', selected === 'full' ? ui.fullTab : ui.recentTab);
}

function syncWaveformStatus(instance) {
  const status = $(waveformUi[instance.type]?.status);
  if (!status) return;
  status.textContent = instance.fullWaveformStatus || '';
  status.hidden = !instance.fullWaveformStatus;
  status.dataset.severity = instance.fullWaveformStatus ? 'warning' : 'info';
}

function syncWaveformChart(instance) {
  if (state.activeInstanceId !== instance.id || state[instance.type] !== instance) return;
  const chart = waveformChartFor(instance);
  if (!chart) return;
  const points = waveformPointsForInstance(instance);
  chart.data.datasets[0].data = points;
  chart.options.scales.y.title.text = waveformYAxisTitle(instance);
  if (points.length) {
    chart.options.scales.x.min = points[0].x;
    chart.options.scales.x.max = points[points.length - 1].x;
  } else {
    delete chart.options.scales.x.min;
    delete chart.options.scales.x.max;
  }
  chart.update('none');
  syncWaveformTabs(instance);
  syncWaveformStatus(instance);
}

function fullWaveformRefreshAllowed(instance) {
  return Boolean(instance?.runPath)
    && state.activeInstanceId === instance.id
    && state.currentView === instance.type
    && instance.waveformTab === 'full';
}

function scheduleFullWaveformRefresh(instance, immediate = false) {
  if (!fullWaveformRefreshAllowed(instance)) return;
  if (instance.fullWaveformTimer) {
    if (!immediate) return;
    clearTimeout(instance.fullWaveformTimer);
  }
  instance.fullWaveformTimer = setTimeout(() => {
    instance.fullWaveformTimer = null;
    refreshFullWaveform(instance);
  }, immediate ? 0 : FULL_WAVEFORM_REFRESH_MS);
}

async function refreshFullWaveform(instance) {
  if (!fullWaveformRefreshAllowed(instance)) return;
  if (instance.fullWaveformBusy) {
    return;
  }
  const revision = instance.fullWaveformRevision || 0;
  const file = instance.runPath;
  instance.fullWaveformBusy = true;
  if (!instance.fullWaveformPoints.length) {
    instance.fullWaveformStatus = 'Loading full waveform…';
    syncWaveformStatus(instance);
  }
  try {
    const result = await api(`/api/library/waveform?file=${encodeURIComponent(file)}`);
    if (revision !== (instance.fullWaveformRevision || 0) || file !== instance.runPath || !fullWaveformRefreshAllowed(instance)) return;
    instance.fullWaveformPoints = Array.isArray(result.waveform?.points)
      ? result.waveform.points
      : [];
    instance.fullWaveformStatus = '';
    syncWaveformChart(instance);
  } catch (error) {
    if (revision !== (instance.fullWaveformRevision || 0) || file !== instance.runPath || !fullWaveformRefreshAllowed(instance)) return;
    instance.fullWaveformStatus = `Full waveform unavailable: ${error.message}`;
    syncWaveformStatus(instance);
  } finally {
    instance.fullWaveformBusy = false;
    if (fullWaveformRefreshAllowed(instance)) {
      scheduleFullWaveformRefresh(instance);
    }
  }
}

function resetFullWaveform(instance, selectRecent = true) {
  const busy = Boolean(instance.fullWaveformBusy);
  clearTimeout(instance.fullWaveformTimer);
  instance.fullWaveformTimer = null;
  instance.fullWaveformBusy = busy;
  instance.fullWaveformRevision = (instance.fullWaveformRevision || 0) + 1;
  instance.fullWaveformPoints = [];
  instance.fullWaveformStatus = '';
  if (selectRecent) instance.waveformTab = 'recent';
  syncWaveformChart(instance);
}

function selectWaveformTab(instance, tab) {
  if (!instance) return;
  instance.waveformTab = tab === 'full' ? 'full' : 'recent';
  if (instance.waveformTab === 'recent') instance.fullWaveformStatus = '';
  syncWaveformChart(instance);
  if (instance.waveformTab === 'full') {
    scheduleFullWaveformRefresh(instance, true);
  } else {
    clearTimeout(instance.fullWaveformTimer);
    instance.fullWaveformTimer = null;
  }
}

function setBadge(text) {
  const badgeElement = $('connectionBadge');
  badgeElement.textContent = text;
  badgeElement.classList.remove('offline', 'ready', 'busy');
  badgeElement.classList.add(text.toLowerCase());
}

function setView(view) {
  const previous = activeInstance();
  if (previous && view !== previous.type) {
    clearTimeout(previous.fullWaveformTimer);
    previous.fullWaveformTimer = null;
  }
  state.currentView = view;
  if (view !== 'home') state.launcherActionInstanceId = '';
  document.body.classList.toggle('home-view', view === 'home');
  document.body.classList.toggle('subapp-view', ['ufc', 'dmm', 'wlm', 'opm', 'library', 'devices'].includes(view));
  document.body.classList.toggle('library-view-body', view === 'library' || view === 'devices');
  document.querySelectorAll('.view').forEach((element) => {
    element.classList.toggle('active', element.dataset.view === view);
  });
  setBadge(['ufc', 'dmm', 'wlm', 'opm'].includes(view) ? activeInstance()?.badge || 'OFFLINE' : 'OFFLINE');
  document.querySelector('.app-shell')?.scrollTo({ top: 0 });
  syncTitleBarScrollState();
  if (['ufc', 'dmm', 'wlm', 'opm'].includes(view)) {
    scheduleFullWaveformRefresh(activeInstance(), true);
  }
  if (view === 'library') loadLibrary().catch((error) => reportLibraryError('Could not load Library', error));
  if (view === 'devices') loadDevices();
}

function activateInstance(instanceId) {
  const instance = state.instances[instanceId];
  if (!instance) return;
  state.activeInstanceId = instanceId;
  if (instance.type === 'ufc') {
    state.ufc = instance;
    applyUfcSettings(instance.settings || {});
    renderUfcInstance();
  } else if (instance.type === 'dmm') {
    state.dmm = instance;
    applyDmmSettings(instance.settings || {});
    renderDmmInstance();
  } else if (instance.type === 'wlm') {
    state.wlm = instance;
    $('wlmAcquisitionName').value = instance.acquisitionName || '';
    applyWlmSettings(instance.settings || {});
    renderWlmInstance();
  } else if (instance.type === 'opm') {
    state.opm = instance;
    applyOpmSettings(instance.settings || {});
    renderOpmInstance();
  }
  if (state.currentView === instance.type) setBadge(instance.badge);
}

function refreshActiveInstanceOptions() {
  const instance = activeInstance();
  if (!instance) return;
  const actions = {
    ufc: refreshResources,
    dmm: () => loadDmmOptions().then(refreshDmmResources),
    wlm: loadWlmOptions,
    opm: () => loadOpmOptions().then(refreshOpmResources)
  };
  runInstrumentAction(instance, 'Could not load instrument resources', actions[instance.type]);
}

function openInstrumentInstance(instanceId) {
  const instance = state.instances[instanceId];
  if (!instance) return;
  activateInstance(instanceId);
  setView(instance.type);
  refreshActiveInstanceOptions();
}

function navigateHome() {
  if (state.currentView !== 'home') setView('home');
}

function runningAcquisitions() {
  return state.instruments
    .map((item) => state.instances[item.id])
    .filter((instance) => instance?.running || instance?.pendingAction);
}

function runningAcquisitionShortcutHtml(instance) {
  const meta = instrumentTypeMeta[instance.type];
  const status = instance.statusText || 'Acquisition running';
  return `
    <button class="running-acquisition-shortcut" type="button" data-running-instance="${escapeHtml(instance.id)}">
      <img src="${meta.icon}" alt="" />
      <span>
        <strong>${escapeHtml(meta.title)}</strong>
        <span>${escapeHtml(status)}</span>
      </span>
      <em>Open</em>
    </button>
  `;
}

function openRunningAcquisition(instanceId) {
  const instance = state.instances[instanceId];
  if (!instance) return;
  const dialog = $('runningAcquisitionsDialog');
  if (dialog?.open) closeModal(dialog);
  activateInstance(instanceId);
  setView(instance.type);
  refreshActiveInstanceOptions();
}

function showRunningAcquisitionsDialog(items) {
  const dialog = $('runningAcquisitionsDialog');
  const list = $('runningAcquisitionShortcuts');
  if (!dialog || !list) return;
  list.innerHTML = items.map(runningAcquisitionShortcutHtml).join('');
  dialog.classList.remove('closing');
  if (!dialog.open) dialog.showModal();
}

function handleCloseRequested() {
  const items = runningAcquisitions();
  if (!items.length) {
    window.openUfc.allowCloseWindow();
    return;
  }
  showRunningAcquisitionsDialog(items);
}

function statusKindToBadge(kind) {
  if (kind === 'connected') return 'READY';
  if (['running', 'stopping', 'warning'].includes(kind)) return 'BUSY';
  return 'OFFLINE';
}

function waveformPoints(values, width = 100, height = 46) {
  const clean = values.map(Number).filter(Number.isFinite);
  if (!clean.length) return '';
  const min = Math.min(...clean);
  const max = Math.max(...clean);
  const span = max - min || 1;
  const denominator = Math.max(clean.length - 1, 1);
  return clean.map((value, index) => {
    const x = (index / denominator) * width;
    const y = height - ((value - min) / span) * (height - 8) - 4;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  }).join(' ');
}

function syncLauncherStatus() {
  const grid = $('launcherGrid');
  if (!grid) return;
  const cards = Array.from(grid.querySelectorAll('.launcher-card'));
  if (cards.length !== state.instruments.length) {
    renderLauncherCards();
    return;
  }
  for (const item of state.instruments) {
    const instance = state.instances[item.id] || item;
    const card = cards.find((candidate) => candidate.dataset.instanceId === instance.id);
    if (!card) {
      renderLauncherCards();
      return;
    }
    const actionsOpen = state.launcherActionInstanceId === instance.id;
    card.classList.toggle('homepage-running', Boolean(instance.running));
    card.classList.toggle('launcher-actions-open', actionsOpen);
    const actions = card.querySelector('.launcher-card-actions');
    actions?.setAttribute('aria-hidden', String(!actionsOpen));
    actions?.querySelectorAll('.launcher-action-button').forEach((button) => {
      button.tabIndex = actionsOpen ? 0 : -1;
    });
    const deleteButton = actions?.querySelector('[data-delete-instance]');
    if (deleteButton) {
      const deleteLabel = instance.running || instance.pendingAction
        ? 'Stop acquisition before deleting this instrument'
        : 'Delete instrument';
      deleteButton.disabled = Boolean(instance.running || instance.pendingAction);
      deleteButton.setAttribute('aria-label', deleteLabel);
      deleteButton.title = deleteLabel;
    }
    const liveValue = card.querySelector('.launcher-live-value');
    if (liveValue) liveValue.textContent = instance.running ? instance.launcherValue || '--' : '--';
    let values = [];
    if (instance.type === 'ufc') values = instance.frequencyValues || [];
    else if (instance.type === 'dmm') values = (instance.values || []).map((point) => point.y);
    else if (instance.type === 'wlm') values = (instance.values || []).map((point) => point.y);
    else if (instance.type === 'opm') values = (instance.powerValuesW || []).map((point) => point.y);
    card.querySelector('.launcher-waveform polyline')?.setAttribute('points', waveformPoints(values.slice(-56)));
  }
}

function syncAcquisitionIndicators() {
  $('ufcNumberIndicators')?.classList.toggle('acquiring', state.currentView === 'ufc' && Boolean(activeInstance()?.running));
  $('dmmNumberIndicators')?.classList.toggle('acquiring', state.currentView === 'dmm' && Boolean(activeInstance()?.running));
  $('wlmNumberIndicators')?.classList.toggle('acquiring', state.currentView === 'wlm' && Boolean(activeInstance()?.running));
  $('opmNumberIndicators')?.classList.toggle('acquiring', state.currentView === 'opm' && Boolean(activeInstance()?.running));
  syncLauncherStatus();
}

function renderLauncherCards() {
  const grid = $('launcherGrid');
  if (!grid) return;
  if (!state.instruments.some((item) => item.id === state.launcherActionInstanceId)) {
    state.launcherActionInstanceId = '';
  }
  grid.innerHTML = state.instruments.map((item) => launcherCardHtml(state.instances[item.id] || item)).join('');
  grid.querySelectorAll('.launcher-card').forEach((button) => wireLauncherCard(button));
}

function launcherCardHtml(instance) {
  const meta = instrumentTypeMeta[instance.type];
  if (!meta) throw new Error(`Unsupported instrument type: ${instance.type}`);
  const running = instance.running ? ' homepage-running' : '';
  const actionsOpen = state.launcherActionInstanceId === instance.id;
  const actionMode = actionsOpen ? ' launcher-actions-open' : '';
  const actionTabIndex = actionsOpen ? '0' : '-1';
  const displayName = instrumentDisplayName(instance);
  const deleteDisabled = instance.running || instance.pendingAction ? ' disabled' : '';
  const deleteLabel = instance.running || instance.pendingAction
    ? 'Stop acquisition before deleting this instrument'
    : 'Delete instrument';
  const liveValue = instance.running ? escapeHtml(instance.launcherValue || '--') : '--';
  let values = [];
  if (instance.type === 'ufc') values = instance.frequencyValues || [];
  else if (instance.type === 'dmm') values = (instance.values || []).map((point) => point.y);
  else if (instance.type === 'wlm') values = (instance.values || []).map((point) => point.y);
  else if (instance.type === 'opm') values = (instance.powerValuesW || []).map((point) => point.y);
  const customName = (instance.display_name || '').trim();
  const titleHtml = customName
    ? `<span class="launcher-instance-name">${escapeHtml(customName)}</span><span class="launcher-type-name">${escapeHtml(meta.title)}</span>`
    : meta.htmlTitle;
  return `
    <article class="launcher-card raised${running}${actionMode}" data-instance-id="${escapeHtml(instance.id)}" data-instrument-type="${escapeHtml(instance.type)}">
      <button class="launcher-card-open" type="button" aria-label="Open ${escapeHtml(displayName)}" data-open-instance="${escapeHtml(instance.id)}">
        <span class="launcher-running-dot" aria-hidden="true"></span>
        <span class="launcher-live-value">${liveValue}</span>
        <svg class="launcher-waveform" viewBox="0 0 100 46" preserveAspectRatio="none" aria-hidden="true">
          <polyline points="${waveformPoints(values.slice(-56))}"></polyline>
        </svg>
        <span class="launcher-logo ${meta.logoClass}" aria-hidden="true">
          <img class="launcher-icon" src="${meta.icon}" alt="" />
        </span>
        <span class="launcher-title">${titleHtml}</span>
      </button>
      <div class="launcher-card-actions" role="group" aria-label="Actions for ${escapeHtml(displayName)}" aria-hidden="${String(!actionsOpen)}">
        <button class="launcher-action-button launcher-rename-button" type="button" tabindex="${actionTabIndex}" title="Rename instrument" aria-label="Rename instrument" data-rename-instance="${escapeHtml(instance.id)}">
          <img src="../node_modules/lucide-static/icons/pencil.svg" alt="" />
        </button>
        <button class="launcher-action-button launcher-delete-button" type="button" tabindex="${actionTabIndex}" title="${escapeHtml(deleteLabel)}" aria-label="${escapeHtml(deleteLabel)}" data-delete-instance="${escapeHtml(instance.id)}"${deleteDisabled}>
          <img src="../node_modules/lucide-static/icons/trash-2.svg" alt="" />
        </button>
      </div>
    </article>
  `;
}

function instrumentDisplayName(instance) {
  const meta = instrumentTypeMeta[instance?.type] || {};
  return (instance?.display_name || '').trim() || meta.title || instance?.id || '';
}


function setLauncherActionMode(instanceId = '', { focusRename = false, restoreFocus = false } = {}) {
  const previousId = state.launcherActionInstanceId;
  const nextId = state.instances[instanceId] ? instanceId : '';
  if (state.launcherActionInstanceId === nextId) return;
  state.launcherActionInstanceId = nextId;
  syncLauncherStatus();
  if (nextId) closeAddInstrumentMenu();
  window.requestAnimationFrame(() => {
    if (focusRename && nextId) {
      document.querySelector(`[data-instance-id="${nextId}"] [data-rename-instance]`)?.focus();
    } else if (restoreFocus && previousId && !nextId) {
      document.querySelector(`[data-instance-id="${previousId}"] [data-open-instance]`)?.focus();
    }
  });
}

function openRenameInstrumentDialog(instanceId) {
  const instance = state.instances[instanceId];
  if (!instance) return;
  const dialog = $('renameInstrumentDialog');
  const input = $('renameInstrumentName');
  state.renamingInstrumentId = instanceId;
  state.renameInstrumentSaving = false;
  input.value = (instance.display_name || '').trim();
  input.placeholder = instrumentDisplayName(instance);
  $('saveRenameInstrument').disabled = false;
  dialog.classList.remove('closing');
  if (!dialog.open) dialog.showModal();
  input.focus();
  input.select();
  window.requestAnimationFrame(() => {
    if (!dialog.open) return;
    input.focus();
    input.select();
  });
}

async function saveRenamedInstrument() {
  const instanceId = state.renamingInstrumentId;
  const instance = state.instances[instanceId];
  if (!instance || state.renameInstrumentSaving) return;
  state.renameInstrumentSaving = true;
  $('saveRenameInstrument').disabled = true;
  const nextName = $('renameInstrumentName').value.trim();
  try {
    const updated = await api(`/api/instruments/${encodeURIComponent(instanceId)}/rename`, {
      method: 'POST',
      body: JSON.stringify({ display_name: nextName })
    });
    upsertRuntime(updated);
    state.instruments = state.instruments.map((item) => item.id === instanceId ? { ...item, ...updated } : item);
    renderLauncherCards();
    closeModal($('renameInstrumentDialog'));
  } catch (error) {
    showError('Could not rename instrument', error);
  } finally {
    state.renameInstrumentSaving = false;
    $('saveRenameInstrument').disabled = false;
  }
}

function wireLauncherCard(button) {
  const instanceId = button.dataset.instanceId;
  const openButton = button.querySelector('[data-open-instance]');
  if (!openButton) return;
  let longPressTimer = null;
  let longPressed = false;
  let pressPointerId = null;
  let pressStartX = 0;
  let pressStartY = 0;
  const cancelLongPress = () => {
    clearTimeout(longPressTimer);
    longPressTimer = null;
    pressPointerId = null;
  };
  openButton.addEventListener('pointerdown', (event) => {
    if (event.button !== 0 || event.isPrimary === false) return;
    longPressed = false;
    cancelLongPress();
    pressPointerId = event.pointerId;
    pressStartX = event.clientX;
    pressStartY = event.clientY;
    try {
      openButton.setPointerCapture(event.pointerId);
    } catch {
      // Synthetic smoke events do not own a native pointer capture.
    }
    longPressTimer = window.setTimeout(() => {
      longPressed = true;
      setLauncherActionMode(instanceId);
    }, 650);
  });
  openButton.addEventListener('pointermove', (event) => {
    if (event.pointerId !== pressPointerId) return;
    if (Math.hypot(event.clientX - pressStartX, event.clientY - pressStartY) > 10) {
      cancelLongPress();
    }
  });
  ['pointerup', 'pointercancel', 'lostpointercapture'].forEach((eventName) => {
    openButton.addEventListener(eventName, cancelLongPress);
  });
  openButton.addEventListener('click', () => {
    if (longPressed) return;
    if (state.launcherActionInstanceId) {
      setLauncherActionMode();
      return;
    }
    openInstrumentInstance(instanceId);
  });
  openButton.addEventListener('contextmenu', (event) => {
    event.preventDefault();
    cancelLongPress();
    longPressed = true;
    setLauncherActionMode(instanceId, { focusRename: true });
  });
  openButton.addEventListener('keydown', (event) => {
    if (event.key === 'F2') {
      event.preventDefault();
      setLauncherActionMode(instanceId, { focusRename: true });
    } else if (event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10')) {
      event.preventDefault();
      setLauncherActionMode(instanceId, { focusRename: true });
    } else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      if (state.launcherActionInstanceId) setLauncherActionMode();
      else openInstrumentInstance(instanceId);
    }
  });
  button.querySelector('[data-rename-instance]')?.addEventListener('click', (event) => {
    event.stopPropagation();
    setLauncherActionMode();
    openRenameInstrumentDialog(instanceId);
  });
  button.querySelector('[data-delete-instance]')?.addEventListener('click', (event) => {
    event.stopPropagation();
    deleteInstrumentInstance(instanceId).catch((error) => showError('Could not delete instrument', error));
  });
}

const errorQueue = [];

function showError(context, error, details = '', source = context) {
  const message = error?.message || String(error || 'An unexpected error occurred.');
  const key = `${source}\n${message}`;
  if (errorQueue.some((item) => item.key === key)) return;
  errorQueue.push({ context, message, details: details || error?.stack || '', key });
  if (errorQueue.length === 1) showNextError();
}

function showNextError() {
  if (!errorQueue.length) return;
  const item = errorQueue[0];
  $('errorContext').textContent = item.context;
  $('errorMessage').textContent = item.message;
  $('errorDetailsText').textContent = item.details;
  $('errorDetails').hidden = !item.details;
  $('errorDetails').open = false;
  $('errorDialog').classList.remove('closing');
  $('errorDialog').showModal();
}

function setStatusMessage(element, text, severity = 'info') {
  element.textContent = text || '';
  element.dataset.severity = severity;
}

function renderInstrumentStatus(instance) {
  const id = instance.type === 'ufc' ? 'statusText' : `${instance.type}StatusText`;
  setStatusMessage($(id), instance.statusText || 'Offline', instance.statusSeverity || 'info');
}

function reportInstrumentError(instance, context, error, details = '') {
  setInstrumentStatus(instance, instance.running
    ? 'Acquisition is still active. Review the error before continuing.'
    : 'Action required. Review the error before retrying.', null, 'warning');
  showError(`${instrumentDisplayName(instance)} — ${context}`, error, details, instance.id);
}

async function runInstrumentAction(instance, context, action) {
  try {
    return await action();
  } catch (error) {
    reportInstrumentError(instance, context, error);
  }
}

function setInstrumentStatus(instance, text, badge = null, severity = 'info') {
  instance.statusText = text;
  instance.statusSeverity = severity;
  if (badge) instance.badge = badge;
  if (state.activeInstanceId === instance.id) {
    renderInstrumentStatus(instance);
    if (state.currentView === instance.type) setBadge(instance.badge);
  }
  renderLauncherCards();
}

function renderUfcInstance() {
  const instance = state.ufc;
  renderInstrumentStatus(instance);
  $('frequencyMetric').textContent = instance.frequencyMetric || '--';
  $('frequencyUnit').textContent = instance.frequencyUnit || instance.frequencyDisplayUnit || 'MHz';
  $('sampleRateMetric').textContent = instance.sampleRateMetric || '--';
  $('elapsedMetric').textContent = instance.elapsedMetric || '0.0';
  $('adevMetric').textContent = instance.adevMetric || '--';
  syncUfcConnectionControls();
  syncUfcChartFromInstance(instance);
  syncUfcAdevAxis();
  syncAcquisitionIndicators();
}

function renderDmmInstance() {
  const instance = state.dmm;
  renderInstrumentStatus(instance);
  $('dmmValueMetric').textContent = instance.valueMetric || '--';
  $('dmmMinMetric').textContent = instance.minMetric || '--';
  $('dmmMaxMetric').textContent = instance.maxMetric || '--';
  $('dmmAvgMetric').textContent = instance.avgMetric || '--';
  $('dmmSampleRateMetric').textContent = instance.sampleRateMetric || '--';
  $('dmmUnitMetric').textContent = instance.unit || 'V';
  syncDmmChartFromInstance(instance);
  syncDmmControlState();
  syncAcquisitionIndicators();
}

function renderWlmInstance() {
  const instance = state.wlm;
  renderInstrumentStatus(instance);
  $('wlmValueMetric').textContent = instance.valueMetric || '--';
  $('wlmMinMetric').textContent = instance.minMetric || '--';
  $('wlmMaxMetric').textContent = instance.maxMetric || '--';
  $('wlmAvgMetric').textContent = instance.avgMetric || '--';
  $('wlmSampleRateMetric').textContent = instance.sampleRateMetric || '--';
  syncWlmChartFromInstance(instance);
  syncWlmControlState();
  syncAcquisitionIndicators();
}

function renderOpmInstance() {
  const instance = state.opm;
  renderInstrumentStatus(instance);
  $('opmValueMetric').textContent = instance.valueMetric || '--';
  $('opmMinMetric').textContent = instance.minMetric || '--';
  $('opmMaxMetric').textContent = instance.maxMetric || '--';
  $('opmAvgMetric').textContent = instance.avgMetric || '--';
  $('opmSampleRateMetric').textContent = instance.sampleRateMetric || '--';
  $('opmUnitMetric').textContent = instance.displayUnit || 'mW';
  syncOpmDisplayFromRaw(instance);
  syncOpmControlState();
  syncOpmDriverOverlay(instance);
  syncAcquisitionIndicators();
}

function formatSampleRate(sampleCount, elapsedS) {
  const rate = sampleCount / elapsedS;
  if (!(elapsedS > 0) || !Number.isFinite(rate) || rate < 0) return '--';
  return rate.toLocaleString(undefined, { maximumSignificantDigits: 5 });
}

async function api(path, options = {}) {
  const response = await fetch(`${state.backendUrl}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {})
    }
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || `Request failed: ${response.status}`);
  }
  return payload;
}

async function saveConfigPatch(patch) {
  state.config = await api('/api/config', {
    method: 'POST',
    body: JSON.stringify(patch)
  });
  return state.config;
}

function scheduleConfigSave() {
  clearTimeout(state.configSaveTimer);
  state.configSaveTimer = setTimeout(() => {
    const instance = activeInstance();
    if (!instance || !['ufc', 'dmm', 'wlm', 'opm'].includes(state.currentView)) return;
    let settings;
    if (instance.type === 'ufc') settings = readUfcSettings();
    else if (instance.type === 'dmm') settings = readDmmSettings();
    else if (instance.type === 'wlm') {
      settings = readWlmSettings();
      if (settings.connection_mode === 'ethernet' && !settings.resource) return;
    }
    else if (instance.type === 'opm') settings = readOpmSettings();
    else return;
    api(`/api/instruments/${encodeURIComponent(instance.id)}/settings`, {
      method: 'POST',
      body: JSON.stringify(settings)
    }).then((updated) => {
      instance.settings = updated.settings || settings;
      state.instruments = state.instruments.map((item) => item.id === instance.id ? { ...item, settings: instance.settings } : item);
    }).catch((error) => {
      reportInstrumentError(instance, 'Could not save settings', error);
    });
  }, 350);
}

function frequencyDisplayUnit(valueHz) {
  const absHz = Math.abs(valueHz);
  if (absHz >= 1_000_000_000) return { scale: 1_000_000_000, unit: 'GHz', digits: 6 };
  if (absHz >= 1_000_000) return { scale: 1_000_000, unit: 'MHz', digits: 6 };
  if (absHz >= 1_000) return { scale: 1_000, unit: 'kHz', digits: 3 };
  return { scale: 1, unit: 'Hz', digits: 3 };
}

function setFrequencyDisplayUnitForInstance(instance, valueHz) {
  if (!Number.isFinite(valueHz)) return;
  const next = frequencyDisplayUnit(valueHz);
  if (next.unit === instance.frequencyDisplayUnit) return;
  instance.frequencyDisplayScale = next.scale;
  instance.frequencyDisplayUnit = next.unit;
  if (state.activeInstanceId === instance.id) {
    $('frequencyUnit').textContent = next.unit;
    state.ufc.frequencyChart.options.scales.y.title.text = next.unit;
  }
}

function formatFrequency(valueHz) {
  if (!Number.isFinite(valueHz)) return '--';
  const unit = frequencyDisplayUnit(valueHz);
  return (valueHz / unit.scale).toFixed(unit.digits);
}

function wavelengthNmToOpticalFrequencyHz(valueNm) {
  const wavelengthNm = Number.parseFloat(valueNm);
  if (!Number.isFinite(wavelengthNm) || wavelengthNm <= 0) throw new Error('Wavelength must be a positive number of nm');
  return SPEED_OF_LIGHT_M_S / (wavelengthNm * 1e-9);
}

function ufcAdevUsesOpticalFrequency() {
  return $('divideOpticalFrequency').checked;
}

function syncUfcAdevAxis() {
  const usesOpticalFrequency = state.ufc.adevSettings?.divide_adev_by_optical_frequency ?? ufcAdevUsesOpticalFrequency();
  const yTitle = usesOpticalFrequency ? 'ADEV' : 'ADEV (Hz)';
  state.ufc.adevChart.options.plugins.title.text = usesOpticalFrequency ? 'Fractional Allan deviation' : 'Allan deviation';
  state.ufc.adevChart.options.scales.y.title.text = yTitle;
  state.ufc.adevChart.update('none');
}

function syncUfcOpticalFrequencyControls() {
  $('wavelengthRow').classList.toggle('hidden', !ufcAdevUsesOpticalFrequency());
  syncUfcAdevAxis();
}

function numericOrFallback(value, fallback) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : fallback;
}

function configuredLibraryDir() {
  return state.config?.platform?.library_dir || 'runs';
}

function applyPlatformSettings(config) {
  $('globalLibraryDir').value = config?.library_dir || configuredLibraryDir();
  syncColorModeButtons(config?.color_mode || 'auto');
}

function syncColorModeButtons(mode) {
  state.colorMode = mode;
  document.querySelectorAll('[data-color-mode]').forEach((button) => {
    button.setAttribute('aria-pressed', String(button.dataset.colorMode === mode));
  });
}

async function previewColorMode(mode) {
  await window.openUfc.setColorMode(mode);
  syncColorModeButtons(mode);
}

function readUfcConfig() {
  return {
    resource: $('resource').value.trim(),
    channel: Number.parseInt($('channel').value, 10),
    sample_rate_hz: Number.parseFloat($('sampleRate').value),
    optical_frequency_hz: ufcAdevUsesOpticalFrequency() ? wavelengthNmToOpticalFrequencyHz($('wavelength').value) : 1,
    divide_adev_by_optical_frequency: ufcAdevUsesOpticalFrequency(),
    divide_adev_by_sqrt2: $('divideSqrt2').checked,
    library_dir: configuredLibraryDir(),
    display_name: $('acquisitionName').value.trim()
  };
}

function readUfcSettings() {
  return {
    resource: $('resource').value.trim(),
    channel: numericOrFallback($('channel').value, 1),
    sample_rate_hz: numericOrFallback($('sampleRate').value, 1000),
    wavelength_nm: numericOrFallback($('wavelength').value, 851.683),
    divide_adev_by_optical_frequency: $('divideOpticalFrequency').checked,
    divide_adev_by_sqrt2: $('divideSqrt2').checked,
    analysis_tab: state.ufc.analysisTab || 'adev',
    fn_segment_length: Number($('fnSegmentLength').value),
    fn_window: $('fnWindow').value,
    fn_overlap_percent: Number($('fnOverlap').value),
    fn_log_x: $('fnLogX').checked,
    fn_log_y: $('fnLogY').checked
  };
}

function applyUfcSettings(config) {
  $('resource').value = config.resource || '';
  setSelectValueOrDefault($('channel'), config.channel ?? 1);
  setSelectValueOrDefault($('sampleRate'), config.sample_rate_hz ?? 1000);
  $('wavelength').value = config.wavelength_nm ?? 851.683;
  $('divideOpticalFrequency').checked = Boolean(config.divide_adev_by_optical_frequency ?? true);
  $('divideSqrt2').checked = Boolean(config.divide_adev_by_sqrt2 ?? true);
  setSelectValueOrDefault($('fnSegmentLength'), config.fn_segment_length ?? 1024);
  setSelectValueOrDefault($('fnWindow'), config.fn_window ?? 'hann');
  setSelectValueOrDefault($('fnOverlap'), config.fn_overlap_percent ?? 50);
  $('fnLogX').checked = config.fn_log_x ?? true;
  $('fnLogY').checked = config.fn_log_y ?? true;
  selectUfcAnalysisTab(config.analysis_tab || 'adev');
  syncUfcOpticalFrequencyControls();
  syncUfcTickSliders();
}

function selectUfcAnalysisTab(tab) {
  state.ufc.analysisTab = tab === 'fn' ? 'fn' : 'adev';
  for (const name of ['adev', 'fn']) {
    const selected = name === state.ufc.analysisTab;
    const title = name === 'adev' ? 'Adev' : 'Fn';
    $(`ufc${title}Tab`).setAttribute('aria-selected', String(selected));
    $(`ufc${title}Tab`).tabIndex = selected ? 0 : -1;
    $(`ufc${title}Panel`).hidden = !selected;
  }
  const chart = tab === 'fn' ? state.ufc.frequencyNoiseChart : state.ufc.adevChart;
  chart.resize();
  chart.update('none');
  if (tab === 'fn') {
    syncUfcNoiseChart();
    scheduleUfcNoiseUpdate(state.ufc);
  }
}

function syncUfcNoiseChart() {
  const chart = state.ufc.frequencyNoiseChart;
  const logX = $('fnLogX').checked;
  const logY = $('fnLogY').checked;
  chart.options.scales.x.type = logX ? 'logarithmic' : 'linear';
  chart.options.scales.y.type = logY ? 'logarithmic' : 'linear';
  chart.options.scales.x.ticks = { maxRotation: 0, maxTicksLimit: 9 };
  chart.options.scales.y.ticks = { maxTicksLimit: 6, callback: (value) => Number(value).toExponential(1) };
  chart.data.datasets[0].data = (state.ufc.fnPoints || []).map((point) => ({
    x: point.x, y: logY && point.y <= 0 ? null : point.y
  }));
  $('fnXScaleLabel').textContent = logX ? 'Log' : 'Linear';
  $('fnYScaleLabel').textContent = logY ? 'Log' : 'Linear';
  setStatusMessage($('fnStatus'), state.ufc.fnStatus || '', state.ufc.fnStatus ? 'warning' : 'info');
  $('fnStatus').hidden = !state.ufc.fnStatus;
  chart.update('none');
}

function ufcNoiseRequest(instance) {
  return new URLSearchParams({
    file: instance.runPath,
    segment_length: instance.settings.fn_segment_length ?? 1024,
    window: instance.settings.fn_window ?? 'hann',
    overlap_percent: instance.settings.fn_overlap_percent ?? 50
  }).toString();
}

function scheduleUfcNoiseUpdate(instance) {
  if (instance.fnTimer) return;
  instance.fnTimer = setTimeout(() => {
    instance.fnTimer = null;
    refreshUfcNoise(instance);
  }, 300);
}

async function refreshUfcNoise(instance) {
  if (state.currentView !== 'ufc' || state.activeInstanceId !== instance.id || instance.analysisTab !== 'fn' || !instance.runPath) return;
  if (instance.fnBusy) {
    instance.fnDirty = true;
    return;
  }
  const query = ufcNoiseRequest(instance);
  const revision = instance.fnRevision || 0;
  const key = `${revision}:${query}:${instance.fnSampleCount || 0}`;
  if (instance.fnCacheKey === key) return;
  instance.fnBusy = true;
  try {
    const result = await api(`/api/library/frequency-noise?${query}`);
    if (revision !== (instance.fnRevision || 0) || query !== ufcNoiseRequest(instance)) return;
    instance.fnPoints = result.points || [];
    instance.fnCacheKey = key;
    instance.fnStatus = '';
    if (state.activeInstanceId === instance.id) syncUfcNoiseChart();
  } catch (error) {
    if (revision !== (instance.fnRevision || 0) || query !== ufcNoiseRequest(instance)) return;
    instance.fnPoints = [];
    instance.fnStatus = `Frequency noise calculation failed: ${error.message}`;
    if (state.activeInstanceId === instance.id) syncUfcNoiseChart();
  } finally {
    instance.fnBusy = false;
    if (instance.fnDirty) {
      instance.fnDirty = false;
      scheduleUfcNoiseUpdate(instance);
    }
  }
}

function saveUfcAnalysisSettings() {
  const instance = state.ufc;
  instance.settings = readUfcSettings();
  // Capture this instrument's settings before navigation can change the form.
  api(`/api/instruments/${encodeURIComponent(instance.id)}/settings`, {
    method: 'POST', body: JSON.stringify(instance.settings)
  }).catch((error) => reportInstrumentError(instance, 'Could not save settings', error));
}

function setDiscoveredInstrumentCount(elementId, count) {
  const numericCount = Number(count);
  const normalizedCount = Number.isFinite(numericCount)
    ? Math.max(0, Math.trunc(numericCount))
    : 0;
  const badge = $(elementId);
  badge.textContent = normalizedCount.toLocaleString();
  badge.setAttribute(
    'aria-label',
    `${normalizedCount} discovered instrument${normalizedCount === 1 ? '' : 's'}`
  );
}

function syncUfcConnectionControls() {
  const running = Boolean(state.ufc.running || state.ufc.pendingAction);
  const checking = state.connectionCheckingIds.has(state.ufc.id);
  $('resource').disabled = running || checking;
  $('refreshResources').disabled = running || checking;
  $('checkConnection').disabled = running || checking;
  $('checkConnection').setAttribute('aria-busy', String(checking));
  syncRunSwitch(state.ufc);
}

async function refreshResources() {
  const instance = state.ufc;
  setDiscoveredInstrumentCount('ufcResourceCount', 0);
  setInstrumentStatus(instance, 'Detecting VISA resources', 'OFFLINE');
  const payload = await api(`/api/instruments/${encodeURIComponent(instance.id)}/resources`);
  if (state.activeInstanceId !== instance.id || state.ufc !== instance) return payload;
  const resources = Array.isArray(payload.resources) ? payload.resources : [];
  const list = $('resourceList');
  list.innerHTML = '';
  resources.forEach((resource) => {
    const option = document.createElement('option');
    option.value = resource;
    list.appendChild(option);
  });
  if (!$('resource').value && resources.length) $('resource').value = resources[0];
  setDiscoveredInstrumentCount('ufcResourceCount', payload.valid_count);
  setInstrumentStatus(instance, payload.error ? `VISA discovery unavailable: ${payload.error}` : 'Offline', 'OFFLINE', payload.error ? 'warning' : 'info');
}

async function startAcquisition(instance = state.ufc) {
  resetUfcPlots();
  syncUfcAdevAxis();
  const config = readUfcConfig();
  instance.settings = readUfcSettings();
  instance.adevSettings = { ...instance.settings };
  await api(`/api/instruments/${encodeURIComponent(instance.id)}/settings`, { method: 'POST', body: JSON.stringify(instance.settings) });
  await api(`/api/instruments/${encodeURIComponent(instance.id)}/start`, { method: 'POST', body: JSON.stringify(config) });
}

async function stopAcquisition(instance = state.ufc) {
  await api(`/api/instruments/${encodeURIComponent(instance.id)}/stop`, { method: 'POST', body: '{}' });
}

function syncRunSwitch(instance) {
  const input = $(instance.type === 'ufc' ? 'runSwitch' : `${instance.type}RunSwitch`);
  const busy = Boolean(instance.pendingAction);
  input.checked = Boolean(instance.running);
  input.disabled = busy || state.connectionCheckingIds.has(instance.id) || Boolean(instance.driverUnavailable);
  input.setAttribute('aria-busy', String(busy));
  const label = input.nextElementSibling;
  label.classList.toggle('pending', busy);
  label.setAttribute('aria-busy', String(busy));
  label.setAttribute('aria-label', busy
    ? (instance.pendingAction.starting ? 'Starting acquisition' : 'Stopping acquisition')
    : (instance.running ? 'Stop acquisition' : 'Run acquisition'));
}

function syncInstrumentControlState(instance) {
  if (state.activeInstanceId !== instance.id || state[instance.type] !== instance) return;
  const sync = { ufc: syncUfcConnectionControls, dmm: syncDmmControlState, wlm: syncWlmControlState, opm: syncOpmControlState };
  sync[instance.type]();
}

async function handleRunSwitchChange(kind, switchId, start, stop) {
  const instance = state[kind];
  const runSwitch = $(switchId);
  const requestedStart = runSwitch.checked;
  runSwitch.checked = Boolean(instance.running);
  if (instance.pendingAction || runSwitch.disabled) return;
  // The action identity keeps a late request failure from undoing a newer state.
  const action = { starting: requestedStart };
  instance.pendingAction = action;
  syncInstrumentControlState(instance);
  setInstrumentStatus(instance, requestedStart ? 'Connecting' : 'Stop requested', requestedStart ? 'OFFLINE' : 'BUSY');
  try {
    if (requestedStart) await start(instance);
    else await stop(instance);
  } catch (error) {
    if (instance.pendingAction !== action) return;
    instance.pendingAction = null;
    reportInstrumentError(instance, requestedStart ? 'Could not start acquisition' : 'Could not stop acquisition', error);
    syncInstrumentControlState(instance);
  }
}

function resetUfcPlots() {
  resetFullWaveform(state.ufc);
  state.ufc.adevSettings = null;
  state.ufc.fnRevision = (state.ufc.fnRevision || 0) + 1;
  state.ufc.fnSampleCount = 0;
  state.ufc.fnCacheKey = null;
  state.ufc.fnPoints = [];
  state.ufc.fnStatus = '';
  syncUfcNoiseChart();
  state.ufc.frequencyValues = [];
  state.ufc.frequencyStartIndex = 0;
  state.ufc.frequencyBreakIndices = [];
  state.ufc.frequencyDisplayScale = 1_000_000;
  state.ufc.frequencyDisplayUnit = 'MHz';
  $('frequencyUnit').textContent = 'MHz';
  state.ufc.frequencyChart.options.scales.y.title.text = 'MHz';
  state.ufc.frequencyChart.data.labels = [];
  state.ufc.frequencyChart.data.datasets[0].data = [];
  state.ufc.frequencyChart.update('none');
  state.ufc.adevPoints = [];
  state.ufc.adevChart.data.datasets[0].data = [];
  state.ufc.adevChart.update('none');
  state.ufc.frequencyMetric = '--';
  $('frequencyMetric').textContent = '--';
  state.ufc.sampleRateMetric = '--';
  $('sampleRateMetric').textContent = state.ufc.sampleRateMetric;
  state.ufc.elapsedMetric = '0.0';
  $('elapsedMetric').textContent = '0.0';
  state.ufc.adevMetric = '--';
  $('adevMetric').textContent = '--';
  state.ufc.runPath = '';
  state.ufc.launcherValue = '--';
}

function ufcWaveformPoints(instance, sampleRate) {
  const breaks = new Set(instance.frequencyBreakIndices || []);
  const points = [];
  (instance.frequencyValues || []).forEach((value, i) => {
    const index = instance.frequencyStartIndex + i;
    const x = index / sampleRate;
    if (i > 0 && breaks.has(index)) points.push({ x, y: null });
    points.push({ x, y: value / (instance.frequencyDisplayScale || 1_000_000) });
  });
  return points;
}

function syncUfcChartFromInstance(instance) {
  syncWaveformChart(instance);
  state.ufc.adevChart.data.datasets[0].data = instance.adevPoints || [];
  state.ufc.adevChart.update('none');
}

function handleData(data, instance) {
  const values = data.frequency_hz || [];
  instance.frequencyBreakIndices ||= [];
  if (data.segment_start && values.length) {
    instance.frequencyBreakIndices.push(data.total_samples - values.length);
  }
  // Large counter batches can exceed JavaScript's function argument limit.
  instance.frequencyValues = instance.frequencyValues.concat(values.slice(-instance.maxFrequencyPoints))
    .slice(-instance.maxFrequencyPoints);
  instance.frequencyStartIndex = data.total_samples - instance.frequencyValues.length;
  instance.frequencyBreakIndices = instance.frequencyBreakIndices.filter(
    (index) => index > instance.frequencyStartIndex
  );

  const latest = values.length ? values[values.length - 1] : Number.NaN;
  setFrequencyDisplayUnitForInstance(instance, latest);
  const sampleRateMetric = formatSampleRate(data.total_samples, data.elapsed_s);
  if (state.activeInstanceId === instance.id) {
    syncWaveformChart(instance);
    $('frequencyMetric').textContent = formatFrequency(latest);
    $('sampleRateMetric').textContent = sampleRateMetric;
    $('elapsedMetric').textContent = Number(data.elapsed_s).toFixed(1);
  }
  instance.frequencyMetric = formatFrequency(latest);
  instance.frequencyUnit = instance.frequencyDisplayUnit;
  instance.sampleRateMetric = sampleRateMetric;
  instance.elapsedMetric = Number(data.elapsed_s).toFixed(1);
  instance.runPath = data.library_file || '';
  instance.fnSampleCount = data.total_samples;
  scheduleFullWaveformRefresh(instance);
  if (state.activeInstanceId === instance.id && instance.analysisTab === 'fn') scheduleUfcNoiseUpdate(instance);
  instance.launcherValue = `${instance.frequencyMetric} ${instance.frequencyUnit}`;
  syncLauncherStatus();
}

function handleAdev(data, instance) {
  const tau = data.tau_s || [];
  const adev = data.adev || [];
  const points = [];
  for (let i = 0; i < tau.length; i += 1) {
    if (tau[i] > 0 && adev[i] > 0) points.push({ x: tau[i], y: adev[i] });
  }
  instance.adevPoints = points;
  const oneSecondPoint = points.find((point) => Math.abs(point.x - 1.0) < 1e-9);
  instance.adevMetric = oneSecondPoint ? oneSecondPoint.y.toExponential(2) : '--';
  if (state.activeInstanceId === instance.id) {
    state.ufc.adevChart.data.datasets[0].data = points;
    state.ufc.adevChart.update('none');
    $('adevMetric').textContent = instance.adevMetric;
  }
}

const chartColors = {};

function refreshChartTheme() {
  const style = getComputedStyle(document.documentElement);
  for (const name of ['text', 'muted', 'blue', 'green', 'amber', 'teal', 'power', 'chart-grid']) {
    chartColors[name] = style.getPropertyValue(`--${name}`).trim();
  }
  Chart.defaults.color = () => chartColors.muted;
  Chart.defaults.borderColor = () => chartColors['chart-grid'];
  for (const chart of Object.values(Chart.instances)) chart.update('none');
}

function createCharts() {
  refreshChartTheme();
  Chart.defaults.font.family = 'Utendo, Segoe UI, Arial, sans-serif';

  state.ufc.frequencyChart = new Chart($('frequencyChart'), {
    type: 'line',
    data: { datasets: [{ label: 'Frequency', data: [], borderColor: () => chartColors.blue, borderWidth: 2, pointRadius: 0, tension: 0.12 }] },
    options: chartOptions('Frequency', 'Time (s)', 'MHz')
  });

  state.ufc.adevChart = new Chart($('adevChart'), {
    type: 'line',
    data: { datasets: [{ label: 'ADEV', data: [], borderColor: () => chartColors.amber, backgroundColor: () => chartColors.amber, borderWidth: 2, pointRadius: 3, showLine: true }] },
    options: {
      ...chartOptions('Fractional Allan deviation', 'Tau (s)', 'ADEV'),
      scales: {
        x: adevTauAxis(),
        y: adevYAxis('ADEV')
      }
    }
  });

  state.ufc.frequencyNoiseChart = new Chart($('frequencyNoiseChart'), {
    type: 'line',
    data: { datasets: [{ label: 'Frequency noise PSD', data: [], borderColor: () => chartColors.teal, borderWidth: 1.5, pointRadius: 0 }] },
    options: chartOptions('Frequency noise spectrum', 'Fourier frequency (Hz)', 'PSD (Hz²/Hz)')
  });

  state.dmm.trendChart = new Chart($('dmmTrendChart'), {
    type: 'line',
    data: { datasets: [{ label: 'DC Voltage', data: [], borderColor: () => chartColors.green, borderWidth: 2, pointRadius: 0, tension: 0.16 }] },
    options: chartOptions('DC Voltage trend', 'Elapsed (s)', 'V')
  });

  state.dmm.adevChart = new Chart($('dmmAdevChart'), {
    type: 'line',
    data: { datasets: [{ label: 'ADEV', data: [], borderColor: () => chartColors.amber, backgroundColor: () => chartColors.amber, borderWidth: 2, pointRadius: 3, showLine: true }] },
    options: {
      ...chartOptions('Allan deviation', 'Tau (s)', 'V'),
      scales: {
        x: adevTauAxis(),
        y: adevYAxis('ADEV (V)')
      }
    }
  });

  const wlmTrendOptions = chartOptions('Wavelength Trend', 'Elapsed (s)', 'nm');
  wlmTrendOptions.scales.y.ticks = wavelengthTickStyle();
  wlmTrendOptions.plugins.tooltip = {
    callbacks: {
      label: wavelengthTooltipLabel
    }
  };
  state.wlm.trendChart = new Chart($('wlmTrendChart'), {
    type: 'line',
    data: { datasets: [{ label: 'Wavelength', data: [], borderColor: () => chartColors.blue, borderWidth: 2, pointRadius: 0, tension: 0.16 }] },
    options: wlmTrendOptions
  });

  state.wlm.adevChart = new Chart($('wlmAdevChart'), {
    type: 'line',
    data: { datasets: [{ label: 'ADEV (nm)', data: [], borderColor: () => chartColors.amber, backgroundColor: () => chartColors.amber, borderWidth: 2, pointRadius: 3, showLine: true }] },
    options: {
      ...chartOptions('ADEV (nm)', 'Tau (s)', 'ADEV (nm)'),
      scales: {
        x: adevTauAxis(),
        y: adevYAxis('ADEV (nm)')
      }
    }
  });

  state.opm.trendChart = new Chart($('opmTrendChart'), {
    type: 'line',
    data: { datasets: [{ label: 'Optical power', data: [], borderColor: () => chartColors.power, borderWidth: 2, pointRadius: 0, tension: 0.16 }] },
    options: chartOptions('Optical power trend', 'Elapsed (s)', 'mW')
  });

  state.opm.adevChart = new Chart($('opmAdevChart'), {
    type: 'line',
    data: { datasets: [{ label: 'ADEV (W)', data: [], borderColor: () => chartColors.amber, backgroundColor: () => chartColors.amber, borderWidth: 2, pointRadius: 3, showLine: true }] },
    options: {
      ...chartOptions('Absolute power Allan deviation', 'Tau (s)', 'ADEV (W)'),
      scales: {
        x: adevTauAxis(),
        y: adevYAxis('ADEV (W)')
      }
    }
  });

  state.library.waveformChart = new Chart($('libraryWaveformChart'), {
    type: 'line',
    data: { datasets: [{ label: 'Waveform', data: [], borderColor: () => chartColors.blue, borderWidth: 2, pointRadius: 0, tension: 0.12 }] },
    options: chartOptions('Waveform preview', 'Time (s)', 'Value')
  });

  state.library.adevChart = new Chart($('libraryAdevChart'), {
    type: 'line',
    data: { datasets: [{ label: 'ADEV', data: [], borderColor: () => chartColors.amber, backgroundColor: () => chartColors.amber, borderWidth: 2, pointRadius: 3, showLine: true }] },
    options: {
      ...chartOptions('ADEV preview', 'Tau (s)', 'ADEV'),
      scales: {
        x: adevTauAxis(),
        y: adevYAxis('ADEV')
      }
    }
  });
}

function chartOptions(title, xTitle, yTitle) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    parsing: false,
    plugins: {
      title: { display: true, text: title, color: () => chartColors.text, font: { size: 15, weight: 'bold' } },
      legend: { display: false }
    },
    scales: {
      x: { type: 'linear', title: axisTitle(xTitle), grid: gridStyle() },
      y: { title: axisTitle(yTitle), grid: gridStyle(), ticks: yTickStyle() }
    }
  };
}

function axisTitle(text) {
  return { display: true, text, color: () => chartColors.muted, font: { weight: 'bold' } };
}

function gridStyle() {
  return { color: () => chartColors['chart-grid'] };
}

function decadeExponent(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric <= 0) return null;
  const exponent = Math.round(Math.log10(numeric));
  const decade = 10 ** exponent;
  return Math.abs(numeric - decade) / decade <= 1e-10 ? exponent : null;
}

function superscriptExponent(exponent) {
  const superscripts = {
    '-': '\u207B',
    '0': '\u2070',
    '1': '\u00B9',
    '2': '\u00B2',
    '3': '\u00B3',
    '4': '\u2074',
    '5': '\u2075',
    '6': '\u2076',
    '7': '\u2077',
    '8': '\u2078',
    '9': '\u2079'
  };
  return String(exponent).replace(/[-0-9]/g, (digit) => superscripts[digit]);
}

function adevTauAxis() {
  return {
    type: 'logarithmic',
    title: axisTitle('Tau (s)'),
    grid: gridStyle(),
    ticks: {
      autoSkip: false,
      major: { enabled: true },
      callback(value) {
        const exponent = decadeExponent(value);
        return exponent === null ? '' : `10${superscriptExponent(exponent)}`;
      }
    }
  };
}

function adevYAxis(title) {
  return {
    type: 'logarithmic',
    title: axisTitle(title),
    grid: gridStyle(),
    ticks: {
      autoSkip: false,
      major: { enabled: true },
      callback(value) {
        const exponent = decadeExponent(value);
        return exponent === null ? '' : `1E${exponent}`;
      }
    }
  };
}

function yTickStyle() {
  return {
    callback(value) {
      const numeric = Number(value);
      if (!Number.isFinite(numeric)) return value;
      const abs = Math.abs(numeric);
      if (abs > 0 && (abs < 0.001 || abs >= 1_000_000)) return numeric.toExponential(3);
      return numeric.toFixed(3);
    }
  };
}

function wavelengthTickStyle() {
  return {
    callback(value) {
      const numeric = Number(value);
      return Number.isFinite(numeric) ? numeric.toFixed(6) : value;
    }
  };
}

function wavelengthTooltipLabel(context) {
  const label = context.dataset?.label || 'Wavelength';
  return `${label}: ${formatWavelengthNm(context.parsed?.y)} nm`;
}

async function loadDevices() {
  // One request at a time also prevents an older scan from replacing a newer result.
  if (state.devices.loading) return;
  state.devices.loading = true;
  state.devices.error = '';
  renderDevices();
  try {
    const payload = await api('/api/devices');
    state.devices.items = payload.devices || [];
    state.devices.warnings = payload.warnings || [];
    if (!state.devices.items.some((item) => item.id === state.devices.selectedId)) {
      state.devices.selectedId = state.devices.items.find((item) => item.type && item.status !== 'unavailable')?.id || '';
    }
  } catch (error) {
    state.devices.items = [];
    state.devices.selectedId = '';
    state.devices.warnings = [];
    state.devices.error = 'Device discovery failed. Press Refresh to try again.';
    showError('Device discovery failed', error);
  } finally {
    state.devices.loading = false;
    if (state.currentView === 'devices') renderDevices();
  }
}

function renderDevices() {
  const { items, selectedId, loading, warnings, error } = state.devices;
  $('refreshDevices').disabled = loading;
  $('refreshDevices').textContent = loading ? 'Scanning…' : 'Refresh';
  for (const id of ['devicesList', 'unidentifiedDevicesList', 'disconnectedDevicesList']) {
    $(id).replaceChildren();
  }
  items.forEach((item) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'library-item';
    button.dataset.deviceId = item.id;
    button.classList.toggle('active', item.id === selectedId);
    button.setAttribute('aria-pressed', String(item.id === selectedId));
    const type = instrumentTypeMeta[item.type]?.title || item.transport;
    button.innerHTML = `<span>${escapeHtml(item.model || item.resource)}</span><em>${escapeHtml(type)}${item.status === 'in_use' ? ' / In use' : ''}</em>`;
    button.addEventListener('click', () => {
      state.devices.selectedId = item.id;
      renderDevices();
      document.querySelectorAll('[data-device-id]').forEach((row) => {
        if (row.dataset.deviceId === item.id) row.focus();
      });
    });
    const listId = item.status === 'unavailable' ? 'disconnectedDevicesList'
      : item.type ? 'devicesList' : 'unidentifiedDevicesList';
    $(listId).appendChild(button);
  });
  for (const [id, label] of [['unidentifiedDevices', 'Unidentified'], ['disconnectedDevices', 'Disconnected']]) {
    const count = $(`${id}List`).childElementCount;
    $(id).hidden = count === 0;
    $(`${id}Summary`).textContent = `${label} (${count})`;
  }
  setStatusMessage($('devicesStatus'), loading ? 'Looking for USB instruments…'
    : error || [`${items.length} USB instrument${items.length === 1 ? '' : 's'} found.`, ...warnings].join('\n'),
    !loading && (error || warnings.length) ? 'warning' : 'info');
  const selected = items.find((item) => item.id === selectedId);
  $('deviceDetail').classList.toggle('hidden', !selected);
  $('devicesEmpty').classList.toggle('hidden', Boolean(selected));
  $('devicesEmpty').textContent = loading ? 'Looking for USB instruments…'
    : error ? 'Device discovery failed. Press Refresh to try again.'
    : items.length ? 'Select an instrument from the list.'
    : warnings.length ? 'No instruments found. Some discovery sources are unavailable.'
    : 'No USB instruments found.';
  $('deviceName').textContent = selected?.model || selected?.resource || '';
  const availability = { available: 'Connected', detected: 'Detected', in_use: 'In use', unavailable: 'Disconnected' };
  const rows = selected ? [
    ['Manufacturer', selected.manufacturer], ['Model', selected.model],
    ['Instrument type', instrumentTypeMeta[selected.type]?.title],
    ['Serial number', selected.serial], ['Firmware', selected.firmware],
    ['Connection', selected.transport], ['Address', selected.resource],
    ['Availability', availability[selected.status]], ['Identification', selected.identification]
  ] : [];
  $('deviceMetadata').innerHTML = rows.map(([label, value]) => `<span>${label}</span><strong>${escapeHtml(value || '')}</strong>`).join('');
}

function setLibraryStatus(text, severity = 'info') {
  setStatusMessage($('libraryExportStatus'), text, severity);
}

function reportLibraryError(context, error) {
  setLibraryStatus('Action required. Review the error before retrying.', 'warning');
  showError(context, error);
}

function libraryItemTitle(item) {
  return item.display_name || item.file;
}

function renderLibraryList() {
  const list = $('libraryList');
  list.innerHTML = '';
  if (!state.library.items.length) {
    const empty = document.createElement('div');
    empty.className = 'library-list-empty';
    empty.textContent = 'No .lmp files';
    list.appendChild(empty);
    $('libraryEmpty').classList.remove('hidden');
    $('libraryDetail').classList.add('hidden');
    return;
  }

  state.library.items.forEach((item) => {
    const button = document.createElement('button');
    button.className = 'library-item';
    button.type = 'button';
    button.classList.toggle('active', item.file === state.library.selectedFile);
    button.innerHTML = `
      <span>${escapeHtml(libraryItemTitle(item))}</span>
      <em>${escapeHtml(item.instrument_abbreviation || '')} / ${Number(item.sample_count || 0).toLocaleString()} pts</em>
    `;
    if (item.active) button.classList.add('active-acquisition');
    button.addEventListener('click', () => selectLibraryItem(item.file));
    list.appendChild(button);
  });
}

async function loadLibrary() {
  const payload = await api('/api/library');
  state.library.items = payload.items || [];
  const warnings = payload.warnings || [];
  setStatusMessage($('libraryScanStatus'), warnings.join('\n'), 'warning');
  $('libraryScanStatus').hidden = !warnings.length;
  $('showLibraryInExplorer').title = `Show in Explorer\n${payload.library_dir || configuredLibraryDir()}`;
  if (!state.library.selectedFile && state.library.items.length) {
    state.library.selectedFile = state.library.items[0].file;
  }
  if (state.library.selectedFile && !state.library.items.some((item) => item.file === state.library.selectedFile)) {
    state.library.selectedFile = state.library.items[0]?.file || '';
  }
  renderLibraryList();
  if (state.library.selectedFile) await selectLibraryItem(state.library.selectedFile, { skipListRender: true });
}

async function selectLibraryItem(file, options = {}) {
  state.library.selectedFile = file;
  if (!options.skipListRender) renderLibraryList();
  const item = await api(`/api/library/item?file=${encodeURIComponent(file)}`);
  renderLibraryDetail(item);
}

function renderLibraryDetail(item) {
  $('libraryEmpty').classList.add('hidden');
  $('libraryDetail').classList.remove('hidden');
  const metadata = item.metadata || {};
  $('libraryDisplayName').value = metadata.display_name || '';
  renderMetadata(metadata, item.path);

  const waveformPoints = item.waveform?.points || [];
  state.library.waveformChart.data.datasets[0].data = waveformPoints;
  state.library.waveformChart.options.scales.y.title.text = item.waveform?.unit || 'Value';
  state.library.waveformChart.update('none');

  const adevPoints = item.adev?.points || [];
  state.library.adevChart.data.datasets[0].data = adevPoints;
  state.library.adevChart.options.scales.y.title.text = item.adev?.unit || 'ADEV';
  state.library.adevChart.update('none');
  const legacyCounter = metadata.app_type === 'ufc' && !('ufc_segment_starts' in metadata);
  setLibraryStatus(legacyCounter
    ? 'This older recording has no segment boundaries. Plots and analysis treat the samples as one continuous segment.'
    : '', legacyCounter ? 'warning' : 'info');
}

function renderMetadata(metadata, path) {
  const settings = metadata.settings || {};
  const typeLabels = {
    ufc: 'Universal Frequency Counter',
    dmm: 'Digital Multimeter',
    wlm: 'Wavelength Meter',
    opm: 'Optical Power Meter'
  };
  const rows = [
    ['File', metadata.file_name || state.library.selectedFile],
    ['Name', metadata.display_name || '--'],
    ['Type', typeLabels[metadata.app_type] || metadata.app_type],
    ['Instrument', metadata.instrument_id || '--'],
    ['Resource', metadata.resource || '--'],
    ['Started', metadata.started_at || '--'],
    ['Ended', metadata.ended_at || 'Active'],
    ['Samples', Number(metadata.sample_count || 0).toLocaleString()],
    ['Unit', metadata.unit || '--'],
    ['Path', path || '--']
  ];
  if (metadata.app_type === 'ufc') {
    rows.splice(6, 0, ['Sample rate', `${settings.sample_rate_hz || '--'} Hz`]);
  }
  if (metadata.app_type === 'dmm') {
    rows.splice(6, 0, ['Function', settings.measurement_function]);
  }
  if (metadata.app_type === 'wlm') {
    rows.splice(6, 0, ['Sample rate', `${settings.sample_rate_hz ?? '--'} Hz`]);
  }
  if (metadata.app_type === 'opm') {
    const manualRange = Number(settings.manual_range_w);
    const rangeText = settings.autorange
      ? 'Autorange'
      : Number.isFinite(manualRange) ? `${formatMeasurement(manualRange)} W` : '--';
    rows.splice(
      6,
      0,
      ['Wavelength', `${settings.wavelength_nm ?? '--'} nm`],
      ['Display unit', settings.display_unit || 'mW'],
      ['Range', rangeText],
      ['Sample rate', `${settings.sample_rate_hz ?? '--'} Hz`]
    );
  }
  $('libraryMetadata').innerHTML = rows.map(([label, value]) => `
    <div>${escapeHtml(label)}</div>
    <strong>${escapeHtml(String(value ?? '--'))}</strong>
  `).join('');
}

async function renameLibraryItem() {
  if (!state.library.selectedFile) return;
  const displayName = $('libraryDisplayName').value.trim();
  await api('/api/library/rename', {
    method: 'POST',
    body: JSON.stringify({ file: state.library.selectedFile, display_name: displayName })
  });
  setLibraryStatus('Name saved');
  await loadLibrary();
}


function setDeleteLibraryBusy(busy) {
  state.library.deleteInProgress = Boolean(busy);
  $('confirmDeleteLibraryItem').disabled = Boolean(busy);
  $('deleteLibraryDialog').querySelectorAll('[value="cancel"]').forEach((button) => {
    button.disabled = Boolean(busy);
  });
}

function openDeleteLibraryDialog() {
  if (!state.library.selectedFile) return;
  const title = $('libraryDisplayName').value.trim() || state.library.selectedFile;
  const dialog = $('deleteLibraryDialog');
  state.library.pendingDeleteFile = state.library.selectedFile;
  $('deleteLibraryRecordName').textContent = title;
  setDeleteLibraryBusy(false);
  dialog.classList.remove('closing');
  if (!dialog.open) dialog.showModal();
  window.requestAnimationFrame(() => $('cancelDeleteLibraryItem').focus());
}

async function confirmDeleteLibraryItem() {
  const file = state.library.pendingDeleteFile;
  if (!file || state.library.deleteInProgress) return;
  setDeleteLibraryBusy(true);
  try {
    await api('/api/library/delete', {
      method: 'POST',
      body: JSON.stringify({ file })
    });
  } catch (error) {
    showError('Could not delete record', error);
    setDeleteLibraryBusy(false);
    return;
  }
  if (state.library.selectedFile === file) {
    state.library.selectedFile = '';
  }
  closeModal($('deleteLibraryDialog'));
  setLibraryStatus('Deleted');
  setDeleteLibraryBusy(false);
  try {
    await loadLibrary();
  } catch (error) {
    setLibraryStatus('Record deleted. Refresh the Library to update the list.', 'warning');
    showError('Record deleted, but Library refresh failed', error);
  }
}

async function exportLibrarySeries(series) {
  if (!state.library.selectedFile) return;
  const stem = state.library.selectedFile.replace(/\.lmp$/i, '');
  const suffix = series === 'adev' ? 'adev' : 'waveform';
  const selected = await window.openUfc.saveCsv({
    title: `Export ${suffix} CSV`,
    defaultPath: `${stem}_${suffix}.csv`
  });
  if (!selected) return;
  setLibraryStatus(`Exporting ${suffix} CSV...`);
  const payload = await api('/api/library/export', {
    method: 'POST',
    body: JSON.stringify({ file: state.library.selectedFile, series, csv_path: selected })
  });
  setLibraryStatus(`Exported ${Number(payload.row_count || 0).toLocaleString()} row(s) to ${payload.csv_path}`);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function currentDmmFunctionInfo(instance = state.dmm) {
  const fn = state.activeInstanceId === instance?.id ? $('dmmFunction').value : instance?.settings?.measurement_function;
  return (state.dmmOptions?.functions || []).find((item) => item.value === fn);
}

function syncDmmChartTitles(instance = state.dmm) {
  const info = currentDmmFunctionInfo(instance);
  const label = info?.label || 'Measurement';
  state.dmm.trendChart.options.plugins.title.text = `${label} trend`;
  state.dmm.trendChart.data.datasets[0].label = label;
  state.dmm.adevChart.options.plugins.title.text = 'Allan deviation';
  state.dmm.adevChart.data.datasets[0].label = 'ADEV';
}

function currentDmmScaleAndUnit(instance = state.dmm) {
  const info = currentDmmFunctionInfo(instance);
  if (!info) return { scale: 1, unit: instance?.unit || 'V' };
  const autorange = state.activeInstanceId === instance?.id ? $('dmmAutorange').checked : Boolean(instance?.settings?.autorange ?? true);
  if (autorange) return { scale: 1, unit: info.unit };
  const rangeValue = Number.parseFloat(state.activeInstanceId === instance?.id ? $('dmmRange').value : instance?.settings?.range_value);
  const rmsSuffix = info.unit.endsWith(' RMS') ? ' RMS' : '';
  if (info.value === 'RES') {
    if (rangeValue >= 1_000_000) return { scale: 1e-6, unit: 'MOhm' };
    if (rangeValue >= 1_000) return { scale: 1e-3, unit: 'kOhm' };
    return { scale: 1, unit: 'Ohm' };
  }
  const baseUnit = info.is_current ? 'A' : 'V';
  if (rangeValue < 0.001) return { scale: 1_000_000, unit: `u${baseUnit}${rmsSuffix}` };
  if (rangeValue < 1.0) return { scale: 1_000, unit: `m${baseUnit}${rmsSuffix}` };
  return { scale: 1, unit: `${baseUnit}${rmsSuffix}` };
}

function formatMeasurement(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '--';
  const numeric = Number(value);
  const abs = Math.abs(numeric);
  if (abs >= 100_000 || (abs > 0 && abs < 0.001)) return numeric.toExponential(6);
  return numeric.toFixed(6).replace(/\.?0+$/, '');
}

function populateSelect(select, items, labelKey = 'label', valueKey = 'value') {
  select.innerHTML = '';
  items.forEach((item) => {
    const option = document.createElement('option');
    option.value = item[valueKey];
    option.textContent = item[labelKey];
    select.appendChild(option);
  });
}

function setSelectValueOrDefault(select, value) {
  select.value = String(value ?? '');
  if (select.selectedIndex < 0 && select.options.length) select.selectedIndex = 0;
}

function syncTickSlider(selectId) {
  const select = $(selectId);
  const slider = document.querySelector(`[data-slider-select="${selectId}"]`);
  if (!select || !slider) return;

  const options = [...select.options];
  if (select.selectedIndex < 0 && options.length) select.selectedIndex = 0;
  const selectedIndex = Math.max(select.selectedIndex, 0);
  const denominator = Math.max(options.length - 1, 1);
  const selectedRatio = options.length <= 1 ? 0.5 : selectedIndex / denominator;
  const endpointInset = 8;
  const scalePosition = (ratio) => endpointInset + ((1 - ratio) * (100 - endpointInset * 2));
  const knobTrackPosition = (1 - selectedRatio) * 100;
  const disabled = select.disabled || options.length <= 1;

  slider.style.setProperty('--fill-height', `${selectedRatio * 100}%`);
  slider.style.setProperty('--knob-top', `${knobTrackPosition}%`);
  slider.classList.toggle('is-disabled', disabled);
  slider.classList.toggle('is-single', options.length <= 1);

  const optionContainer = slider.querySelector('[data-slider-options]');
  optionContainer.innerHTML = '';
  options.forEach((option, index) => {
    const ratio = options.length <= 1 ? 0.5 : index / denominator;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'dmm-tick-option';
    button.dataset.tickValue = option.value;
    button.style.setProperty('--tick-top', `${scalePosition(ratio)}%`);
    button.disabled = disabled;
    button.setAttribute('aria-pressed', String(index === selectedIndex));

    const tick = document.createElement('span');
    tick.className = 'dmm-tick-line';
    const label = document.createElement('span');
    label.className = 'dmm-tick-label';
    label.textContent = option.textContent;
    button.append(tick, label);
    optionContainer.appendChild(button);
  });
}

function syncDmmTickSliders() {
  syncTickSlider('dmmRange');
  syncTickSlider('dmmNplc');
}

function syncUfcTickSliders() {
  syncTickSlider('channel');
  syncTickSlider('sampleRate');
}

function setTickSliderValue(selectId, value) {
  const select = $(selectId);
  if (!select || select.disabled) return;
  select.value = value;
  if (select.selectedIndex < 0) return;
  select.dispatchEvent(new Event('change', { bubbles: true }));
}

async function loadDmmOptions() {
  if (!state.dmm?.id) throw new Error('No Digital Multimeter instance is active');
  state.dmmOptions = await api(`/api/instruments/${encodeURIComponent(state.dmm.id)}/options`);
  populateSelect($('dmmFunction'), state.dmmOptions.functions);
  applyDmmSettings(state.dmm?.settings || state.dmmOptions.defaults);
  syncDmmControlState();
}

function applyDmmSettings(config) {
  $('dmmResource').value = config.resource;
  $('dmmFunction').value = config.measurement_function || 'VOLT:DC';
  $('dmmAutorange').checked = Boolean(config.autorange ?? true);
  syncDmmFunctionControls();
  setSelectValueOrDefault($('dmmRange'), config.range_value ?? $('dmmRange').value);
  setSelectValueOrDefault($('dmmNplc'), config.nplc ?? $('dmmNplc').value);
  syncDmmDisplayUnitFromControls();
  syncDmmTickSliders();
}

function syncDmmFunctionControls() {
  const info = currentDmmFunctionInfo();
  if (!info) return;
  populateSelect($('dmmRange'), info.range_options);
  const nplcItems = info.supports_nplc ? info.nplc_options.map((value) => ({ value, label: `${value} PLC` })) : [{ value: 1, label: 'Automatic' }];
  populateSelect($('dmmNplc'), nplcItems);
  $('dmmNplc').disabled = !info.supports_nplc;
  $('dmmLeadWarning').classList.toggle('hidden', !info.is_current);
  syncDmmDisplayUnitFromControls();
  syncDmmTickSliders();
}

function syncDmmDisplayUnitFromControls() {
  const display = currentDmmScaleAndUnit();
  state.dmm.unit = display.unit;
  $('dmmUnitMetric').textContent = display.unit;
  syncDmmChartTitles();
  state.dmm.trendChart.options.scales.y.title.text = display.unit;
  state.dmm.adevChart.options.scales.y.title.text = `ADEV (${display.unit})`;
  syncWaveformChart(state.dmm);
  state.dmm.adevChart.update('none');
}

function syncDmmControlState() {
  const running = Boolean(state.dmm.running || state.dmm.pendingAction);
  const checking = state.connectionCheckingIds.has(state.dmm.id);
  $('dmmResource').disabled = running || checking;
  $('dmmRefreshResources').disabled = running || checking;
  $('dmmCheckConnection').disabled = running || checking;
  $('dmmCheckConnection').setAttribute('aria-busy', String(checking));
  $('dmmFunction').disabled = running;
  $('dmmAutorange').disabled = running;
  $('dmmRange').disabled = $('dmmAutorange').checked || running;
  $('dmmNplc').disabled = !currentDmmFunctionInfo()?.supports_nplc || running;
  syncRunSwitch(state.dmm);
  syncDmmTickSliders();
}

async function refreshDmmResources() {
  const instance = state.dmm;
  setDiscoveredInstrumentCount('dmmResourceCount', 0);
  setInstrumentStatus(instance, 'Detecting DMM VISA resources', 'OFFLINE');
  const payload = await api(`/api/instruments/${encodeURIComponent(instance.id)}/resources`);
  if (state.activeInstanceId !== instance.id || state.dmm !== instance) return payload;
  const resources = Array.isArray(payload.resources) ? payload.resources : [];
  const list = $('dmmResourceList');
  list.innerHTML = '';
  resources.forEach((resource) => {
    const option = document.createElement('option');
    option.value = resource;
    list.appendChild(option);
  });
  if (!$('dmmResource').value && resources.length) $('dmmResource').value = resources[0];
  setDiscoveredInstrumentCount('dmmResourceCount', payload.valid_count);
  setInstrumentStatus(instance, payload.error ? `DMM VISA discovery unavailable: ${payload.error}` : 'Offline', 'OFFLINE', payload.error ? 'warning' : 'info');
}

function readDmmConfig() {
  return {
    resource: $('dmmResource').value.trim(),
    measurement_function: $('dmmFunction').value,
    autorange: $('dmmAutorange').checked,
    range_value: Number.parseFloat($('dmmRange').value),
    nplc: Number.parseFloat($('dmmNplc').value),
    library_dir: configuredLibraryDir(),
    display_name: $('dmmAcquisitionName').value.trim()
  };
}

function readDmmSettings() {
  const settings = readDmmConfig();
  delete settings.library_dir;
  delete settings.display_name;
  return settings;
}

function instrumentConnectionCheckSpec(kind) {
  if (kind === 'ufc') {
    return {
      instance: state.ufc,
      label: 'frequency counter',
      settings: readUfcSettings(),
      syncControls: syncUfcConnectionControls
    };
  }
  if (kind === 'dmm') {
    return {
      instance: state.dmm,
      label: 'DMM',
      settings: readDmmSettings(),
      syncControls: syncDmmControlState
    };
  }
  if (kind === 'opm') {
    return {
      instance: state.opm,
      label: 'optical power meter',
      settings: readOpmSettings(),
      syncControls: syncOpmControlState
    };
  }
  throw new Error(`Unsupported connection check: ${kind}`);
}

async function checkInstrumentConnection(kind) {
  const spec = instrumentConnectionCheckSpec(kind);
  const instance = spec.instance;
  const instanceId = instance?.id;
  if (!instanceId || instance.running || instance.pendingAction || state.connectionCheckingIds.has(instanceId)) return null;
  const isStillActive = () => state.activeInstanceId === instanceId && state[kind] === instance;
  state.connectionCheckingIds.add(instanceId);
  spec.syncControls();
  setInstrumentStatus(instance, `Checking ${spec.label} connection`, 'OFFLINE');
  try {
    const payload = await api(`/api/instruments/${encodeURIComponent(instanceId)}/check`, {
      method: 'POST',
      body: JSON.stringify(spec.settings)
    });
    const identity = String(payload.identity || payload.resource || '').trim();
    setInstrumentStatus(instance, identity ? `Connected: ${identity}` : 'Connection check passed', 'READY');
    return payload;
  } catch (error) {
    reportInstrumentError(instance, 'Connection check failed', error);
    return null;
  } finally {
    state.connectionCheckingIds.delete(instanceId);
    if (isStillActive()) spec.syncControls();
  }
}

function resetDmmDisplay() {
  resetFullWaveform(state.dmm);
  state.dmm.runPath = '';
  state.dmm.values = [];
  state.dmm.adevPoints = [];
  syncWaveformChart(state.dmm);
  ['dmmValueMetric', 'dmmMinMetric', 'dmmMaxMetric', 'dmmAvgMetric'].forEach((id) => {
    $(id).textContent = '--';
  });
  $('dmmSampleRateMetric').textContent = '--';
  state.dmm.adevChart.data.datasets[0].data = [];
  state.dmm.adevChart.update('none');
  state.dmm.valueMetric = '--';
  state.dmm.minMetric = '--';
  state.dmm.maxMetric = '--';
  state.dmm.avgMetric = '--';
  state.dmm.sampleRateMetric = '--';
  state.dmm.launcherValue = '--';
}

function syncDmmChartFromInstance(instance) {
  syncDmmChartTitles(instance);
  syncWaveformChart(instance);
  state.dmm.adevChart.options.scales.y.title.text = `ADEV (${instance.unit || 'V'})`;
  state.dmm.adevChart.data.datasets[0].data = instance.adevPoints || [];
  state.dmm.trendChart.update('none');
  state.dmm.adevChart.update('none');
}

async function startDmm(instance = state.dmm) {
  resetDmmDisplay();
  const config = readDmmConfig();
  instance.settings = readDmmSettings();
  await api(`/api/instruments/${encodeURIComponent(instance.id)}/settings`, { method: 'POST', body: JSON.stringify(instance.settings) });
  await api(`/api/instruments/${encodeURIComponent(instance.id)}/start`, { method: 'POST', body: JSON.stringify(config) });
}

async function stopDmm(instance = state.dmm) {
  await api(`/api/instruments/${encodeURIComponent(instance.id)}/stop`, { method: 'POST', body: '{}' });
}

function handleDmmSample(data, instance) {
  const display = currentDmmScaleAndUnit(instance);
  if (display.unit !== instance.unit) {
    instance.unit = display.unit;
    if (state.activeInstanceId === instance.id) {
      $('dmmUnitMetric').textContent = display.unit;
      state.dmm.trendChart.options.scales.y.title.text = display.unit;
      state.dmm.adevChart.options.scales.y.title.text = `ADEV (${display.unit})`;
    }
  }
  instance.values.push({ x: Number(data.elapsed_s), y: Number(data.value) * display.scale });
  if (instance.values.length > instance.maxPoints) instance.values.splice(0, instance.values.length - instance.maxPoints);
  if (state.activeInstanceId === instance.id) {
    syncWaveformChart(instance);
  }

  const stats = data.stats || {};
  instance.valueMetric = formatMeasurement(Number(stats.latest) * display.scale);
  instance.minMetric = formatMeasurement(Number(stats.minimum) * display.scale);
  instance.maxMetric = formatMeasurement(Number(stats.maximum) * display.scale);
  instance.avgMetric = formatMeasurement(Number(stats.average) * display.scale);
  instance.sampleRateMetric = formatSampleRate(stats.count, data.elapsed_s);
  instance.launcherValue = `${instance.valueMetric} ${instance.unit}`;
  if (state.activeInstanceId === instance.id) {
    $('dmmValueMetric').textContent = instance.valueMetric;
    $('dmmMinMetric').textContent = instance.minMetric;
    $('dmmMaxMetric').textContent = instance.maxMetric;
    $('dmmAvgMetric').textContent = instance.avgMetric;
    $('dmmSampleRateMetric').textContent = instance.sampleRateMetric;
  }
  scheduleFullWaveformRefresh(instance);
  syncLauncherStatus();
}

function handleDmmAdev(data, instance) {
  const display = currentDmmScaleAndUnit(instance);
  const tau = data.tau_s || [];
  const adev = data.adev || [];
  const points = [];
  for (let i = 0; i < tau.length; i += 1) {
    const x = Number(tau[i]);
    const y = Number(adev[i]) * display.scale;
    if (x > 0 && y > 0) points.push({ x, y });
  }
  instance.adevPoints = points;
  if (state.activeInstanceId === instance.id) {
    state.dmm.adevChart.options.scales.y.title.text = `ADEV (${display.unit})`;
    state.dmm.adevChart.data.datasets[0].data = points;
    state.dmm.adevChart.update('none');
  }
}

function formatWavelengthNm(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric.toFixed(6) : '--';
}

async function loadWlmOptions() {
  const instance = state.wlm;
  const instanceId = instance?.id;
  if (!instanceId) throw new Error('No Wavelength Meter instance is active');
  const options = await api(`/api/instruments/${encodeURIComponent(instanceId)}/options`);
  if (state.activeInstanceId !== instanceId || state.wlm !== instance) return false;
  state.wlmOptions = options;
  applyWlmSettings({
    ...(options.defaults || {}),
    ...(instance.settings || {})
  });
  syncWlmControlState();
  return true;
}

function wlmUsbResource() {
  return String(state.wlmOptions?.usb_resource || WLM_USB_RESOURCE).trim() || WLM_USB_RESOURCE;
}

function normalizedWlmConnectionMode(config = {}) {
  return config.connection_mode === 'ethernet' ? 'ethernet' : 'usb';
}

function currentWlmConnectionMode(instance = state.wlm) {
  const pressedButton = document.querySelector('[data-wlm-connection-mode][aria-pressed="true"]');
  if (state.activeInstanceId === instance?.id && pressedButton) {
    return pressedButton.dataset.wlmConnectionMode;
  }
  return normalizedWlmConnectionMode(instance?.settings || {});
}

function wlmEthernetResource(config = {}) {
  return String(config.ethernet_resource || '').trim();
}

function applyWlmConnectionMode(mode, config = state.wlm?.settings || {}) {
  const normalizedMode = mode === 'ethernet' ? 'ethernet' : 'usb';
  document.querySelectorAll('[data-wlm-connection-mode]').forEach((button) => {
    button.setAttribute('aria-pressed', String(button.dataset.wlmConnectionMode === normalizedMode));
  });
  $('wlmResource').value = normalizedMode === 'usb'
    ? wlmUsbResource()
    : wlmEthernetResource(config);
  if (state.wlm?.id) {
    state.wlm.settings = {
      ...(state.wlm.settings || {}),
      connection_mode: normalizedMode,
      resource: $('wlmResource').value,
      ethernet_resource: wlmEthernetResource(config)
    };
  }
}

function selectWlmConnectionMode(mode) {
  const instance = state.wlm;
  if (!instance?.id || instance.running || instance.pendingAction || state.connectionCheckingIds.has(instance.id)) return;
  const currentMode = currentWlmConnectionMode(instance);
  const currentResource = $('wlmResource').value.trim();
  const nextSettings = { ...(instance.settings || {}) };
  if (currentMode === 'ethernet' && currentResource) {
    nextSettings.ethernet_resource = currentResource;
  }
  applyWlmConnectionMode(mode, nextSettings);
  syncWlmControlState();
  scheduleConfigSave();
}

function applyWlmSettings(config) {
  const connectionMode = normalizedWlmConnectionMode(config);
  applyWlmConnectionMode(connectionMode, config);
  if (state.wlm?.id) {
    state.wlm.settings = {
      ...(state.wlm.settings || {}),
      ...config,
      connection_mode: connectionMode,
      resource: $('wlmResource').value,
      ethernet_resource: wlmEthernetResource(config)
    };
  }
  syncWlmControlState();
}

function syncWlmControlState() {
  const running = Boolean(state.wlm.running || state.wlm.pendingAction);
  const checking = state.connectionCheckingIds.has(state.wlm.id);
  const connectionMode = currentWlmConnectionMode();
  document.querySelectorAll('[data-wlm-connection-mode]').forEach((button) => {
    button.disabled = running || checking;
  });
  const showEthernetResource = connectionMode === 'ethernet';
  $('wlmEndpointLabel').classList.toggle('hidden', !showEthernetResource);
  $('wlmEthernetResourceRow').classList.toggle('hidden', !showEthernetResource);
  $('wlmResource').readOnly = connectionMode === 'usb';
  $('wlmResource').disabled = running || checking;
  $('wlmCheckEndpoint').disabled = running || checking;
  $('wlmCheckEndpoint').setAttribute('aria-busy', String(checking));
  syncRunSwitch(state.wlm);
}

function readWlmSettings(instance = state.wlm) {
  const current = instance?.settings || {};
  const connectionMode = currentWlmConnectionMode(instance);
  const visibleResource = $('wlmResource').value.trim();
  const ethernetResource = connectionMode === 'ethernet'
    ? visibleResource
    : wlmEthernetResource(current);
  return {
    connection_mode: connectionMode,
    resource: connectionMode === 'usb' ? wlmUsbResource() : visibleResource,
    ethernet_resource: ethernetResource
  };
}

function readWlmConfig(instance = state.wlm) {
  return {
    ...readWlmSettings(instance),
    library_dir: configuredLibraryDir(),
    display_name: $('wlmAcquisitionName').value.trim()
  };
}

async function checkWlmEndpoint({ persistSettings = true } = {}) {
  const instance = state.wlm;
  const instanceId = instance?.id;
  if (!instanceId || instance.running || instance.pendingAction || state.connectionCheckingIds.has(instanceId)) return null;
  const typedResource = $('wlmResource').value;
  const settings = readWlmSettings();
  if (settings.connection_mode === 'ethernet' && !settings.resource) {
    setInstrumentStatus(instance, 'Enter the wavelength meter Ethernet endpoint before checking', 'OFFLINE', 'warning');
    return null;
  }
  const isStillActive = () => state.activeInstanceId === instanceId && state.wlm === instance;
  if (persistSettings) clearTimeout(state.configSaveTimer);
  state.connectionCheckingIds.add(instanceId);
  syncWlmControlState();
  setInstrumentStatus(state.wlm, 'Checking wavelength meter endpoint', 'OFFLINE');
  try {
    if (persistSettings) {
      const updated = await api(`/api/instruments/${encodeURIComponent(instanceId)}/settings`, {
        method: 'POST',
        body: JSON.stringify(settings)
      });
      instance.settings = updated.settings || settings;
      state.instruments = state.instruments.map((item) => (
        item.id === instanceId ? { ...item, settings: instance.settings } : item
      ));
    }
    const payload = await api(`/api/instruments/${encodeURIComponent(instanceId)}/check`, {
      method: 'POST',
      body: JSON.stringify(settings)
    });
    const identity = String(payload.identity || payload.resource || '').trim();
    const statusText = identity ? `Connected: ${identity}` : 'Connection check passed';
    const statusBadge = 'READY';
    if (!isStillActive()) {
      setInstrumentStatus(instance, statusText, statusBadge);
      return payload;
    }
    $('wlmResource').value = typedResource;
    setInstrumentStatus(state.wlm, statusText, 'READY');
    return payload;
  } catch (error) {
    reportInstrumentError(instance, 'Connection check failed', error);
    return null;
  } finally {
    state.connectionCheckingIds.delete(instanceId);
    if (isStillActive()) {
      $('wlmResource').value = typedResource;
      syncWlmControlState();
    }
  }
}

function resetWlmDisplay(instance = state.wlm) {
  resetFullWaveform(instance);
  instance.runPath = '';
  instance.values = [];
  instance.adevPoints = [];
  instance.valueMetric = '--';
  instance.minMetric = '--';
  instance.maxMetric = '--';
  instance.avgMetric = '--';
  instance.sampleRateMetric = '--';
  instance.launcherValue = '--';
  syncWaveformChart(instance);
  if (state.activeInstanceId !== instance.id || state.wlm !== instance) {
    syncLauncherStatus();
    return;
  }
  ['wlmValueMetric', 'wlmMinMetric', 'wlmMaxMetric', 'wlmAvgMetric'].forEach((id) => {
    $(id).textContent = '--';
  });
  $('wlmSampleRateMetric').textContent = '--';
  instance.adevChart.data.datasets[0].data = [];
  instance.adevChart.update('none');
  syncLauncherStatus();
}

function syncWlmChartFromInstance(instance) {
  syncWaveformChart(instance);
  state.wlm.adevChart.data.datasets[0].data = instance.adevPoints || [];
  state.wlm.trendChart.update('none');
  state.wlm.adevChart.update('none');
}

async function startWlm(instance = state.wlm) {
  const instanceId = instance?.id;
  if (!instanceId) throw new Error('No Wavelength Meter instance is active');
  const settings = readWlmSettings(instance);
  const config = readWlmConfig(instance);
  instance.acquisitionName = config.display_name;
  instance.settings = settings;
  resetWlmDisplay(instance);
  const updated = await api(`/api/instruments/${encodeURIComponent(instanceId)}/settings`, {
    method: 'POST',
    body: JSON.stringify(settings)
  });
  instance.settings = updated.settings || settings;
  state.instruments = state.instruments.map((item) => (
    item.id === instanceId ? { ...item, settings: instance.settings } : item
  ));
  await api(`/api/instruments/${encodeURIComponent(instanceId)}/start`, {
    method: 'POST',
    body: JSON.stringify(config)
  });
}

async function stopWlm(instance = state.wlm) {
  const instanceId = instance?.id;
  if (!instanceId) throw new Error('No Wavelength Meter instance is active');
  await api(`/api/instruments/${encodeURIComponent(instanceId)}/stop`, {
    method: 'POST',
    body: '{}'
  });
}

function handleWlmSample(data, instance) {
  const wavelengthNm = Number(data.wavelength_nm);
  const elapsedS = Number(data.elapsed_s);
  if (!Number.isFinite(wavelengthNm) || !Number.isFinite(elapsedS)) return;
  instance.values.push({ x: elapsedS, y: wavelengthNm });
  if (instance.values.length > instance.maxPoints) {
    instance.values.splice(0, instance.values.length - instance.maxPoints);
  }
  if (state.activeInstanceId === instance.id) {
    syncWaveformChart(instance);
  }

  const stats = data.stats || {};
  instance.valueMetric = formatWavelengthNm(stats.latest ?? wavelengthNm);
  instance.minMetric = formatWavelengthNm(stats.minimum ?? wavelengthNm);
  instance.maxMetric = formatWavelengthNm(stats.maximum ?? wavelengthNm);
  instance.avgMetric = formatWavelengthNm(stats.average ?? wavelengthNm);
  instance.sampleRateMetric = formatSampleRate(stats.count, elapsedS);
  instance.launcherValue = `${instance.valueMetric} nm`;
  if (state.activeInstanceId === instance.id) {
    $('wlmValueMetric').textContent = instance.valueMetric;
    $('wlmMinMetric').textContent = instance.minMetric;
    $('wlmMaxMetric').textContent = instance.maxMetric;
    $('wlmAvgMetric').textContent = instance.avgMetric;
    $('wlmSampleRateMetric').textContent = instance.sampleRateMetric;
  }
  scheduleFullWaveformRefresh(instance);
  syncLauncherStatus();
}

function handleWlmAdev(data, instance) {
  const tau = data.tau_s || [];
  const adev = data.adev_nm || [];
  const points = [];
  for (let i = 0; i < tau.length; i += 1) {
    const x = Number(tau[i]);
    const y = Number(adev[i]);
    if (x > 0 && y > 0) points.push({ x, y });
  }
  instance.adevPoints = points;
  if (state.activeInstanceId === instance.id) {
    state.wlm.adevChart.data.datasets[0].data = points;
    state.wlm.adevChart.update('none');
  }
}

function normalizedOpmDisplayUnit(value) {
  return ['W', 'mW', 'dBm'].includes(value) ? value : 'mW';
}

function powerValueForDisplay(valueW, unit) {
  const numeric = Number(valueW);
  if (!Number.isFinite(numeric)) return null;
  if (unit === 'W') return numeric;
  if (unit === 'mW') return numeric * 1000;
  if (unit === 'dBm') return numeric > 0 ? 10 * Math.log10(numeric / 0.001) : null;
  return numeric * 1000;
}

function formatPowerForDisplay(valueW, unit) {
  const displayValue = powerValueForDisplay(valueW, unit);
  if (displayValue === null) {
    return unit === 'dBm' && Number.isFinite(Number(valueW)) ? 'N/A' : '--';
  }
  return formatMeasurement(displayValue);
}

function currentOpmDisplayUnit(instance = state.opm) {
  if (state.activeInstanceId === instance?.id) {
    return normalizedOpmDisplayUnit($('opmDisplayUnit').value);
  }
  return normalizedOpmDisplayUnit(instance?.settings?.display_unit || instance?.displayUnit);
}

function updateOpmMetricsFromRaw(instance) {
  const displayUnit = currentOpmDisplayUnit(instance);
  instance.displayUnit = displayUnit;
  const stats = instance.statsW;
  if (!stats) {
    instance.valueMetric = '--';
    instance.minMetric = '--';
    instance.maxMetric = '--';
    instance.avgMetric = '--';
    instance.sampleRateMetric = '--';
    instance.launcherValue = '--';
    return;
  }
  instance.valueMetric = formatPowerForDisplay(stats.latest, displayUnit);
  instance.minMetric = formatPowerForDisplay(stats.minimum, displayUnit);
  instance.maxMetric = formatPowerForDisplay(stats.maximum, displayUnit);
  instance.avgMetric = formatPowerForDisplay(stats.average, displayUnit);
  instance.launcherValue = `${instance.valueMetric} ${displayUnit}`;
}

function syncOpmDisplayFromRaw(instance = state.opm) {
  const displayUnit = currentOpmDisplayUnit(instance);
  instance.displayUnit = displayUnit;
  instance.settings = { ...(instance.settings || {}), display_unit: displayUnit };
  updateOpmMetricsFromRaw(instance);
  if (state.activeInstanceId !== instance.id) return;

  syncWaveformChart(instance);
  state.opm.adevChart.data.datasets[0].data = instance.adevPointsW || [];
  state.opm.adevChart.options.scales.y.title.text = 'ADEV (W)';
  state.opm.adevChart.update('none');

  $('opmUnitMetric').textContent = displayUnit;
  $('opmValueMetric').textContent = instance.valueMetric;
  $('opmMinMetric').textContent = instance.minMetric;
  $('opmMaxMetric').textContent = instance.maxMetric;
  $('opmAvgMetric').textContent = instance.avgMetric;
  $('opmSampleRateMetric').textContent = instance.sampleRateMetric;
}

function opmSelectItems(values, suffix = '') {
  return (values || []).map((item) => {
    if (item && typeof item === 'object') {
      return {
        value: item.value,
        label: item.label ?? `${item.value}${suffix}`
      };
    }
    return { value: item, label: `${item}${suffix}` };
  });
}

async function loadOpmOptions() {
  if (!state.opm?.id) throw new Error('No Optical Power Meter instance is active');
  state.opmOptions = await api(`/api/instruments/${encodeURIComponent(state.opm.id)}/options`);
  populateSelect(
    $('opmDisplayUnit'),
    opmSelectItems(state.opmOptions.units || ['W', 'mW', 'dBm'])
  );
  populateSelect(
    $('opmManualRange'),
    opmSelectItems(state.opmOptions.range_options || [])
  );
  applyOpmSettings({
    ...(state.opmOptions.defaults || {}),
    ...(state.opm.settings || {})
  });
  syncOpmControlState();
}

function applyOpmSettings(config) {
  $('opmResource').value = config.resource || '';
  $('opmWavelength').value = config.wavelength_nm ?? 852;
  setSelectValueOrDefault($('opmDisplayUnit'), normalizedOpmDisplayUnit(config.display_unit || 'mW'));
  $('opmAutorange').checked = Boolean(config.autorange ?? true);
  setSelectValueOrDefault($('opmManualRange'), config.manual_range_w ?? $('opmManualRange').value);
  if (state.opm?.id) {
    state.opm.settings = { ...(state.opm.settings || {}), ...config };
    state.opm.displayUnit = normalizedOpmDisplayUnit(config.display_unit || 'mW');
  }
  syncOpmTickSliders();
  syncOpmDisplayFromRaw();
}

function syncOpmTickSliders() {
  syncTickSlider('opmManualRange');
}

function syncOpmControlState() {
  const running = Boolean(state.opm.running || state.opm.pendingAction);
  const checking = state.connectionCheckingIds.has(state.opm.id);
  const unavailable = Boolean(state.opm.driverUnavailable);
  $('opmResource').disabled = running || checking || unavailable;
  $('opmRefreshResources').disabled = running || checking || unavailable;
  $('opmCheckConnection').disabled = running || checking || unavailable;
  $('opmCheckConnection').setAttribute('aria-busy', String(checking));
  $('opmWavelength').disabled = running || unavailable;
  $('opmDisplayUnit').disabled = unavailable;
  $('opmAutorange').disabled = running || unavailable;
  $('opmManualRange').disabled = $('opmAutorange').checked || running || unavailable;
  syncRunSwitch(state.opm);
  syncOpmTickSliders();
}

function opmResourceName(detail) {
  return detail?.resource || '';
}

function opmResourceLabel(detail) {
  const identity = [detail?.model, detail?.serial].filter(Boolean).join(' / ');
  const availability = detail?.available === false ? 'Unavailable' : '';
  return [identity, availability].filter(Boolean).join(' - ');
}

const OPM_DRIVER_UNAVAILABLE_STATUS = 'TLPMX driver unavailable. Install Thorlabs Optical Power Monitor and select TLPMX in Driver Switcher.';

function opmDriverIsUnavailable(payload) {
  const error = String(payload?.error || '');
  return payload?.error_code === 'tlpmx_driver_unavailable'
    || error.startsWith('Thorlabs TLPMX driver is unavailable.')
    || error.startsWith('TLPMX driver unavailable.')
    || (!error && payload?.driver_available === false);
}

function syncOpmDriverOverlay(instance = state.opm) {
  const overlay = $('opmDriverOverlay');
  const dashboard = $('opmDashboard');
  if (!overlay || !dashboard || !instance) return;
  const activeInstance = state.activeInstanceId === instance.id && state.opm === instance;
  const unavailable = activeInstance && Boolean(instance.driverUnavailable);
  const wasHidden = overlay.classList.contains('hidden');
  overlay.classList.toggle('hidden', !unavailable);
  overlay.setAttribute('aria-hidden', String(!unavailable));
  if (unavailable) {
    dashboard.setAttribute('inert', '');
    dashboard.setAttribute('aria-hidden', 'true');
    $('opmDriverErrorMessage').textContent = instance.driverError || OPM_DRIVER_UNAVAILABLE_STATUS;
    if (wasHidden && state.currentView === 'opm') {
      requestAnimationFrame(() => $('opmRetryDriver').focus());
    }
  } else {
    dashboard.removeAttribute('inert');
    dashboard.removeAttribute('aria-hidden');
  }
}

function setOpmDriverAvailability(payload, instance = state.opm) {
  if (!instance) return;
  instance.driverUnavailable = opmDriverIsUnavailable(payload);
  instance.driverError = instance.driverUnavailable
    ? OPM_DRIVER_UNAVAILABLE_STATUS
    : '';
  if (state.opm === instance) {
    syncOpmControlState();
    syncOpmDriverOverlay(instance);
  }
}

function opmDiscoveryStatus(payload, resourceCount) {
  const error = String(payload?.error || '');
  if (opmDriverIsUnavailable(payload)) {
    return OPM_DRIVER_UNAVAILABLE_STATUS;
  }
  if (error) {
    return `TLPMX discovery failed: ${error}`;
  }
  return `Detected ${resourceCount} optical power meter resource(s)`;
}

async function refreshOpmResources() {
  const instance = state.opm;
  const instanceId = instance?.id;
  if (!instanceId) throw new Error('No Optical Power Meter instance is active');
  setDiscoveredInstrumentCount('opmResourceCount', 0);
  setInstrumentStatus(instance, 'Detecting Thorlabs TLPMX resources', 'OFFLINE');
  const payload = await api(`/api/instruments/${encodeURIComponent(instanceId)}/resources`);
  setOpmDriverAvailability(payload, instance);
  if (state.activeInstanceId !== instanceId || state.opm !== instance) return payload;
  const list = $('opmResourceList');
  const details = Array.isArray(payload.resource_details) ? payload.resource_details : [];
  const detailMap = new Map(details.map((detail) => [opmResourceName(detail), detail]));
  const resources = Array.isArray(payload.resources) ? payload.resources : [];
  list.innerHTML = '';
  resources.forEach((resource) => {
    const option = document.createElement('option');
    option.value = resource;
    const label = opmResourceLabel(detailMap.get(resource));
    if (label) option.label = label;
    list.appendChild(option);
  });
  if (!$('opmResource').value && resources.length) $('opmResource').value = resources[0];
  setDiscoveredInstrumentCount('opmResourceCount', payload.valid_count);
  setInstrumentStatus(instance, opmDiscoveryStatus(payload, payload.valid_count || 0), 'OFFLINE', payload.error || instance.driverUnavailable ? 'warning' : 'info');
  return payload;
}

async function retryOpmDriverDiscovery() {
  const instance = state.opm;
  const button = $('opmRetryDriver');
  button.disabled = true;
  button.textContent = 'Checking...';
  try {
    await refreshOpmResources();
  } catch (error) {
    reportInstrumentError(instance, 'Could not discover optical power meters', error);
  } finally {
    button.disabled = false;
    button.textContent = 'Check again';
  }
}

function readOpmSettings() {
  return {
    resource: $('opmResource').value.trim(),
    wavelength_nm: Number.parseFloat($('opmWavelength').value),
    display_unit: normalizedOpmDisplayUnit($('opmDisplayUnit').value),
    autorange: $('opmAutorange').checked,
    manual_range_w: Number.parseFloat($('opmManualRange').value),
    channel: 1
  };
}

function readOpmConfig() {
  return {
    ...readOpmSettings(),
    library_dir: configuredLibraryDir(),
    display_name: $('opmAcquisitionName').value.trim()
  };
}

function resetOpmDisplay() {
  resetFullWaveform(state.opm);
  state.opm.runPath = '';
  state.opm.powerValuesW = [];
  state.opm.adevPointsW = [];
  state.opm.statsW = null;
  state.opm.valueMetric = '--';
  state.opm.minMetric = '--';
  state.opm.maxMetric = '--';
  state.opm.avgMetric = '--';
  state.opm.sampleRateMetric = '--';
  state.opm.launcherValue = '--';
  syncOpmDisplayFromRaw();
  syncLauncherStatus();
}

async function startOpm(instance = state.opm) {
  resetOpmDisplay();
  const config = readOpmConfig();
  instance.settings = readOpmSettings();
  await api(`/api/instruments/${encodeURIComponent(instance.id)}/settings`, {
    method: 'POST',
    body: JSON.stringify(instance.settings)
  });
  await api(`/api/instruments/${encodeURIComponent(instance.id)}/start`, {
    method: 'POST',
    body: JSON.stringify(config)
  });
}

async function stopOpm(instance = state.opm) {
  await api(`/api/instruments/${encodeURIComponent(instance.id)}/stop`, {
    method: 'POST',
    body: '{}'
  });
}

function handleOpmSample(data, instance) {
  const valueW = Number(data.power_w);
  const elapsedS = Number(data.elapsed_s);
  if (!Number.isFinite(valueW) || !Number.isFinite(elapsedS)) return;
  instance.powerValuesW.push({ x: elapsedS, y: valueW });
  if (instance.powerValuesW.length > instance.maxPoints) {
    instance.powerValuesW.splice(0, instance.powerValuesW.length - instance.maxPoints);
  }
  const stats = data.stats || {};
  instance.sampleRateMetric = formatSampleRate(stats.count, elapsedS);
  instance.statsW = {
    latest: Number(stats.latest ?? valueW),
    minimum: Number(stats.minimum ?? valueW),
    maximum: Number(stats.maximum ?? valueW),
    average: Number(stats.average ?? valueW)
  };
  syncOpmDisplayFromRaw(instance);
  scheduleFullWaveformRefresh(instance);
  syncLauncherStatus();
}

function handleOpmAdev(data, instance) {
  const tau = data.tau_s || [];
  const adev = data.adev_w || [];
  const points = [];
  for (let i = 0; i < tau.length; i += 1) {
    const x = Number(tau[i]);
    const y = Number(adev[i]);
    if (x > 0 && y > 0) points.push({ x, y });
  }
  instance.adevPointsW = points;
  if (state.activeInstanceId === instance.id) {
    state.opm.adevChart.options.scales.y.title.text = 'ADEV (W)';
    state.opm.adevChart.data.datasets[0].data = points;
    state.opm.adevChart.update('none');
  }
}

function connectInstrumentEvents() {
  const events = new EventSource(`${state.backendUrl}/api/instruments/events`);
  events.addEventListener('instrument', (event) => handleInstrumentEvent(JSON.parse(event.data)));
}

function handleInstrumentEvent(payload) {
  const instance = state.instances[payload.instrument_id];
  if (!instance) return;
  const data = payload.data || {};
  const terminal = payload.event === 'done' || payload.event === 'error';
  const started = payload.event === 'data' || payload.event === 'sample' ||
    (payload.event === 'status' && (data.kind === 'running' || data.text === 'Acquisition running'));
  if (terminal || (started && !instance.running)) {
    instance.running = !terminal;
    if (terminal || instance.pendingAction?.starting) instance.pendingAction = null;
    syncInstrumentControlState(instance);
    syncAcquisitionIndicators();
  }
  if (payload.event === 'status') {
    if (data.kind === 'error') {
      reportInstrumentError(instance, 'Instrument error', data.text, data.details);
    } else {
      setInstrumentStatus(instance, data.text || 'Offline', instance.type === 'ufc' ? data.badge : statusKindToBadge(data.kind),
        data.severity === 'warning' || ['warning', 'reconnecting'].includes(data.kind) ? 'warning' : 'info');
    }
  } else if (payload.event === 'data') {
    if (instance.type !== 'ufc') return;
    handleData(data, instance);
  } else if (payload.event === 'adev') {
    if (instance.type === 'ufc') handleAdev(data, instance);
    else if (instance.type === 'dmm') handleDmmAdev(data, instance);
    else if (instance.type === 'wlm') handleWlmAdev(data, instance);
    else if (instance.type === 'opm') handleOpmAdev(data, instance);
  } else if (payload.event === 'recoverable_error') {
    setInstrumentStatus(instance, `Transient ${data.operation} error #${data.total_errors}; acquisition continues`, 'BUSY', 'warning');
  } else if (payload.event === 'session_opened') {
    instance.runPath = data.library_file || '';
    resetFullWaveform(instance);
  } else if (payload.event === 'sample') {
    if (instance.type === 'dmm') handleDmmSample(data, instance);
    else if (instance.type === 'wlm') handleWlmSample(data, instance);
    else if (instance.type === 'opm') handleOpmSample(data, instance);
  } else if (payload.event === 'done') {
    setInstrumentStatus(instance, data.text || 'Stopped', 'READY', data.severity || 'info');
    if (data.library_file) instance.runPath = data.library_file;
    scheduleFullWaveformRefresh(instance, true);
    if (instance.type === 'ufc') {
      scheduleUfcNoiseUpdate(instance);
    }
  } else if (payload.event === 'error') {
    instance.badge = 'OFFLINE';
    reportInstrumentError(instance, 'Acquisition failed', data.text || 'Instrument error', data.details);
  }
}

async function loadInstruments() {
  const payload = await api('/api/instruments');
  state.instruments = payload.instruments || [];
  state.instruments.forEach((item) => upsertRuntime(item));
  Object.keys(state.instances).forEach((id) => {
    if (!state.instruments.some((item) => item.id === id)) delete state.instances[id];
  });
  if (!state.activeInstanceId || !state.instances[state.activeInstanceId]) {
    state.activeInstanceId = state.instruments[0]?.id || '';
  }
  renderLauncherCards();
}

async function addInstrument(kind) {
  state.launcherActionInstanceId = '';
  const item = await api('/api/instruments', {
    method: 'POST',
    body: JSON.stringify({ type: kind })
  });
  upsertRuntime(item);
  state.instruments.push(item);
  renderLauncherCards();
  closeAddInstrumentMenu();
}

async function deleteInstrumentInstance(instanceId) {
  const instance = state.instances[instanceId];
  if (!instance) return;
  if (instance.running || instance.pendingAction) {
    setInstrumentStatus(instance, 'Stop acquisition before deleting this instrument.', null, 'warning');
    return;
  }
  await api(`/api/instruments/${encodeURIComponent(instanceId)}`, { method: 'DELETE' });
  state.launcherActionInstanceId = '';
  delete state.instances[instanceId];
  state.instruments = state.instruments.filter((item) => item.id !== instanceId);
  if (state.activeInstanceId === instanceId) state.activeInstanceId = '';
  renderLauncherCards();
}

function setAddInstrumentMenuOpen(open) {
  const menu = $('addInstrumentMenu');
  const button = $('addInstrument');
  if (!menu || !button) return;
  clearTimeout(state.addInstrumentMenuCloseTimer);
  if (open) setLauncherActionMode();
  menu.classList.remove('closing');
  menu.hidden = !open;
  button.setAttribute('aria-expanded', String(open));
}

function toggleAddInstrumentMenu() {
  setAddInstrumentMenuOpen($('addInstrumentMenu')?.hidden ?? true);
}

function closeAddInstrumentMenu() {
  const menu = $('addInstrumentMenu');
  const button = $('addInstrument');
  if (!menu || !button || menu.hidden || menu.classList.contains('closing')) return;
  button.setAttribute('aria-expanded', 'false');
  menu.classList.add('closing');
  state.addInstrumentMenuCloseTimer = window.setTimeout(() => {
    menu.hidden = true;
    menu.classList.remove('closing');
  }, 150);
}

function closeModal(dialog) {
  if (!dialog?.open || dialog.classList.contains('closing')) return;
  dialog.classList.add('closing');
  window.setTimeout(() => {
    dialog.close();
    dialog.classList.remove('closing');
  }, 160);
}

function openGlobalSettings() {
  applyPlatformSettings(state.config?.platform || {});
  $('globalSettingsDialog').classList.remove('closing');
  $('globalSettingsDialog').showModal();
}


function syncResetConfigSlider() {
  const slider = $('resetConfigSlider');
  const value = Math.max(0, Math.min(100, Number(slider.value) || 0));
  slider.style.setProperty('--reset-progress', `${value}%`);
  $('resetConfigSliderLabel').textContent = state.resetConfigInProgress
    ? 'Resetting and restarting…'
    : value >= 100
      ? 'Release to reset and restart'
      : 'Slide to reset and restart';
}

function setResetConfigBusy(busy) {
  state.resetConfigInProgress = Boolean(busy);
  $('resetConfigSlider').disabled = state.resetConfigInProgress;
  $('resetConfigDialog').querySelectorAll('[value="cancel"]').forEach((button) => {
    button.disabled = state.resetConfigInProgress;
  });
  syncResetConfigSlider();
}

function resetResetConfigDialog() {
  $('resetConfigSlider').value = '0';
  setResetConfigBusy(false);
}

function openResetConfigDialog() {
  resetResetConfigDialog();
  const dialog = $('resetConfigDialog');
  dialog.classList.remove('closing');
  if (!dialog.open) dialog.showModal();
  window.requestAnimationFrame(() => $('cancelResetConfig').focus());
}

async function requestConfigReset() {
  return window.openUfc.resetConfig();
}

async function confirmResetConfig() {
  if (state.resetConfigInProgress || Number($('resetConfigSlider').value) < 100) return;
  setResetConfigBusy(true);
  try {
    const result = await requestConfigReset();
    if (result?.ok === false) {
      throw new Error(result.error || 'Configuration reset could not start.');
    }
  } catch (error) {
    showError('Could not reset configuration', error);
    $('resetConfigSlider').value = '0';
    setResetConfigBusy(false);
  }
}

function handleResetConfigSliderChange() {
  if (Number($('resetConfigSlider').value) >= 100) {
    confirmResetConfig();
    return;
  }
  $('resetConfigSlider').value = '0';
  syncResetConfigSlider();
}

function openAboutDialog() {
  $('aboutDialog').classList.remove('closing');
  $('aboutDialog').showModal();
}

async function chooseGlobalOutputDir() {
  const selected = await window.openUfc.selectDirectory({ title: 'Choose library folder', defaultPath: $('globalLibraryDir').value || configuredLibraryDir() });
  if (selected) {
    $('globalLibraryDir').value = selected;
  }
}

async function saveGlobalSettings() {
  const libraryDir = $('globalLibraryDir').value.trim() || 'runs';
  state.config = await saveConfigPatch({
    platform: {
      library_dir: libraryDir,
      color_mode: state.colorMode
    }
  });
  applyPlatformSettings(state.config.platform || {});
  closeModal($('globalSettingsDialog'));
  if (state.currentView === 'library') await loadLibrary();
}

function syncTitleBarScrollState() {
  const titleBar = document.querySelector('.title-bar');
  const appShell = document.querySelector('.app-shell');
  if (!titleBar || !appShell) return;
  titleBar.classList.toggle('scrolled', appShell.scrollTop > 2);
}

function wireUi() {
  $('errorDialog').addEventListener('close', () => {
    errorQueue.shift();
    showNextError();
  });
  window.openUfc.onBackendError((message) => showError('Measurement service stopped', message));
  $('globalSettingsDialog').addEventListener('close', () => {
    previewColorMode(state.config?.platform?.color_mode || 'auto').catch((error) => showError('Could not restore appearance', error));
  });
  document.querySelectorAll('[data-color-mode]').forEach((button) => {
    button.addEventListener('click', () => previewColorMode(button.dataset.colorMode).catch((error) => showError('Could not change appearance', error)));
  });
  const syncMaximized = (maximized) => {
    document.body.classList.toggle('maximized', maximized);
    $('maximizeWindow').setAttribute('aria-label', maximized ? 'Restore window' : 'Maximize');
  };
  window.openUfc.onMaximizedChanged(syncMaximized);
  window.openUfc.isWindowMaximized().then(syncMaximized);
  document.querySelectorAll('.modal').forEach((dialog) => {
    dialog.addEventListener('cancel', (event) => {
      event.preventDefault();
      if (dialog.id === 'deleteLibraryDialog' && state.library.deleteInProgress) return;
      if (dialog.id === 'resetConfigDialog' && state.resetConfigInProgress) return;
      closeModal(dialog);
    });
    dialog.querySelectorAll('[value="cancel"]').forEach((button) => {
      button.addEventListener('click', (event) => {
        event.preventDefault();
        if (dialog.id === 'deleteLibraryDialog' && state.library.deleteInProgress) return;
        if (dialog.id === 'resetConfigDialog' && state.resetConfigInProgress) return;
        closeModal(dialog);
      });
    });
  });
  $('renameInstrumentDialog').addEventListener('close', () => {
    state.renamingInstrumentId = '';
    state.renameInstrumentSaving = false;
  });
  $('renameInstrumentForm').addEventListener('submit', (event) => {
    event.preventDefault();
    saveRenamedInstrument();
  });
  $('deleteLibraryDialog').addEventListener('close', () => {
    state.library.pendingDeleteFile = '';
    setDeleteLibraryBusy(false);
  });
  $('resetConfigDialog').addEventListener('close', () => {
    if (!state.resetConfigInProgress) resetResetConfigDialog();
  });
  $('deleteLibraryForm').addEventListener('submit', (event) => {
    event.preventDefault();
    confirmDeleteLibraryItem();
  });
  document.querySelectorAll('[data-return-home]').forEach((button) => {
    button.addEventListener('click', navigateHome);
  });
  $('minimizeWindow').addEventListener('click', () => window.openUfc.minimizeWindow());
  $('maximizeWindow').addEventListener('click', () => window.openUfc.toggleMaximizeWindow());
  $('closeWindow').addEventListener('click', () => window.openUfc.closeWindow());
  window.openUfc.onCloseRequested(handleCloseRequested);
  $('runningAcquisitionShortcuts').addEventListener('click', (event) => {
    const button = event.target.closest('[data-running-instance]');
    if (!button) return;
    openRunningAcquisition(button.dataset.runningInstance);
  });
  document.querySelector('.app-shell')?.addEventListener('scroll', syncTitleBarScrollState, { passive: true });
  document.addEventListener('click', (event) => {
    if (!event.target.closest('#addInstrumentMenu') && !event.target.closest('#addInstrument')) {
      closeAddInstrumentMenu();
    }
    if (!event.target.closest('.launcher-card')) {
      setLauncherActionMode();
    }
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      closeAddInstrumentMenu();
      setLauncherActionMode('', { restoreFocus: true });
    }
  });

  $('addInstrument').addEventListener('click', (event) => {
    event.stopPropagation();
    toggleAddInstrumentMenu();
  });
  document.querySelectorAll('[data-add-instrument-type]').forEach((button) => {
    button.addEventListener('click', () => addInstrument(button.dataset.addInstrumentType).catch((error) => showError('Could not add instrument', error)));
  });
  $('refreshResources').addEventListener('click', () => runInstrumentAction(state.ufc, 'Could not discover instruments', refreshResources));
  $('checkConnection').addEventListener('click', () => checkInstrumentConnection('ufc'));
  $('runSwitch').addEventListener('change', () => handleRunSwitchChange('ufc', 'runSwitch', startAcquisition, stopAcquisition));
  $('channel').addEventListener('change', syncUfcTickSliders);
  $('sampleRate').addEventListener('change', syncUfcTickSliders);
  $('openLibrary').addEventListener('click', () => setView('library'));
  $('openDevices').addEventListener('click', () => setView('devices'));
  $('refreshDevices').addEventListener('click', loadDevices);
  $('refreshLibrary').addEventListener('click', () => loadLibrary().catch((error) => reportLibraryError('Could not load Library', error)));
  $('showLibraryInExplorer').addEventListener('click', () => window.openUfc.openLibraryFolder().catch((error) => reportLibraryError('Could not open Library folder', error)));
  $('renameLibraryItem').addEventListener('click', () => renameLibraryItem().catch((error) => reportLibraryError('Could not rename record', error)));
  $('deleteLibraryItem').addEventListener('click', openDeleteLibraryDialog);
  $('exportWaveformCsv').addEventListener('click', () => exportLibrarySeries('waveform').catch((error) => reportLibraryError('Could not export CSV', error)));
  $('exportAdevCsv').addEventListener('click', () => exportLibrarySeries('adev').catch((error) => reportLibraryError('Could not export CSV', error)));
  $('openGlobalSettings').addEventListener('click', openGlobalSettings);
  $('openAbout').addEventListener('click', openAboutDialog);
  $('browseGlobalLibrary').addEventListener('click', () => chooseGlobalOutputDir().catch((error) => showError('Could not open folder picker', error)));
  $('openResetConfig').addEventListener('click', openResetConfigDialog);
  $('resetConfigSlider').addEventListener('input', syncResetConfigSlider);
  $('resetConfigSlider').addEventListener('change', handleResetConfigSliderChange);
  $('saveGlobalSettings').addEventListener('click', () => saveGlobalSettings().catch((error) => {
    showError('Could not save Global Settings', error);
  }));
  [
    'resource',
    'channel',
    'sampleRate',
    'wavelength',
    'divideOpticalFrequency',
    'divideSqrt2'
  ].forEach((id) => {
    $(id).addEventListener('change', scheduleConfigSave);
    $(id).addEventListener('input', scheduleConfigSave);
  });
  $('divideOpticalFrequency').addEventListener('change', syncUfcOpticalFrequencyControls);
  document.querySelectorAll('[data-ufc-analysis]').forEach((button) => {
    button.addEventListener('click', () => {
      selectUfcAnalysisTab(button.dataset.ufcAnalysis);
      saveUfcAnalysisSettings();
    });
    button.addEventListener('keydown', (event) => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const tab = event.key === 'Home' ? 'adev' : event.key === 'End' ? 'fn' : state.ufc.analysisTab === 'fn' ? 'adev' : 'fn';
      $(`ufc${tab === 'fn' ? 'Fn' : 'Adev'}Tab`).focus();
      selectUfcAnalysisTab(tab);
      saveUfcAnalysisSettings();
    });
  });
  document.querySelectorAll('[data-waveform-tab]').forEach((button) => {
    button.addEventListener('click', () => {
      selectWaveformTab(state[button.dataset.waveformType], button.dataset.waveformTab);
    });
    button.addEventListener('keydown', (event) => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === 'Home'
        ? 'recent'
        : event.key === 'End'
          ? 'full'
          : button.dataset.waveformTab === 'full' ? 'recent' : 'full';
      const ui = waveformUi[button.dataset.waveformType];
      $(`${button.dataset.waveformType}${next === 'full' ? 'Full' : 'Recent'}WaveformTab`).focus();
      selectWaveformTab(state[button.dataset.waveformType], next);
      if (ui) syncWaveformTabs(state[button.dataset.waveformType]);
    });
  });
  ['fnSegmentLength', 'fnWindow', 'fnOverlap'].forEach((id) => {
    $(id).addEventListener('change', () => {
      saveUfcAnalysisSettings();
      state.ufc.fnRevision = (state.ufc.fnRevision || 0) + 1;
      state.ufc.fnPoints = [];
      state.ufc.fnStatus = '';
      syncUfcNoiseChart();
      scheduleUfcNoiseUpdate(state.ufc);
    });
  });
  ['fnLogX', 'fnLogY'].forEach((id) => {
    $(id).addEventListener('change', () => {
      syncUfcNoiseChart();
      saveUfcAnalysisSettings();
    });
  });

  $('dmmRefreshResources').addEventListener('click', () => runInstrumentAction(state.dmm, 'Could not discover instruments', refreshDmmResources));
  $('dmmCheckConnection').addEventListener('click', () => checkInstrumentConnection('dmm'));
  document.querySelectorAll('[data-slider-select]').forEach((slider) => {
    slider.addEventListener('click', (event) => {
      const button = event.target.closest('[data-tick-value]');
      if (!button) return;
      setTickSliderValue(slider.dataset.sliderSelect, button.dataset.tickValue);
    });
  });
  $('dmmFunction').addEventListener('change', () => {
    syncDmmFunctionControls();
    syncDmmControlState();
    scheduleConfigSave();
  });
  $('dmmAutorange').addEventListener('change', () => {
    syncDmmDisplayUnitFromControls();
    syncDmmControlState();
    scheduleConfigSave();
  });
  $('dmmRunSwitch').addEventListener('change', () => handleRunSwitchChange('dmm', 'dmmRunSwitch', startDmm, stopDmm));
  $('dmmRange').addEventListener('change', () => {
    syncDmmDisplayUnitFromControls();
    syncDmmTickSliders();
  });
  $('dmmNplc').addEventListener('change', syncDmmTickSliders);
  [
    'dmmResource',
    'dmmRange',
    'dmmNplc'
  ].forEach((id) => {
    $(id).addEventListener('change', scheduleConfigSave);
    $(id).addEventListener('input', scheduleConfigSave);
  });

  $('wlmCheckEndpoint').addEventListener('click', () => {
    const instance = state.wlm;
    runInstrumentAction(instance, 'Connection check failed', checkWlmEndpoint);
  });
  document.querySelectorAll('[data-wlm-connection-mode]').forEach((button) => {
    button.addEventListener('click', () => selectWlmConnectionMode(button.dataset.wlmConnectionMode));
  });
  $('wlmRunSwitch').addEventListener('change', () => handleRunSwitchChange('wlm', 'wlmRunSwitch', startWlm, stopWlm));
  $('wlmAcquisitionName').addEventListener('input', () => {
    if (state.wlm?.id && state.activeInstanceId === state.wlm.id) {
      state.wlm.acquisitionName = $('wlmAcquisitionName').value;
    }
  });
  [
    'wlmResource'
  ].forEach((id) => {
    $(id).addEventListener('change', scheduleConfigSave);
    $(id).addEventListener('input', scheduleConfigSave);
  });

  $('opmRefreshResources').addEventListener('click', () => {
    runInstrumentAction(state.opm, 'Could not discover instruments', refreshOpmResources);
  });
  $('opmRetryDriver').addEventListener('click', retryOpmDriverDiscovery);
  $('opmCheckConnection').addEventListener('click', () => checkInstrumentConnection('opm'));
  $('opmDisplayUnit').addEventListener('change', () => {
    syncOpmDisplayFromRaw();
    syncLauncherStatus();
    scheduleConfigSave();
  });
  $('opmAutorange').addEventListener('change', () => {
    syncOpmControlState();
    scheduleConfigSave();
  });
  $('opmRunSwitch').addEventListener('change', () => handleRunSwitchChange('opm', 'opmRunSwitch', startOpm, stopOpm));
  $('opmManualRange').addEventListener('change', syncOpmTickSliders);
  [
    'opmResource',
    'opmWavelength',
    'opmManualRange'
  ].forEach((id) => {
    $(id).addEventListener('change', scheduleConfigSave);
    $(id).addEventListener('input', scheduleConfigSave);
  });
}

async function init() {
  wireUi();
  $('appVersion').textContent = await window.openUfc.appVersion();
  state.backendUrl = await window.openUfc.backendUrl();
  createCharts();
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', refreshChartTheme);
  connectInstrumentEvents();
  state.config = await api('/api/config');
  applyPlatformSettings(state.config.platform || {});
  await window.openUfc.setColorMode(state.colorMode);
  await loadInstruments();
  setView('home');
}

window.addEventListener('DOMContentLoaded', () => {
  window.addEventListener('unhandledrejection', (event) => {
    event.preventDefault();
    showError('Operation failed', event.reason);
  });
  window.addEventListener('error', (event) => {
    if (event.error) showError('Unexpected application error', event.error);
  });
  init().catch((error) => {
    showError('Could not initialize OpenUFC', error);
  }).finally(() => window.openUfc.ready());
});
