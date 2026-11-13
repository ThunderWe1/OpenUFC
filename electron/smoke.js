module.exports = async function runSmokeTests() {
  for (const [count, elapsed, expected] of [[0, 0, '--'], [1, 0, '--'], [1, -1, '--'],
      [undefined, 1, '--'], [1, NaN, '--'], [Infinity, 1, '--'], [0, 1, '0'], [1, 8, (0.125).toLocaleString()]]) {
    if (formatSampleRate(count, elapsed) !== expected) throw new Error('Invalid or fractional sample rate is formatted incorrectly');
  }
  const expectedRates = [1, 10, 100, 1000, 5000, 10000, 50000];
  const actualRates = [...document.querySelector('#sampleRate').options].map((option) => Number(option.value));
  if (JSON.stringify(actualRates) !== JSON.stringify(expectedRates)) throw new Error('Counter rate presets are incomplete');
  const segmentedPoints = ufcWaveformPoints({
    frequencyValues: [10, 11, 20, 21], frequencyStartIndex: 10,
    frequencyBreakIndices: [12], frequencyDisplayScale: 1
  }, 10);
  if (segmentedPoints.length !== 5 || segmentedPoints[2].y !== null ||
      segmentedPoints[2].x !== 1.2 || segmentedPoints[3].y !== 20) {
    throw new Error('Counter waveform connects readings across a restart');
  }
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const click = (selector) => {
    const el = document.querySelector(selector);
    if (!el) throw new Error('Missing ' + selector);
    el.click();
  };
   if (!document.querySelector('[data-view="home"]')) throw new Error('Missing launcher');
   if (!document.querySelector('[data-add-instrument-type="opm"]')) throw new Error('Missing OPM add-instrument option');
    if (!document.querySelector('[data-supported-instrument-type="opm"]')) throw new Error('Missing OPM supported-model entry');
    if (!document.querySelector('[data-add-instrument-type="wlm"]')) throw new Error('Missing WLM add-instrument option');
    if (!document.querySelector('[data-supported-instrument-type="wlm"]')) throw new Error('Missing WLM supported-model entry');
   click('#openAbout');
   const aboutDialog = document.querySelector('#aboutDialog');
   if (document.querySelector('#appVersion').textContent !== await window.openUfc.appVersion()) throw new Error('About dialog version does not match the app');
   await document.fonts.ready;
   if (!document.fonts.check('14px Utendo')) throw new Error('Bundled font did not load');
   for (const icon of aboutDialog.querySelectorAll('img')) {
     if (!icon.complete || !icon.naturalWidth) throw new Error('Bundled About icon did not load: ' + icon.src);
   }
   const counterInfo = aboutDialog.querySelector('[data-supported-instrument-type="ufc"]');
   if (!aboutDialog.open || !counterInfo || [...counterInfo.querySelectorAll('.about-model-number')].map((item) => item.textContent).join(',') !== '53220A,53230A') throw new Error('Counter support information is missing the supported models');
   click('#aboutDialog button[aria-label="Close dialog"]');
   await wait(400);
   if (aboutDialog.open) throw new Error('About dialog did not close');
   click('#openGlobalSettings');
   await wait(40);
   const globalSettingsDialog = document.querySelector('#globalSettingsDialog');
   if (!globalSettingsDialog?.open) throw new Error('Global settings did not open');
    const previousRequestConfigReset = requestConfigReset;
    let resetRequestCount = 0;
    requestConfigReset = async () => {
      resetRequestCount += 1;
      return { ok: true };
    };
    click('#openResetConfig');
    await wait(40);
    const resetConfigDialog = document.querySelector('#resetConfigDialog');
    const resetConfigSlider = document.querySelector('#resetConfigSlider');
    if (!resetConfigDialog?.open || !resetConfigSlider) throw new Error('Reset confirmation dialog or slider did not render');
    if (document.activeElement !== document.querySelector('#cancelResetConfig')) throw new Error('Reset confirmation did not default focus to Cancel');
    const resetFormBounds = resetConfigDialog.querySelector('.modal-form').getBoundingClientRect();
    const resetSliderBounds = resetConfigSlider.getBoundingClientRect();
    if (resetSliderBounds.width < 300 || resetSliderBounds.left < resetFormBounds.left || resetSliderBounds.right > resetFormBounds.right) throw new Error('Reset confirmation slider is clipped or misaligned');
    const resetSliderLabel = document.querySelector('#resetConfigSliderLabel');
    if (resetSliderLabel.scrollWidth > resetSliderLabel.clientWidth) throw new Error('Reset confirmation slider label is truncated');
    resetConfigSlider.value = '75';
    resetConfigSlider.dispatchEvent(new Event('input', { bubbles: true }));
    resetConfigSlider.dispatchEvent(new Event('change', { bubbles: true }));
    if (resetConfigSlider.value !== '0' || resetRequestCount !== 0) throw new Error('Partial reset slider movement did not safely snap back');
    resetConfigSlider.value = '100';
    resetConfigSlider.dispatchEvent(new Event('input', { bubbles: true }));
    resetConfigSlider.dispatchEvent(new Event('change', { bubbles: true }));
    await wait(40);
    if (resetRequestCount !== 1 || !state.resetConfigInProgress) throw new Error('Completed reset slider did not issue exactly one reset request');
    requestConfigReset = previousRequestConfigReset;
    resetResetConfigDialog();
    closeModal(resetConfigDialog);
    await wait(220);
    if (!globalSettingsDialog.open) throw new Error('Canceling reset did not return to Global Settings');
    click('#globalSettingsDialog [value="cancel"]');
   await wait(220);
   click('#openLibrary');
  await wait(80);
  if (!document.querySelector('[data-view="library"].active')) throw new Error('Library view did not activate');
  if (!document.querySelector('#libraryList')) throw new Error('Missing library list');
  const previousLibraryFile = state.library.selectedFile;
  const previousLibraryName = document.querySelector('#libraryDisplayName').value;
  state.library.selectedFile = '__smoke_library_record__.lmp';
  document.querySelector('#libraryDisplayName').value = 'Smoke Library Record';
  openDeleteLibraryDialog();
  await wait(40);
  const deleteLibraryDialog = document.querySelector('#deleteLibraryDialog');
  if (!deleteLibraryDialog?.open) throw new Error('Library delete confirmation did not open in-app');
  if (document.querySelector('#deleteLibraryRecordName').textContent !== 'Smoke Library Record') throw new Error('Library delete confirmation did not show the selected record');
  if (!document.querySelector('#confirmDeleteLibraryItem').classList.contains('danger')) throw new Error('Library delete confirmation is missing its destructive action style');
  if (document.activeElement !== document.querySelector('#cancelDeleteLibraryItem')) throw new Error('Library delete confirmation did not default focus to Cancel');
  click('#cancelDeleteLibraryItem');
  await wait(220);
  if (deleteLibraryDialog.open) throw new Error('Library delete confirmation did not close on Cancel');
  state.library.selectedFile = previousLibraryFile;
  document.querySelector('#libraryDisplayName').value = previousLibraryName;
  setView('home');
  await wait(80);
   const smokeUfc = state.instruments.find((item) => item.type === 'ufc');
   const smokeDmm = state.instruments.find((item) => item.type === 'dmm');
     if (!smokeUfc || !smokeDmm) throw new Error('Default UFC and DMM instruments did not render');
  const analysisApi = api;
  const analysisInstance = state.instances[smokeUfc.id];
  const analysisSettings = { ...analysisInstance.settings };
  let noiseRequests = 0;
  let waveformRequests = 0;
  let releaseWaveform;
  let releaseNoise;
  const noiseResult = { points: [{ x: 1, y: 0 }, { x: 2, y: 4 }], averages: 3, resolution_hz: 1, sample_count: 2048, segment_length: 1024 };
  const waveformResult = {
    file: 'smoke-waveform.lmp',
    sample_count: 2048,
    waveform: { unit: 'Hz', points: [{ x: 0, y: 1000000000 }, { x: 1, y: null }, { x: 2, y: 2000000 }] }
  };
  api = async (path) => {
    if (path.includes('/frequency-noise?')) { noiseRequests += 1; return noiseResult; }
    if (path.includes('/api/library/waveform?')) {
      waveformRequests += 1;
      return waveformResult;
    }
    if (path.endsWith('/settings')) return { settings: analysisInstance.settings };
    return analysisApi(path);
  };
  try {
    activateInstance(smokeUfc.id);
    setView('ufc');
    const previousRate = $('sampleRate').value;
    for (const rate of expectedRates) {
      $('sampleRate').value = String(rate);
      syncUfcTickSliders();
      if (readUfcSettings().sample_rate_hz !== rate) throw new Error('Counter rate does not reach saved settings');
    }
    $('sampleRate').value = previousRate;
    syncUfcTickSliders();
    const rateTicks = [...document.querySelectorAll('[data-slider-select="sampleRate"] .dmm-tick-option')]
      .map((button) => button.getBoundingClientRect()).sort((a, b) => a.top - b.top);
    if (rateTicks.some((rect, index) => index && rect.top < rateTicks[index - 1].bottom - 0.5)) {
      throw new Error('Counter rate tick targets overlap');
    }
    const largeBatchInstance = {
      id: 'large-batch-validation', frequencyValues: [-1], frequencyStartIndex: 0,
      frequencyBreakIndices: [], maxFrequencyPoints: 20000, settings: { sample_rate_hz: 50000 }
    };
    handleData({ frequency_hz: Array.from({ length: 50000 }, (_, i) => i),
      total_samples: 50001, elapsed_s: 1, segment_start: true }, largeBatchInstance);
    if (largeBatchInstance.frequencyValues.length !== 20000 ||
        largeBatchInstance.frequencyValues[0] !== 30000 || largeBatchInstance.frequencyStartIndex !== 30001) {
      throw new Error('Large counter batch did not preserve the waveform tail');
    }
    handleData({ frequency_hz: [50000, 50001, 50002], total_samples: 50004,
      elapsed_s: 2, segment_start: true }, largeBatchInstance);
    if (largeBatchInstance.frequencyBreakIndices.join(',') !== '50001' ||
        !ufcWaveformPoints(largeBatchInstance, 50000).some((point) => point.y === null)) {
      throw new Error('Large counter batch lost a restart boundary');
    }
    await wait(100);
    if (!$('divideOpticalFrequency').closest('#ufcAdevPanel') || !$('divideSqrt2').closest('#ufcAdevPanel') || !$('wavelength').closest('#ufcAdevPanel')) throw new Error('ADEV settings are outside their tab');
    if ($('wavelengthRow').getBoundingClientRect().top < $('adevChart').getBoundingClientRect().bottom) throw new Error('ADEV settings are not below the plot');
    analysisInstance.runPath = 'smoke-noise.lmp';
    click('#ufcFnTab');
    await refreshUfcNoise(analysisInstance);
    await wait(100);
    if (!$('ufcAdevPanel').hidden || $('ufcFnPanel').hidden || $('ufcFnTab').getAttribute('aria-selected') !== 'true') throw new Error('FN tab visibility is incorrect');
    if (analysisInstance.frequencyNoiseChart.width <= 0 || analysisInstance.frequencyNoiseChart.height <= 0) throw new Error('FN chart did not resize after revealing the tab');
    if ($('fnSegmentLength').getBoundingClientRect().top < $('frequencyNoiseChart').getBoundingClientRect().bottom) throw new Error('FN settings are not below the plot');
    for (const id of ['fnSegmentLength', 'fnWindow', 'fnOverlap', 'fnLogX', 'fnLogY']) {
      if ($(id).getBoundingClientRect().bottom > document.querySelector('.window-shell').getBoundingClientRect().bottom) throw new Error('FN control is clipped at minimum window size: ' + id);
    }
    if (analysisInstance.frequencyNoiseChart.data.datasets[0].data[0].y !== null) throw new Error('Logarithmic Y received a zero value');
    const beforeScaleChange = noiseRequests;
    click('#fnLogX');
    click('#fnLogY');
    if (analysisInstance.frequencyNoiseChart.options.scales.x.type !== 'linear' || analysisInstance.frequencyNoiseChart.options.scales.y.type !== 'linear') throw new Error('FN axis toggles did not change chart scales');
    if (analysisInstance.frequencyNoiseChart.data.datasets[0].data[0].y !== 0 || noiseRequests !== beforeScaleChange) throw new Error('Scale changes lost zeros or recalculated the spectrum');
    $('fnSegmentLength').value = '256';
    $('fnSegmentLength').dispatchEvent(new Event('change', { bubbles: true }));
    await refreshUfcNoise(analysisInstance);
    if (analysisInstance.settings.fn_segment_length !== 256 || noiseRequests !== beforeScaleChange + 1) throw new Error('FN parameters did not trigger recalculation');
    if (!document.querySelector('#ufcRecentWaveformTab') || !document.querySelector('#ufcFullWaveformTab')) throw new Error('Missing UFC waveform tabs');
    analysisInstance.runPath = 'smoke-waveform.lmp';
    const beforeWaveformRequests = waveformRequests;
    click('#ufcFullWaveformTab');
    await refreshFullWaveform(analysisInstance);
    if (waveformRequests !== beforeWaveformRequests + 1 || $('ufcFullWaveformTab').getAttribute('aria-selected') !== 'true') throw new Error('UFC Full waveform tab did not fetch its recording');
    const fullWaveformData = analysisInstance.frequencyChart.data.datasets[0].data;
    if (fullWaveformData[0].y !== 1000 || fullWaveformData[1].y !== null || fullWaveformData[2].y !== 2) throw new Error('UFC Full waveform did not apply frequency units or gaps');
    $('ufcFullWaveformTab').dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }));
    if (analysisInstance.waveformTab !== 'recent' || document.activeElement !== $('ufcRecentWaveformTab')) throw new Error('UFC waveform tabs cannot be switched by keyboard');
    // An old response must not repopulate a reset/new recording.
    api = (path) => path.includes('/api/library/waveform?')
      ? new Promise((resolve) => { releaseWaveform = resolve; })
      : Promise.resolve({});
    analysisInstance.runPath = 'smoke-waveform.lmp';
    selectWaveformTab(analysisInstance, 'full');
    const pendingWaveform = refreshFullWaveform(analysisInstance);
    resetUfcPlots();
    releaseWaveform(waveformResult);
    await pendingWaveform;
    if (analysisInstance.fullWaveformPoints.length) throw new Error('Stale waveform repopulated a reset recording');
    // An old response must not overwrite a reset/new recording.
    api = (path) => path.includes('/frequency-noise?') ? new Promise((resolve) => { releaseNoise = resolve; }) : Promise.resolve({});
    analysisInstance.runPath = 'smoke-noise.lmp';
    analysisInstance.fnCacheKey = null;
    const pendingNoise = refreshUfcNoise(analysisInstance);
    resetUfcPlots();
    releaseNoise(noiseResult);
    await pendingNoise;
    if (analysisInstance.fnPoints.length) throw new Error('Stale spectrum repopulated a reset recording');
    activateInstance(smokeDmm.id);
    activateInstance(smokeUfc.id);
    if ($('fnSegmentLength').value !== '256' || $('fnLogX').checked || $('fnLogY').checked || $('ufcFnPanel').hidden) throw new Error('FN settings were lost on instrument switch');
    $('ufcFnTab').dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }));
    if ($('ufcAdevPanel').hidden || document.activeElement !== $('ufcAdevTab')) throw new Error('Analysis tabs cannot be switched by keyboard');
  } finally {
    clearTimeout(analysisInstance.fnTimer);
    analysisInstance.fnTimer = null;
    analysisInstance.runPath = '';
    analysisInstance.settings = analysisSettings;
    api = analysisApi;
    applyUfcSettings(analysisSettings);
    setView('home');
  }
   const smokeConnectionBadge = document.querySelector('#connectionBadge');
   if (smokeConnectionBadge?.textContent !== 'OFFLINE' || !smokeConnectionBadge.classList.contains('offline')) throw new Error('Connection badge did not default to OFFLINE');
   if (statusKindToBadge('connected') !== 'READY') throw new Error('Confirmed device state did not map to READY');
   if (statusKindToBadge('running') !== 'BUSY' || statusKindToBadge('stopping') !== 'BUSY') throw new Error('Acquisition states did not map to BUSY');
   if (statusKindToBadge('connecting') !== 'OFFLINE' || statusKindToBadge('reconnecting') !== 'OFFLINE') throw new Error('Unavailable device states did not map to OFFLINE');
   const smokeWlmId = '__smoke_wlm__';
   const smokeWlmItem = {
     id: smokeWlmId,
     type: 'wlm',
     settings: {
       connection_mode: 'usb',
        resource: '10.199.199.1:23',
        ethernet_resource: ''
     }
   };
   state.instances[smokeWlmId] = createRuntime(smokeWlmItem);
   state.instruments = [...state.instruments, smokeWlmItem];
   const previousRefreshActiveInstanceOptions = refreshActiveInstanceOptions;
   refreshActiveInstanceOptions = () => {};
   renderLauncherCards();
   const smokeWlmCard = document.querySelector('[data-instance-id="' + smokeWlmId + '"][data-instrument-type="wlm"]');
   if (!smokeWlmCard) throw new Error('WLM launcher card did not render');
   if (!smokeWlmCard.querySelector('img[src$="/waves.svg"]')) throw new Error('WLM launcher icon did not render');
  const previousApiBeforeVisaCountProbe = api;
  api = async (path) => {
    if (path.includes('/' + smokeUfc.id + '/') && path.endsWith('/resources')) {
      return { resources: ['SMOKE::UFC::ONE', 'SMOKE::UFC::UNKNOWN', 'SMOKE::UFC::DISCONNECTED'], valid_count: 1, error: null };
    }
    if (path.includes('/' + smokeUfc.id + '/') && path.endsWith('/check')) {
      return { connected: true, identity: 'KEYSIGHT,53220A,SMOKE,0', resource: 'SMOKE::UFC::ONE' };
    }
    if (path.includes('/' + smokeDmm.id + '/') && path.endsWith('/resources')) {
      return { resources: ['SMOKE::DMM::ONE', 'SMOKE::DMM::UNKNOWN', 'SMOKE::DMM::DISCONNECTED'], valid_count: 1, error: null };
    }
    if (path.includes('/' + smokeDmm.id + '/') && path.endsWith('/check')) {
      return { connected: true, identity: 'KEYSIGHT,34461A,SMOKE,0', resource: 'SMOKE::DMM::ONE' };
    }
    throw new Error('Unexpected VISA count probe API call: ' + path);
  };
  click('[data-instance-id="' + smokeUfc.id + '"] [data-open-instance]');
  await wait(900);
  if (!document.querySelector('[data-view="ufc"].active')) throw new Error('Universal Frequency Counter view did not activate');
  await refreshResources();
  const smokeUfcCountBadge = document.querySelector('#ufcResourceCount');
  const smokeUfcResourceLabel = document.querySelector('label[for="resource"]');
  if (smokeUfcCountBadge?.textContent !== '1' || smokeUfcCountBadge.getAttribute('aria-label') !== '1 discovered instrument') throw new Error('UFC count included unidentified or disconnected resources');
  if (!smokeUfcCountBadge.closest('.resource-label-row')?.contains(smokeUfcResourceLabel)) throw new Error('UFC count badge is not beside the VISA resource title');
  const smokeUfcCountBounds = smokeUfcCountBadge.getBoundingClientRect();
  const smokeUfcLabelBounds = smokeUfcResourceLabel.getBoundingClientRect();
  if (smokeUfcCountBounds.left <= smokeUfcLabelBounds.right || smokeUfcCountBounds.left - smokeUfcLabelBounds.right > 16 || Math.abs((smokeUfcCountBounds.top + smokeUfcCountBounds.bottom) / 2 - (smokeUfcLabelBounds.top + smokeUfcLabelBounds.bottom) / 2) > 3) throw new Error('UFC count badge is misaligned with the VISA resource title');
   if (document.querySelector('#statusText').textContent !== 'Offline') throw new Error('UFC VISA discovery incorrectly reported a connected device');
  const smokeUfcRefresh = document.querySelector('#refreshResources');
  const smokeUfcCheck = document.querySelector('#checkConnection');
  if (smokeUfcRefresh.textContent.trim() || !smokeUfcRefresh.querySelector('svg')) throw new Error('UFC refresh must be an icon-only SVG button');
  if (!smokeUfcRefresh.getAttribute('aria-label') || !smokeUfcRefresh.title) throw new Error('UFC refresh button is missing accessible text');
  if (smokeUfcCheck.textContent.trim() || !smokeUfcCheck.querySelector('svg')) throw new Error('UFC connection check must be an icon-only SVG button');
  await checkInstrumentConnection('ufc');
  if (document.querySelector('#statusText').textContent !== 'Connected: KEYSIGHT,53220A,SMOKE,0' || document.querySelector('#connectionBadge').textContent !== 'READY') throw new Error('UFC connection check did not update status to READY');
  setView('home');
  await wait(900);
  click('[data-instance-id="' + smokeDmm.id + '"] [data-open-instance]');
   await wait(900);
    if (!document.querySelector('[data-view="dmm"].active')) throw new Error('Digital Multimeter view did not activate');
    if (!document.querySelector('#dmmTrendChart')) throw new Error('Missing DMM trend chart');
     if (!document.querySelector('#dmmRecentWaveformTab') || !document.querySelector('#dmmFullWaveformTab')) throw new Error('Missing DMM waveform tabs');
     state.dmm.fullWaveformPoints = [{ x: 0, y: 1.25 }];
     selectWaveformTab(state.dmm, 'full');
     if (state.dmm.trendChart.data.datasets[0].data[0].y !== 1.25) throw new Error('DMM Full waveform did not retain display units');
     selectWaveformTab(state.dmm, 'recent');
    await refreshDmmResources();
    const smokeDmmCountBadge = document.querySelector('#dmmResourceCount');
    if (smokeDmmCountBadge?.textContent !== '1' || smokeDmmCountBadge.getAttribute('aria-label') !== '1 discovered instrument') throw new Error('DMM count included unidentified or disconnected resources');
    if (!smokeDmmCountBadge.closest('.resource-label-row')?.querySelector('label[for="dmmResource"]')) throw new Error('DMM count badge is not beside the VISA resource title');
     if (document.querySelector('#dmmStatusText').textContent !== 'Offline') throw new Error('DMM VISA discovery incorrectly reported a connected device');
    const smokeDmmRefresh = document.querySelector('#dmmRefreshResources');
    const smokeDmmCheck = document.querySelector('#dmmCheckConnection');
    if (smokeDmmRefresh.textContent.trim() || !smokeDmmRefresh.querySelector('svg')) throw new Error('DMM refresh must be an icon-only SVG button');
    if (smokeDmmCheck.textContent.trim() || !smokeDmmCheck.querySelector('svg')) throw new Error('DMM connection check must be an icon-only SVG button');
    await checkInstrumentConnection('dmm');
    if (document.querySelector('#dmmStatusText').textContent !== 'Connected: KEYSIGHT,34461A,SMOKE,0' || document.querySelector('#connectionBadge').textContent !== 'READY') throw new Error('DMM connection check did not update status to READY');
    api = previousApiBeforeVisaCountProbe;
    setView('home');
    await wait(900);
    const previousApiBeforeWlmProbe = api;
    const wlmProbeCalls = [];
    api = async (path, options = {}) => {
      wlmProbeCalls.push({ path, method: options.method || 'GET', body: options.body || '' });
      if (path.endsWith('/options')) {
        return {
          type: 'wlm',
          connection_modes: ['usb', 'ethernet'],
          usb_resource: '10.199.199.1:23',
          defaults: smokeWlmItem.settings
        };
      }
      if (path.endsWith('/settings')) {
        const nextSettings = options.body ? JSON.parse(options.body) : {};
        return { settings: { ...smokeWlmItem.settings, ...nextSettings } };
      }
      if (path.endsWith('/check')) {
        return {
          connected: true,
          resource: '10.199.199.1:23',
          identity: 'Bristol Instruments,771B-NIR,SMOKE,0'
        };
      }
      throw new Error('Unexpected WLM probe API call: ' + path);
    };
    refreshActiveInstanceOptions = previousRefreshActiveInstanceOptions;
    click('[data-instance-id="' + smokeWlmId + '"] [data-open-instance]');
    await wait(900);
    if (!document.querySelector('[data-view="wlm"].active')) throw new Error('Wavelength Meter view did not activate');
    if (state.activeInstanceId !== smokeWlmId || state.wlm.id !== smokeWlmId) throw new Error('WLM runtime did not activate');
   [
     '#wlmResource',
     '#wlmEndpointLabel',
     '#wlmEthernetResourceRow',
     '#wlmCheckEndpoint',
     '#wlmAcquisitionName',
     '#wlmRunSwitch',
     '#wlmStatusText',
     '#wlmTrendChart',
     '#wlmAdevChart'
   ].forEach((selector) => {
      if (!document.querySelector(selector)) throw new Error('Missing ' + selector);
    });
     if (!document.querySelector('#wlmRecentWaveformTab') || !document.querySelector('#wlmFullWaveformTab')) throw new Error('Missing WLM waveform tabs');
     state.wlm.fullWaveformPoints = [{ x: 0, y: 852.1 }];
     selectWaveformTab(state.wlm, 'full');
     if (state.wlm.trendChart.data.datasets[0].data[0].y !== 852.1) throw new Error('WLM Full waveform did not retain wavelength units');
     selectWaveformTab(state.wlm, 'recent');
    if (wlmProbeCalls.filter((call) => call.path.endsWith('/options')).length !== 1) throw new Error('WLM page entry did not load options exactly once');
    if (wlmProbeCalls.some((call) => call.path.endsWith('/check'))) throw new Error('WLM page entry probed the hardware without using the check button');
    const smokeWlmUsbMode = document.querySelector('#wlmUsbMode');
     const smokeWlmEthernetMode = document.querySelector('#wlmEthernetMode');
     const smokeWlmResource = document.querySelector('#wlmResource');
     const smokeWlmEndpointLabel = document.querySelector('#wlmEndpointLabel');
     const smokeWlmResourceRow = document.querySelector('#wlmEthernetResourceRow');
     const smokeWlmCheck = document.querySelector('#wlmCheckEndpoint');
    if (!smokeWlmUsbMode || !smokeWlmEthernetMode) throw new Error('Missing WLM USB/Ethernet mode controls');
     if (smokeWlmUsbMode.getAttribute('aria-pressed') !== 'true') throw new Error('WLM USB mode was not selected from saved settings');
     if (smokeWlmResource.value !== '10.199.199.1:23' || !smokeWlmResource.readOnly) throw new Error('WLM USB mode must use the fixed read-only endpoint');
     if (!smokeWlmEndpointLabel.classList.contains('hidden') || !smokeWlmResourceRow.classList.contains('hidden')) throw new Error('WLM USB mode exposed the IP editor');
     if (smokeWlmCheck.textContent.trim() || !smokeWlmCheck.querySelector('svg')) throw new Error('WLM connection check must be an icon-only SVG button');
    if (!smokeWlmCheck.getAttribute('aria-label') || !smokeWlmCheck.title) throw new Error('WLM connection check button is missing accessible text');
     smokeWlmEthernetMode.click();
     if (smokeWlmResource.readOnly || smokeWlmResource.value !== '') throw new Error('WLM Ethernet mode did not expose an empty editable endpoint');
     if (smokeWlmEndpointLabel.classList.contains('hidden') || smokeWlmResourceRow.classList.contains('hidden')) throw new Error('WLM Ethernet mode did not show the IP editor');
    await wait(420);
    if (wlmProbeCalls.some((call) => call.path.endsWith('/settings'))) throw new Error('WLM tried to persist an incomplete Ethernet endpoint');
    smokeWlmResource.value = 'changed-wlm.local:23';
    smokeWlmResource.dispatchEvent(new Event('input', { bubbles: true }));
     smokeWlmUsbMode.click();
     if (smokeWlmResource.value !== '10.199.199.1:23' || !smokeWlmResource.readOnly) throw new Error('WLM USB mode did not restore its fixed endpoint');
     if (!smokeWlmResourceRow.classList.contains('hidden')) throw new Error('WLM USB mode did not hide the IP editor after switching');
    smokeWlmEthernetMode.click();
    if (smokeWlmResource.value !== 'changed-wlm.local:23') throw new Error('WLM Ethernet endpoint was not retained across mode switches');
    smokeWlmUsbMode.click();
     smokeWlmCheck.click();
     await wait(80);
     if (wlmProbeCalls.filter((call) => call.path.endsWith('/check')).length !== 1) throw new Error('WLM check button did not perform exactly one connection check');
     if (document.querySelector('#connectionBadge').textContent !== 'READY' || !document.querySelector('#connectionBadge').classList.contains('ready')) throw new Error('Successful WLM identity check did not set READY');
    if (document.querySelector('#wlmChannel')) throw new Error('WLM channel must not be exposed');
    if (document.querySelector('#wlmTimeout')) throw new Error('WLM timeout must not be exposed');
    if (document.querySelector('#wlmDisplayUnit')) throw new Error('WLM display unit must not be exposed');
   if (document.querySelector('[data-slider-select="wlmPollingRate"]') || document.querySelector('#wlmPollingRate')) throw new Error('WLM polling control should not be rendered');
   if (formatWavelengthNm(852.1) !== '852.100000') throw new Error('WLM wavelength values must use six decimals');
   if (wavelengthTickStyle().callback(852.1) !== '852.100000') throw new Error('WLM trend ticks must use six decimals');
   if (wavelengthTooltipLabel({ dataset: { label: 'Wavelength' }, parsed: { y: 852.1 } }) !== 'Wavelength: 852.100000 nm') throw new Error('WLM trend tooltips must use six-decimal nm');
   if (state.wlm.trendChart.options.plugins.title.text !== 'Wavelength Trend') throw new Error('Unexpected WLM trend chart title');
   if (state.wlm.adevChart.options.plugins.title.text !== 'ADEV (nm)') throw new Error('Unexpected WLM ADEV chart title');
    state.wlm.running = true;
    syncWlmControlState();
    if (!document.querySelector('#wlmResource').disabled) throw new Error('WLM endpoint must lock while running');
    if (!smokeWlmUsbMode.disabled || !smokeWlmEthernetMode.disabled || !smokeWlmCheck.disabled) throw new Error('WLM mode and check controls must lock while running');
   handleWlmSample({
     elapsed_s: 1,
     wavelength_nm: 852.1,
     stats: { latest: 852.1, minimum: 852.1, maximum: 852.1, average: 852.1, count: 1 }
   }, state.wlm);
   const smokeWlmLiveValue = document.querySelector('[data-instance-id="' + smokeWlmId + '"] .launcher-live-value');
   if (smokeWlmLiveValue?.textContent !== '852.100000 nm') throw new Error('WLM launcher live value did not render in nm');
   const smokeWlmMetric = document.querySelector('#wlmValueMetric');
   if (smokeWlmMetric.scrollWidth > smokeWlmMetric.clientWidth) throw new Error('WLM six-decimal metric is truncated at 1180px');
   state.wlm.running = false;
   syncWlmControlState();

   const smokeWlmSecondId = '__smoke_wlm_second__';
   const smokeWlmSecondItem = {
     id: smokeWlmSecondId,
     type: 'wlm',
      settings: {
        connection_mode: 'ethernet',
         resource: 'second-wlm.local:23',
         ethernet_resource: 'second-wlm.local:23'
     }
   };
   state.instances[smokeWlmSecondId] = createRuntime(smokeWlmSecondItem);
   state.instruments = [...state.instruments, smokeWlmSecondItem];
   document.querySelector('#wlmAcquisitionName').value = 'First WLM run';
   document.querySelector('#wlmAcquisitionName').dispatchEvent(new Event('input', { bubbles: true }));
   activateInstance(smokeWlmSecondId);
   if (document.querySelector('#wlmAcquisitionName').value !== '') throw new Error('WLM acquisition name leaked to a second instance');
   document.querySelector('#wlmAcquisitionName').value = 'Second WLM run';
   document.querySelector('#wlmAcquisitionName').dispatchEvent(new Event('input', { bubbles: true }));
   activateInstance(smokeWlmId);
   if (document.querySelector('#wlmAcquisitionName').value !== 'First WLM run') throw new Error('WLM acquisition name was not restored per instance');

   delete state.instances[smokeWlmSecondId];
   state.instruments = state.instruments.filter((item) => item.id !== smokeWlmSecondId);
    activateInstance(smokeWlmId);
    refreshActiveInstanceOptions = previousRefreshActiveInstanceOptions;
    api = previousApiBeforeWlmProbe;

  const smokeOpmId = '__smoke_opm__';
  const smokeOpmItem = {
    id: smokeOpmId,
    type: 'opm',
    settings: {
      resource: '',
      wavelength_nm: 852,
      display_unit: 'mW',
      autorange: true,
       manual_range_w: 0.01,
       channel: 1
     }
   };
  state.instances[smokeOpmId] = createRuntime(smokeOpmItem);
  state.instruments = [...state.instruments, smokeOpmItem];
  renderLauncherCards();
  const smokeOpmCard = document.querySelector('[data-instance-id="' + smokeOpmId + '"][data-instrument-type="opm"]');
  if (!smokeOpmCard) throw new Error('OPM launcher card did not render');
  if (!smokeOpmCard.querySelector('img[src$="/sun.svg"]')) throw new Error('OPM launcher icon did not render');
  if (!document.querySelector('#renameInstrumentDialog')) throw new Error('Missing instrument rename dialog');
  const viewBeforeRename = state.currentView;
  const smokeOpmOpen = smokeOpmCard.querySelector('[data-open-instance="' + smokeOpmId + '"]');
  smokeOpmOpen.dispatchEvent(new PointerEvent('pointerdown', { button: 0, pointerId: 1, isPrimary: true, clientX: 10, clientY: 10, bubbles: true }));
  await wait(700);
  smokeOpmOpen.dispatchEvent(new PointerEvent('pointerup', { button: 0, pointerId: 1, isPrimary: true, clientX: 10, clientY: 10, bubbles: true }));
  smokeOpmOpen.click();
  const actionOpmCard = document.querySelector('[data-instance-id="' + smokeOpmId + '"][data-instrument-type="opm"]');
  if (!actionOpmCard.classList.contains('launcher-actions-open')) throw new Error('Long press did not reveal instrument actions');
  if (document.querySelector('#renameInstrumentDialog').open) throw new Error('Long press opened rename before its action was selected');
  if (state.currentView !== viewBeforeRename) throw new Error('Long press unexpectedly opened the instrument view');
  const renameAction = actionOpmCard.querySelector('[data-rename-instance="' + smokeOpmId + '"]');
  const deleteAction = actionOpmCard.querySelector('[data-delete-instance="' + smokeOpmId + '"]');
  if (!renameAction?.querySelector('img[src$="/pencil.svg"]')) throw new Error('Rename action does not use the pencil icon');
  if (!deleteAction?.querySelector('img[src$="/trash-2.svg"]')) throw new Error('Delete action does not use the trash icon');
  if (renameAction.textContent.trim() || deleteAction.textContent.trim()) throw new Error('Launcher actions must not use ASCII text as icons');
  renameAction.click();
  await wait(40);
  if (!document.querySelector('#renameInstrumentDialog').open) throw new Error('Rename action did not open the instrument rename dialog');
  if (document.querySelector('#renameInstrumentName').placeholder !== 'OPTICAL POWER METER') throw new Error('Rename dialog did not identify the selected instrument');
  if (document.activeElement !== document.querySelector('#renameInstrumentName')) throw new Error('Rename dialog did not focus its name input');
  document.querySelector('#renameInstrumentDialog').close();
  activateInstance(smokeOpmId);
  setView('opm');
  await wait(120);
  if (!document.querySelector('[data-view="opm"].active')) throw new Error('Optical Power Meter view did not activate');
  if (state.activeInstanceId !== smokeOpmId || state.opm.id !== smokeOpmId) throw new Error('OPM runtime did not activate');
  [
    '#opmResource',
    '#opmResourceCount',
    '#opmWavelength',
     '#opmDisplayUnit',
     '#opmAutorange',
     '#opmManualRange',
     '#opmRunSwitch',
     '#opmTrendChart',
     '#opmAdevChart',
     '#opmDriverOverlay',
     '#opmDriverErrorMessage',
     '#opmRetryDriver',
     '#opmDashboard'
   ].forEach((selector) => {
     if (!document.querySelector(selector)) throw new Error('Missing ' + selector);
   });
   if (!document.querySelector('#opmRecentWaveformTab') || !document.querySelector('#opmFullWaveformTab')) throw new Error('Missing OPM waveform tabs');
   $('opmDisplayUnit').value = 'mW';
   state.opm.fullWaveformPoints = [{ x: 0, y: 0.001 }];
   selectWaveformTab(state.opm, 'full');
   if (state.opm.trendChart.data.datasets[0].data[0].y !== 1) throw new Error('OPM Full waveform did not apply mW conversion');
   selectWaveformTab(state.opm, 'recent');
  const previousApiBeforeOpmCountProbe = api;
  const smokeOpmAvailablePayload = {
    resources: ['USB0::SMOKE::OPM::ONE', 'USB0::SMOKE::OPM::UNKNOWN', 'USB0::SMOKE::OPM::DISCONNECTED'],
    resource_details: [
      { resource: 'USB0::SMOKE::OPM::ONE', manufacturer: 'Thorlabs', model: 'PM100D', serial: 'SMOKE1', available: true },
      { resource: 'USB0::SMOKE::OPM::UNKNOWN', manufacturer: 'Thorlabs', model: '', available: true },
      { resource: 'USB0::SMOKE::OPM::DISCONNECTED', manufacturer: 'Thorlabs', model: 'PM400', serial: 'SMOKE2', available: false }
    ],
    valid_count: 1,
    error: null,
    driver_available: true
  };
  api = async (path) => {
    if (path.includes('/' + smokeOpmId + '/') && path.endsWith('/resources')) {
      return smokeOpmAvailablePayload;
    }
    throw new Error('Unexpected OPM count probe API call: ' + path);
  };
  await refreshOpmResources();
  const smokeOpmOverlay = document.querySelector('#opmDriverOverlay');
  const smokeOpmDashboard = document.querySelector('#opmDashboard');
  if (!smokeOpmOverlay.classList.contains('hidden') || smokeOpmDashboard.hasAttribute('inert')) throw new Error('Available TLPMX driver incorrectly disabled the OPM page');
  const smokeOpmCountBadge = document.querySelector('#opmResourceCount');
  const smokeOpmResourceLabel = document.querySelector('label[for="opmResource"]');
  if (smokeOpmCountBadge?.textContent !== '1' || smokeOpmCountBadge.getAttribute('aria-label') !== '1 discovered instrument') throw new Error('OPM count included unidentified or disconnected resources');
  if (!document.querySelector('[data-view="opm"]').textContent.includes('Detected 1 optical power meter resource(s)')) throw new Error('OPM discovery status disagrees with the valid count');
  if (!smokeOpmCountBadge.closest('.resource-label-row')?.contains(smokeOpmResourceLabel)) throw new Error('OPM count badge is not beside the TLPMX resource title');
  const smokeOpmCountBounds = smokeOpmCountBadge.getBoundingClientRect();
  const smokeOpmLabelBounds = smokeOpmResourceLabel.getBoundingClientRect();
  if (smokeOpmCountBounds.left <= smokeOpmLabelBounds.right || smokeOpmCountBounds.left - smokeOpmLabelBounds.right > 16 || Math.abs((smokeOpmCountBounds.top + smokeOpmCountBounds.bottom) / 2 - (smokeOpmLabelBounds.top + smokeOpmLabelBounds.bottom) / 2) > 3) throw new Error('OPM count badge is misaligned with the TLPMX resource title');
   if (document.querySelector('#opmChannel')) throw new Error('Fixed channel 1 must not be exposed as an OPM control');
  if (document.querySelectorAll('[data-slider-select="opmManualRange"] [data-tick-value]').length !== 9) throw new Error('OPM range slider did not render all presets');
  if (document.querySelector('[data-slider-select="opmPollingRate"]') || document.querySelector('#opmPollingRate')) throw new Error('OPM polling control should not be rendered');
  if (powerValueForDisplay(1e-3, 'mW') !== 1) throw new Error('1e-3 W did not convert to 1 mW');
  if (Math.abs(powerValueForDisplay(1e-3, 'dBm')) > 1e-12) throw new Error('1e-3 W did not convert to 0 dBm');
  if (powerValueForDisplay(0, 'dBm') !== null || powerValueForDisplay(-1, 'dBm') !== null) throw new Error('Non-positive dBm conversion should be unavailable');
   if (formatPowerForDisplay(0, 'dBm') !== 'N/A') throw new Error('Unavailable dBm value did not format as N/A');
  api = async (path) => {
    if (path.includes('/' + smokeOpmId + '/') && path.endsWith('/resources')) {
      return {
        resources: [],
        resource_details: [],
        driver_available: false,
        error_code: 'tlpmx_driver_unavailable',
        error: 'Thorlabs TLPMX driver is unavailable. Attempted: C:\\Program Files\\Thorlabs\\TLPMX_64.dll: Could not find module'
      };
    }
    throw new Error('Unexpected OPM missing-driver probe API call: ' + path);
  };
  await refreshOpmResources();
  if (smokeOpmOverlay.classList.contains('hidden') || smokeOpmOverlay.getAttribute('aria-hidden') !== 'false') throw new Error('Missing TLPMX driver did not show the OPM page overlay');
  if (!smokeOpmDashboard.hasAttribute('inert') || smokeOpmDashboard.getAttribute('aria-hidden') !== 'true') throw new Error('Missing TLPMX driver did not disable the OPM dashboard');
  if (!document.querySelector('#opmResource').disabled || !document.querySelector('#opmRunSwitch').disabled) throw new Error('Missing TLPMX driver left OPM controls enabled');
  const smokeOpmDriverMessage = document.querySelector('#opmDriverErrorMessage').textContent;
  if (smokeOpmDriverMessage !== OPM_DRIVER_UNAVAILABLE_STATUS || /Attempted:|\.dll|Could not find module/.test(smokeOpmDriverMessage)) throw new Error('OPM driver overlay exposed raw loader diagnostics');
  if (getComputedStyle(smokeOpmOverlay).backdropFilter === 'none') throw new Error('OPM driver overlay did not apply a backdrop blur');
  const smokeWindowBounds = document.querySelector('.window-shell').getBoundingClientRect();
  const smokeOverlayBounds = smokeOpmOverlay.getBoundingClientRect();
  if (Math.abs(smokeOverlayBounds.left - smokeWindowBounds.left) > 1 || Math.abs(smokeOverlayBounds.top - smokeWindowBounds.top) > 1 || Math.abs(smokeOverlayBounds.width - smokeWindowBounds.width) > 2 || Math.abs(smokeOverlayBounds.height - smokeWindowBounds.height) > 2) throw new Error('OPM driver overlay did not cover the full instrument window');
  api = async (path) => {
    if (path.includes('/' + smokeOpmId + '/') && path.endsWith('/resources')) return smokeOpmAvailablePayload;
    throw new Error('Unexpected OPM driver-recovery probe API call: ' + path);
  };
  await refreshOpmResources();
  if (!smokeOpmOverlay.classList.contains('hidden') || smokeOpmDashboard.hasAttribute('inert') || document.querySelector('#opmResource').disabled) throw new Error('OPM page did not recover after TLPMX became available');
  api = previousApiBeforeOpmCountProbe;
  const raceApi = api;
  const raceRefresh = refreshActiveInstanceOptions;
  refreshActiveInstanceOptions = async () => {};
  try {
    for (const [kind, startFn, stopFn, switchId, refresh] of [
      ['ufc', startAcquisition, stopAcquisition, 'runSwitch', refreshResources],
      ['dmm', startDmm, stopDmm, 'dmmRunSwitch', refreshDmmResources],
      ['opm', startOpm, stopOpm, 'opmRunSwitch', refreshOpmResources],
      ['wlm', startWlm, stopWlm, 'wlmRunSwitch']
    ]) {
      const first = createRuntime({ id: '__race_first_' + kind, type: kind, settings: { resource: 'USB0::FIRST::INSTR', connection_mode: 'ethernet', ethernet_resource: 'first.local:23' } });
      const second = createRuntime({ id: '__race_second_' + kind, type: kind, settings: { resource: 'USB0::SECOND::INSTR', connection_mode: 'ethernet', ethernet_resource: 'second.local:23' } });
      state.instances[first.id] = first;
      state.instances[second.id] = second;
      state.instruments.push(first, second);
      const metricId = kind === 'ufc' ? 'sampleRateMetric' : kind + 'SampleRateMetric';
      const sampleHandler = { ufc: handleData, dmm: handleDmmSample, wlm: handleWlmSample, opm: handleOpmSample }[kind];
      const sample = (count, elapsed) => ({
        total_samples: count, elapsed_s: elapsed, frequency_hz: [1, 2], value: 1, wavelength_nm: 852, power_w: 0.001,
        stats: { count, latest: 1, minimum: 1, maximum: 1, average: 1 }
      });
      first.maxPoints = first.maxFrequencyPoints = 1;
      activateInstance(first.id);
      const metric = document.getElementById(metricId);
      if (metric.textContent !== '--' || metric.parentElement.querySelector('span').textContent !== 'Sample rate' ||
          metric.parentElement.querySelector('em').textContent !== 'Sa/s') throw new Error(kind + ' sample rate indicator is missing');
      sampleHandler(sample(250000, 10), first);
      if (metric.textContent !== (25000).toLocaleString()) throw new Error(kind + ' rate does not use the total count and elapsed time');
      if (metric.scrollWidth > metric.clientWidth) throw new Error(kind + ' sample rate is clipped at minimum window width');
      sampleHandler(sample(9, 18), second);
      if (metric.textContent !== first.sampleRateMetric) throw new Error(kind + ' background samples changed the active rate');
      activateInstance(second.id);
      if (metric.textContent !== (0.5).toLocaleString()) throw new Error(kind + ' rate was not restored on switching instruments');
      activateInstance(first.id);
      if (metric.textContent !== (25000).toLocaleString()) throw new Error(kind + ' rate was lost on switching back');
      sampleHandler(sample(500000, 40), first);
      if (metric.textContent !== (12500).toLocaleString()) throw new Error(kind + ' rate is not the cumulative average');
      if (document.querySelector('[data-view="' + kind + '"] .status-block').children.length !== 1) throw new Error(kind + ' sidebar still shows extra acquisition details');
      if (kind === 'opm') {
        first.settings.display_unit = 'dBm';
        syncOpmDisplayFromRaw(first);
        if (metric.textContent !== (12500).toLocaleString()) throw new Error('Changing power units changed the sample rate');
      }
      const viewSnapshot = () => JSON.stringify({
        text: document.querySelector('[data-view="' + kind + '"]').textContent,
        controls: [...document.querySelectorAll('[data-view="' + kind + '"] input, [data-view="' + kind + '"] select, [data-view="' + kind + '"] button')]
          .map((el) => [el.id, el.value, el.checked, el.disabled])
      });
      for (const start of [true, false]) {
        for (const fails of [false, true]) {
          first.running = !start;
          second.running = !start;
          first.pendingAction = second.pendingAction = null;
          activateInstance(first.id);
          document.getElementById(switchId).checked = start;
          const calls = [];
          let resolve, reject;
          const gate = new Promise((yes, no) => { resolve = yes; reject = no; });
          api = (path, options) => {
            calls.push({ path, body: JSON.parse(options.body) });
            return calls.length === 1 ? gate : Promise.resolve({ ok: true });
          };
          const pending = handleRunSwitchChange(kind, switchId, startFn, stopFn);
          const toggle = document.getElementById(switchId);
          if (toggle.checked !== !start || !toggle.disabled || !toggle.nextElementSibling.classList.contains('pending') || toggle.getAttribute('aria-busy') !== 'true') throw new Error(kind + ' toggle moved or did not lock while awaiting acquisition');
          const spinner = getComputedStyle(toggle.nextElementSibling.querySelector('.label-play'));
          if (spinner.clipPath !== 'none' || spinner.animationName !== 'acquisition-wait') throw new Error(kind + ' waiting spinner is missing');
          toggle.click();
          if (calls.length !== 1) throw new Error(kind + ' accepted repeated input during a pending request');
          if (start && (first.sampleRateMetric !== '--' || metric.textContent !== '--')) throw new Error(kind + ' new acquisition retained its previous sample rate');
          activateInstance(second.id);
          activateInstance(first.id);
          if (toggle.checked !== !start || !toggle.disabled || !toggle.nextElementSibling.classList.contains('pending')) throw new Error(kind + ' lost its waiting state on page switch');
          activateInstance(second.id);
          const before = viewSnapshot();
          const statusBefore = second.statusText;
          if (fails) reject(new Error('request failed'));
          else resolve({ ok: true });
          await pending;
          const label = kind + ' ' + (start ? 'start' : 'stop') + (fails ? ' failure' : '');
          if (calls.some((call) => !call.path.includes('/' + first.id + '/'))) throw new Error(label + ' targeted another instrument');
          if (start && !fails) {
            const expected = kind === 'wlm' ? 'first.local:23' : 'USB0::FIRST::INSTR';
            if (calls.length !== 2 || calls[1].body.resource !== expected || first.running) throw new Error(label + ' lost its configuration or confirmed running before acquisition');
          } else if (calls.length !== 1 || first.running !== !start || (fails ? first.statusSeverity !== 'warning' || !errorQueue.some(item => item.key === first.id + '\nrequest failed') : first.statusText !== 'Stop requested')) {
            throw new Error(label + ' did not update the original instrument');
          }
          if (second.running !== !start || second.statusText !== statusBefore || viewSnapshot() !== before) throw new Error(label + ' changed the newly selected instrument');
          if (!fails) {
            if (!first.pendingAction) throw new Error(label + ' cleared its waiting state on HTTP acknowledgement');
            if (start) {
              handleInstrumentEvent({ instrument_id: first.id, event: 'status', data: { kind: 'connected', text: 'Connected: SMOKE', badge: 'READY' } });
              if (first.running || !first.pendingAction) throw new Error(label + ' treated connection as acquisition start');
              handleInstrumentEvent({ instrument_id: first.id, event: 'status', data: { kind: 'running', text: kind === 'ufc' ? 'Acquisition running' : 'Acquisition started', badge: 'BUSY' } });
            } else {
              handleInstrumentEvent({ instrument_id: first.id, event: kind === 'ufc' ? 'data' : 'sample', data: sample(500001, 41) });
              handleInstrumentEvent({ instrument_id: first.id, event: 'status', data: { kind: 'running', text: 'Final ADEV update from full file', badge: 'BUSY' } });
              if (!first.running || !first.pendingAction) throw new Error(label + ' unlocked while draining/finalizing');
              handleInstrumentEvent({ instrument_id: first.id, event: 'done', data: { text: 'Stopped cleanly' } });
            }
            if (first.pendingAction || first.running !== start) throw new Error(label + ' did not follow the backend confirmation');
            if (viewSnapshot() !== before) throw new Error(label + ' confirmation changed a different instrument');
          }
          activateInstance(first.id);
          if (toggle.checked !== first.running || toggle.disabled || toggle.nextElementSibling.classList.contains('pending')) throw new Error(label + ' did not restore the confirmed toggle state');
        }
      }
      for (const start of [true, false]) {
        for (const lateFailure of [false, true]) {
          first.running = !start;
          activateInstance(first.id);
          document.getElementById(switchId).checked = start;
          let resolve, reject;
          const gate = new Promise((yes, no) => { resolve = yes; reject = no; });
          api = (path) => path.endsWith('/settings') ? Promise.resolve({}) : gate;
          const pending = handleRunSwitchChange(kind, switchId, startFn, stopFn);
          await wait(0);
          handleInstrumentEvent({ instrument_id: first.id, event: start ? 'status' : 'done', data: { kind: 'running', text: start ? 'Acquisition running' : 'Stopped cleanly' } });
          const confirmed = viewSnapshot();
          if (lateFailure) reject(new Error('late request failure'));
          else resolve({ ok: true });
          await pending;
          if (first.pendingAction || first.running !== start || viewSnapshot() !== confirmed) throw new Error(kind + ' late HTTP response overwrote acquisition confirmation');
        }
      }
      first.running = false;
      activateInstance(first.id);
      document.getElementById(switchId).checked = true;
      api = async () => ({});
      await handleRunSwitchChange(kind, switchId, startFn, stopFn);
      handleInstrumentEvent({ instrument_id: first.id, event: 'error', data: { text: 'Instrument failed to start' } });
      if (first.running || first.pendingAction || document.getElementById(switchId).checked || document.getElementById(switchId).disabled) throw new Error(kind + ' terminal error did not release the waiting toggle');
      first.running = second.running = false;
      if (refresh) {
        activateInstance(first.id);
        api = async () => ({ resources: ['SMOKE::UNKNOWN', 'SMOKE::DISCONNECTED'], valid_count: 0 });
        await refresh();
        const badgeId = kind + 'ResourceCount';
        if (document.getElementById(badgeId).textContent !== '0') throw new Error(kind + ' counted resources without a valid identity');
        let resolve;
        api = () => new Promise((done) => { resolve = done; });
        const pending = refresh();
        activateInstance(second.id);
        setDiscoveredInstrumentCount(badgeId, 7);
        const before = viewSnapshot();
        resolve({ resources: ['SMOKE::STALE'], valid_count: 1 });
        await pending;
        if (viewSnapshot() !== before) throw new Error(kind + ' discovery changed the newly selected instrument');
      }
      if (kind === 'wlm') {
        activateInstance(first.id);
        document.getElementById(switchId).checked = true;
        smokeWlmUsbMode.disabled = smokeWlmEthernetMode.disabled = smokeWlmCheck.disabled = true;
        api = async () => { throw new Error('start failed'); };
        await handleRunSwitchChange(kind, switchId, startFn, stopFn);
        if (first.running || document.getElementById(switchId).checked || document.getElementById(switchId).disabled || smokeWlmUsbMode.disabled || smokeWlmEthernetMode.disabled || smokeWlmCheck.disabled) throw new Error('WLM controls did not recover after a failed start');
      }
      delete state.instances[first.id];
      delete state.instances[second.id];
      state.instruments = state.instruments.filter((item) => item.id !== first.id && item.id !== second.id);
    }
  } finally {
    api = raceApi;
    refreshActiveInstanceOptions = raceRefresh;
    activateInstance(smokeOpmId);
  }

  const devicesApi = api;
  const instrumentCountBeforeDiscovery = state.instruments.length;
  const deviceRows = [
    { id: 'usb-dmm', resource: 'USB0::0x2A8D::0x1301::MY123::INSTR', model: '34461A', type: 'dmm', manufacturer: 'Keysight', serial: 'MY123', firmware: '1.0', transport: 'USB', status: 'available', identification: 'Identified' },
    { id: 'usb-other', resource: 'USB0::1::2::SCOPE::INSTR', model: 'Scope 100', type: '', manufacturer: '<img src=x>', serial: 'SCOPE', transport: 'USB', status: 'available', identification: 'Identity not recognized by this app.' },
    { id: 'usb-unknown', resource: 'USB0::1::2::UNKNOWN::INSTR', model: '', type: '', transport: 'USB', status: 'available', identification: 'Identity query timed out.' },
    { id: 'usb-disconnected', resource: 'USB0::1::2::OFFLINE::INSTR', model: '', type: '', transport: 'USB', status: 'unavailable', identification: 'Connection failed.' },
    { id: 'usb-known-disconnected', resource: 'USB0::1::2::KNOWN::INSTR', model: '34465A', type: 'dmm', transport: 'USB', status: 'unavailable', identification: 'Connection lost.' }
  ];
  try {
    setView('home');
    const icon = document.querySelector('#openDevices');
    if (!icon?.querySelector('img[src$="/usb.svg"]') || !icon.closest('.home-actions')) throw new Error('Missing homepage Devices icon');
    let resolveScan;
    let scans = 0;
    api = (path) => {
      if (path !== '/api/devices') throw new Error('Unexpected device API request: ' + path);
      scans += 1;
      return new Promise((resolve) => { resolveScan = resolve; });
    };
    icon.click();
    await loadDevices();
    if (scans !== 1 || !document.querySelector('#refreshDevices').disabled || !document.querySelector('#devicesStatus').textContent.includes('Looking')) throw new Error('Device refresh overlaps or lacks a loading state');
    resolveScan({ devices: deviceRows, warnings: [] });
    await wait(400);
    if (!document.querySelector('[data-view="devices"].active')) throw new Error('Devices page did not open');
    if (document.querySelector('#unidentifiedDevices').open || document.querySelector('#unidentifiedDevices').hidden) throw new Error('Unidentified group is not collapsed by default');
    if (document.querySelector('#disconnectedDevices').open || document.querySelector('#disconnectedDevices').hidden) throw new Error('Disconnected group is not collapsed by default');
    if (document.querySelector('#unidentifiedDevicesSummary').textContent !== 'Unidentified (2)' || document.querySelector('#disconnectedDevicesSummary').textContent !== 'Disconnected (2)') throw new Error('Device group counts are incorrect');
    for (const [id, expected] of [
      ['devicesList', 'usb-dmm'],
      ['unidentifiedDevicesList', 'usb-other,usb-unknown'],
      ['disconnectedDevicesList', 'usb-disconnected,usb-known-disconnected']
    ]) {
      if ([...document.getElementById(id).children].map((row) => row.dataset.deviceId).join(',') !== expected) throw new Error('Incorrect devices in ' + id);
    }
    const sidebarBounds = document.querySelector('[data-view="devices"] .library-sidebar').getBoundingClientRect();
    const detailBounds = document.querySelector('#deviceDetail').getBoundingClientRect();
    if (sidebarBounds.right > detailBounds.left || detailBounds.right > innerWidth) throw new Error('Devices list and detail do not fit side by side');
    if (document.querySelector('#deviceName').textContent !== '34461A') throw new Error('First identified instrument was not selected');
    click('#unidentifiedDevicesSummary');
    click('[data-device-id="usb-other"]');
    if (document.querySelector('#deviceMetadata img') || !document.querySelector('#deviceMetadata').textContent.includes('<img src=x>')) throw new Error('Device identity is not safely rendered as text');
    click('[data-device-id="usb-unknown"]');
    if (!document.querySelector('#deviceMetadata').textContent.includes('Identity query timed out.') || document.querySelector('#deviceName').textContent !== deviceRows[2].resource) throw new Error('Unidentified details did not render');
    api = async () => ({ devices: [...deviceRows].reverse(), warnings: [] });
    await loadDevices();
    if (state.devices.selectedId !== 'usb-unknown' || !document.querySelector('#unidentifiedDevices').open) throw new Error('Refresh lost selection or disclosure state');
    click('#disconnectedDevicesSummary');
    click('[data-device-id="usb-disconnected"]');
    if (!document.querySelector('#deviceMetadata').textContent.includes('Disconnected') || !document.querySelector('#deviceMetadata').textContent.includes('Connection failed.')) throw new Error('Disconnected details did not render');
    await loadDevices();
    if (state.devices.selectedId !== 'usb-disconnected' || !document.querySelector('#disconnectedDevices').open) throw new Error('Refresh lost the disconnected selection or disclosure state');
    api = async () => ({ devices: [{ ...deviceRows[3], model: '34465A', type: 'dmm', status: 'available', identification: 'Identified' }], warnings: [] });
    await loadDevices();
    if (state.devices.selectedId !== 'usb-disconnected' || !document.querySelector('#devicesList [data-device-id="usb-disconnected"]') || !document.querySelector('#disconnectedDevices').hidden || document.querySelector('#deviceName').textContent !== '34465A') throw new Error('Reconnected device did not move to the identified list');
    api = async () => ({ devices: [deviceRows[1]], warnings: ['VISA discovery unavailable.'] });
    await loadDevices();
    if (state.devices.selectedId || !document.querySelector('#unidentifiedDevicesList [data-device-id="usb-other"]') || !document.querySelector('#devicesStatus').textContent.includes('unavailable')) throw new Error('Partial discovery discarded an unidentified instrument or selected it automatically');
    api = async () => ({ devices: [deviceRows[3]], warnings: [] });
    await loadDevices();
    if (state.devices.selectedId || document.querySelector('#disconnectedDevices').hidden || !document.querySelector('#unidentifiedDevices').hidden || document.querySelector('#devicesEmpty').textContent.includes('Unidentified')) throw new Error('Disconnected-only inventory is mislabeled');
    api = async () => ({ devices: [], warnings: [] });
    await loadDevices();
    if (state.devices.selectedId || !document.querySelector('#deviceDetail').classList.contains('hidden') || document.querySelector('#deviceMetadata').textContent) throw new Error('Disconnected device details were retained');
    if (document.querySelector('#devicesEmpty').textContent !== 'No USB instruments found.') throw new Error('Missing empty device state');
    if (!document.querySelector('#unidentifiedDevices').hidden || !document.querySelector('#disconnectedDevices').hidden) throw new Error('Empty device groups stayed visible');
    api = async () => { throw new Error('Backend unavailable'); };
    await loadDevices();
    if (!document.querySelector('#devicesEmpty').textContent.includes('failed') || !errorQueue.some((item) => item.message === 'Backend unavailable') || document.querySelector('#devicesStatus').dataset.severity !== 'warning') throw new Error('Discovery failure did not produce an error prompt and warning');
    api = () => new Promise((resolve) => { resolveScan = resolve; });
    const pending = loadDevices();
    setView('home');
    resolveScan({ devices: deviceRows, warnings: [] });
    await pending;
    if (state.currentView !== 'home') throw new Error('Late discovery response changed the active page');
    api = async () => ({ devices: [deviceRows[0]], warnings: [] });
    setView('devices');
    await wait(40);
    if (state.devices.items.length !== 1 || document.querySelector('#deviceName').textContent !== '34461A') throw new Error('Page entry did not refresh device data');
    if (state.instruments.length !== instrumentCountBeforeDiscovery) throw new Error('Discovery created an instrument card');
    click('[data-view="devices"] [data-return-home]');
    if (state.currentView !== 'home') throw new Error('Devices heading did not return home');
  } finally {
    api = devicesApi;
  }
};

module.exports.checkAppearance = async function checkAppearance(theme) {
  const waitFor = async (check, message) => {
    for (let attempt = 0; attempt < 100; attempt += 1) {
      if (check()) return;
      await new Promise((resolve) => setTimeout(resolve, 30));
    }
    throw new Error(message);
  };
  const dark = theme === 'dark';
  const expectedText = dark ? '#e4eaf2' : '#27313f';
  await waitFor(() => window.matchMedia('(prefers-color-scheme: dark)').matches === dark &&
    chartColors.text === expectedText, 'System theme change did not reach CSS and charts');
  const charts = Object.values(Chart.instances);
  if (charts.length !== 11) throw new Error('Missing themed chart');
  for (const chart of charts) {
    if (chart.options.plugins.title.color !== expectedText) throw new Error('Chart title did not follow theme');
    for (const scale of Object.values(chart.scales)) {
      if (scale.options.ticks.color !== chartColors.muted || scale.options.title.color !== chartColors.muted ||
          scale.options.grid.color !== chartColors['chart-grid']) throw new Error('Chart axis did not follow theme: ' +
            JSON.stringify({ chart: chart.canvas.id, axis: scale.id, ticks: scale.options.ticks.color, title: scale.options.title.color,
              grid: scale.options.grid.color, expected: chartColors }));
    }
    const lineColor = chart.getDatasetMeta(0).dataset.options.borderColor;
    if (![chartColors.blue, chartColors.green, chartColors.amber, chartColors.teal, chartColors.power].includes(lineColor)) {
      throw new Error('Chart trace did not follow theme');
    }
  }
  if (dark) {
    const luminance = (color) => {
      const rgb = color.match(/[\d.]+/g).slice(0, 3).map((v) => {
        const n = Number(v) / 255;
        return n <= 0.04045 ? n / 12.92 : ((n + 0.055) / 1.055) ** 2.4;
      });
      return rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722;
    };
    for (const selector of ['.button', '.button.danger', '.inset-input', '.warning-banner', '.status-pill', '.resource-count-badge', '.about-model-number']) {
      const style = getComputedStyle(document.querySelector(selector));
      const fg = luminance(style.color);
      const bg = luminance(style.backgroundColor);
      if ((Math.max(fg, bg) + 0.05) / (Math.min(fg, bg) + 0.05) < 4.5) {
        throw new Error('Insufficient dark-mode text contrast: ' + selector);
      }
    }
  }
  for (const maximized of [true, false]) {
    document.querySelector('#maximizeWindow').click();
    await waitFor(() => document.body.classList.contains('maximized') === maximized,
      'Maximize/restore event did not update the layout');
    await waitFor(() => {
      const rect = document.querySelector('.window-shell').getBoundingClientRect();
      const gutter = maximized ? 0 : 28;
      return rect.x === gutter && rect.y === gutter &&
        rect.width === innerWidth - gutter * 2 && rect.height === innerHeight - gutter * 2;
    }, 'Window shell does not fill the expected bounds');
    if (await window.openUfc.isWindowMaximized() !== maximized) throw new Error('Native maximize state is out of sync');
    const label = document.querySelector('#maximizeWindow').getAttribute('aria-label');
    if (label !== (maximized ? 'Restore window' : 'Maximize')) throw new Error('Incorrect maximize button label');
  }
};

module.exports.checkPreferences = async function checkPreferences() {
  const wait = (ms = 30) => new Promise(resolve => setTimeout(resolve, ms));
  const waitFor = async (check, message) => {
    for (let i = 0; i < 100; i++) {
      if (check()) return;
      await wait();
    }
    throw new Error(message);
  };
  const errorDialog = $('errorDialog');
  const dismissErrors = async () => {
    while (errorDialog.open) { errorDialog.close(); await wait(); }
  };
  await dismissErrors();
  for (const kind of ['ufc', 'dmm', 'wlm', 'opm']) {
    const instance = state.instances[state.instruments.find(item => item.type === kind).id];
    activateInstance(instance.id);
    const status = $(kind === 'ufc' ? 'statusText' : `${kind}StatusText`);
    for (const statusKind of ['warning', 'reconnecting']) {
      handleInstrumentEvent({ instrument_id: instance.id, event: 'status', data: { text: 'Recovering from a temporary problem', kind: statusKind } });
      if (status.dataset.severity !== 'warning' || errorDialog.open) throw new Error('Recoverable warning incorrectly presented: ' + statusKind);
    }
    const warningColor = getComputedStyle(status).color;
    handleInstrumentEvent({ instrument_id: instance.id, event: 'status', data: { text: 'Ready', kind: 'connected', badge: 'READY' } });
    if (status.dataset.severity !== 'info' || getComputedStyle(status).color === warningColor) throw new Error('Info and warning colors are not distinct');
    const failure = { instrument_id: instance.id, event: 'error', data: { text: 'VI_ERROR_NCIC <img src=x>', details: 'Technical details\nVISA connection failed' } };
    handleInstrumentEvent(failure);
    handleInstrumentEvent(failure);
    if (!errorDialog.open || errorQueue.length !== 1 || status.textContent.includes('VI_ERROR') || status.dataset.severity !== 'warning') throw new Error('Critical error was not isolated to a single prompt');
    if ($('errorMessage').textContent !== failure.data.text || $('errorMessage').querySelector('img') || $('errorDetailsText').textContent !== failure.data.details) throw new Error('Error details were lost or interpreted as HTML');
    if (!errorDialog.contains(document.activeElement)) throw new Error('Error dialog did not receive keyboard focus');
    await dismissErrors();
  }
  showError('First operation', 'First failure');
  showError('Second operation', 'Second failure');
  errorDialog.close();
  await wait();
  if (!errorDialog.open || $('errorMessage').textContent !== 'Second failure') throw new Error('A concurrent error was lost');
  await dismissErrors();

  setView('home');
  for (const mode of ['light', 'dark', 'auto']) {
    openGlobalSettings();
    document.querySelector(`[data-color-mode="${mode}"]`).click();
    await waitFor(() => state.colorMode === mode, 'Appearance button did not select mode');
    if (mode !== 'auto') await waitFor(() => matchMedia('(prefers-color-scheme: dark)').matches === (mode === 'dark'), 'Appearance preview did not apply');
    await saveGlobalSettings();
    await wait(220);
    if ((await api('/api/config')).platform.color_mode !== mode) throw new Error('Appearance choice did not persist');
  }
  openGlobalSettings();
  await previewColorMode('dark');
  $('globalSettingsDialog').close();
  await waitFor(() => state.colorMode === 'auto', 'Cancel did not restore saved appearance');
  const realApi = api;
  openGlobalSettings();
  $('globalLibraryDir').value = 'unsaved-folder';
  api = async () => { throw new Error('Disk is read-only'); };
  try {
    $('saveGlobalSettings').click();
    await waitFor(() => errorDialog.open, 'Failed settings save did not show an error');
    if (!$('globalSettingsDialog').open || $('globalLibraryDir').value !== 'unsaved-folder') throw new Error('Failed settings save discarded input');
    await dismissErrors();
  } finally {
    api = realApi;
    $('globalSettingsDialog').close();
    await wait();
  }
};
