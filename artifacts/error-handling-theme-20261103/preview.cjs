const { app, nativeTheme } = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '../..');
const output = path.join(__dirname, 'previews');
fs.mkdirSync(output, { recursive: true });
app.getAppPath = () => root;
app.getVersion = () => require(path.join(root, 'package.json')).version;
process.argv.push('--smoke');
const smokePath = require.resolve(path.join(root, 'electron/smoke.js'));
const smoke = require(smokePath);
require.cache[smokePath].exports = Object.assign(async function pauseForPreview() {
  await new Promise((resolve) => { window.finishPreview = resolve; });
}, { checkAppearance: smoke.checkAppearance, checkPreferences: smoke.checkPreferences });
app.on('browser-window-created', (_event, win) => {
  win.webContents.once('did-finish-load', async () => {
    if (!win.webContents.getURL().endsWith('/ui/index.html')) return;
    const run = (code) => win.webContents.executeJavaScript(code);
    const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
    const capture = async (name) => {
      await wait(450);
      fs.writeFileSync(path.join(output, name + '.png'), (await win.webContents.capturePage()).resize({ width: 1440 }).toPNG());
    };
    try {
      for (let attempt = 0; attempt < 100; attempt++) {
        if (await run('Boolean(window.finishPreview && state.config && state.instruments.length)')) break;
        await wait(100);
      }
      win.setSize(1440, 980);
      await run("addInstrument('wlm'); addInstrument('opm')");
      await run("$('openGlobalSettings').click(); previewColorMode('dark')");
      await capture('dark-settings');
      await run("previewColorMode('light')");
      await capture('light-settings');
      await run("$('globalSettingsDialog').close()");
      await wait(150);
      nativeTheme.themeSource = 'dark';
      await run("activateInstance(state.instruments.find(item => item.type === 'ufc').id); setView('ufc'); reportInstrumentError(activeInstance(), 'Connection failed', new Error('VI_ERROR_NCIC (-1073807264): The interface associated with this session is not currently the controller in charge.'))");
      await capture('dark-error');
      nativeTheme.themeSource = 'light';
      await capture('light-error');
      await run("$('errorDialog').close()");
      await capture('light-warning');
      await run('window.finishPreview()');
    } catch (error) {
      console.error(error);
      app.quit();
    }
  });
});
require(path.join(root, 'electron/main.js'));
