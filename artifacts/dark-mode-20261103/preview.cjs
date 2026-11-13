const { app, nativeTheme, screen } = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '../..');
const output = path.join(__dirname, 'previews');
fs.mkdirSync(output, { recursive: true });
app.getAppPath = () => root;
app.getVersion = () => require(path.join(root, 'package.json')).version;
process.argv.push('--smoke');
nativeTheme.themeSource = 'dark';
const smokePath = require.resolve(path.join(root, 'electron/smoke.js'));
const smoke = require(smokePath);
require.cache[smokePath].exports = Object.assign(async function pauseForPreview() {
  await new Promise((resolve) => { window.finishPreview = resolve; });
}, { checkAppearance: smoke.checkAppearance });
app.on('browser-window-created', (_event, win) => {
  win.webContents.once('did-finish-load', async () => {
    const run = (code) => win.webContents.executeJavaScript(code);
    const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
    const capture = async (name) => {
      await wait(450);
      fs.writeFileSync(path.join(output, name + '.png'), (await win.webContents.capturePage()).toPNG());
    };
    try {
      for (let attempt = 0; attempt < 100; attempt++) {
        if (await run('Boolean(window.finishPreview && state.config && state.instruments.length)')) break;
        await wait(100);
      }
      win.setSize(1440, 980);
      await run("addInstrument('wlm')");
      await run("addInstrument('opm')");
      await capture('dark-home');
      await run("$('addInstrument').click()");
      await capture('dark-menu');
      await run('closeAddInstrumentMenu()');
      for (const kind of ['ufc', 'dmm', 'wlm', 'opm']) {
        await run(`activateInstance(state.instruments.find(item => item.type === '${kind}').id); setView('${kind}');
          for (const chart of Object.values(Chart.instances)) {
            chart.data.datasets[0].data = Array.from({length: 90}, (_, i) => ({x: (i + 1) / 10, y: chart.canvas.id.toLowerCase().includes('adev') ? 1e-9 / Math.sqrt(i + 1) : 10 + 0.01 * Math.sin(i * 0.7) + 0.005 * Math.cos(i * 1.8)}));
            chart.update('none');
          }`);
        await capture('dark-' + kind);
      }
      await run("setView('home'); $('openAbout').click()");
      await capture('dark-about');
      await run("$('aboutDialog').close(); $('openGlobalSettings').click()");
      await capture('dark-settings');
      await run("$('openResetConfig').click()");
      await capture('dark-reset');
      await run("$('resetConfigDialog').close(); $('globalSettingsDialog').close(); activateInstance(state.instruments.find(item => item.type === 'ufc').id); setView('ufc')");
      win.maximize();
      await capture('dark-maximized');
      const bounds = win.getBounds();
      const workArea = screen.getDisplayMatching(bounds).workArea;
      fs.writeFileSync(path.join(output, 'window-bounds.json'), JSON.stringify({ bounds, workArea }, null, 2));
      win.unmaximize();
      nativeTheme.themeSource = 'light';
      await capture('light-ufc');
      await run("setView('home'); $('openAbout').click()");
      await capture('light-about');
      await run("$('aboutDialog').close(); window.finishPreview()");
    } catch (error) {
      console.error(error);
      app.quit();
    }
  });
});
require(path.join(root, 'electron/main.js'));
