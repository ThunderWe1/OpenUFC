const { app, BrowserWindow, dialog, ipcMain, nativeTheme, shell } = require('electron');
const path = require('node:path');
const { spawn, spawnSync } = require('node:child_process');
const fs = require('node:fs');

let mainWindow = null;
let startupWindow = null;
let backendProcess = null;
let backendUrl = null;
let quitting = false;
let allowWindowClose = false;
let resettingConfig = false;
let stoppingBackend = false;

function pythonExecutable() {
  if (process.env.OPENUFC_PYTHON) {
    return process.env.OPENUFC_PYTHON;
  }
  const root = app.getAppPath();
  const candidate = process.platform === 'win32'
    ? path.join(root, '.venv', 'Scripts', 'python.exe')
    : path.join(root, '.venv', 'bin', 'python');
  if (fs.existsSync(candidate)) {
    return candidate;
  }
  if (process.platform === 'win32') {
    const launcher = spawnSync('py', ['--version'], { windowsHide: true });
    if (!launcher.error && launcher.status === 0) {
      return 'py';
    }
  }
  return process.platform === 'win32' ? 'python' : 'python3';
}

function backendCommand() {
  if (app.isPackaged) {
    return {
      command: path.join(process.resourcesPath, 'backend', 'openufc-backend.exe'),
      args: ['--server', '--port', '0'],
      cwd: dataDirectory()
    };
  }
  return {
    command: pythonExecutable(),
    args: [path.join(app.getAppPath(), 'main.py'), '--server', '--port', '0'],
    cwd: dataDirectory()
  };
}

function dataDirectory() {
  return app.isPackaged || process.argv.includes('--smoke') ? app.getPath('userData') : app.getAppPath();
}

function configFilePath() {
  return path.join(dataDirectory(), 'config.json');
}

function setColorMode(mode) {
  if (!['auto', 'light', 'dark'].includes(mode)) throw new Error('Invalid color mode');
  nativeTheme.themeSource = mode === 'auto' ? 'system' : mode;
}

function scheduleRelaunch() {
  setTimeout(() => {
    quitting = true;
    allowWindowClose = true;
    app.relaunch({ execPath: process.env.PORTABLE_EXECUTABLE_FILE || process.execPath });
    app.exit(0);
  }, 75);
}

function waitForProcessExit(proc, timeoutMs) {
  if (proc.exitCode !== null || proc.signalCode !== null) {
    return Promise.resolve(true);
  }
  return new Promise((resolve) => {
    const onExit = () => {
      clearTimeout(timer);
      resolve(true);
    };
    const timer = setTimeout(() => {
      proc.removeListener('exit', onExit);
      resolve(false);
    }, timeoutMs);
    proc.once('exit', onExit);
  });
}

function startBackend() {
  stoppingBackend = false;
  return new Promise((resolve, reject) => {
    const backend = backendCommand();
    fs.mkdirSync(backend.cwd, { recursive: true });
    const child = spawn(backend.command, backend.args, {
      cwd: backend.cwd,
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true
    });
    backendProcess = child;

    let stdoutBuffer = '';
    let settled = false;

    const fail = (message) => {
      if (!settled) {
        settled = true;
        reject(new Error(message));
      }
    };

    child.stdout.on('data', (chunk) => {
      stdoutBuffer += chunk.toString();
      const lines = stdoutBuffer.split(/\r?\n/);
      stdoutBuffer = lines.pop() || '';
      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const msg = JSON.parse(line);
          if (msg.event === 'SERVER_READY') {
            backendUrl = `http://${msg.host}:${msg.port}`;
            if (!settled) {
              settled = true;
              resolve(backendUrl);
            }
          }
        } catch {
          console.log(`[backend] ${line}`);
        }
      }
    });

    child.stderr.on('data', (chunk) => {
      console.error(`[backend] ${chunk.toString()}`);
    });

    child.on('error', (error) => fail(`Could not start the backend: ${error.message}`));

    child.on('exit', (code, signal) => {
      backendProcess = null;
      if (!settled) {
        fail(`Python backend exited before startup (code ${code}, signal ${signal})`);
      } else if (!quitting && !resettingConfig && !stoppingBackend && mainWindow) {
        mainWindow.webContents.send('backend:error', 'The measurement service stopped unexpectedly. Restart OpenUFC before acquiring more data.');
      }
    });

    setTimeout(() => fail('Python backend did not announce readiness'), 15000);
  });
}

async function stopBackend() {
  stoppingBackend = true;
  if (!backendProcess) {
    backendUrl = null;
    return;
  }
  const proc = backendProcess;
  try {
    if (backendUrl) {
      await fetch(`${backendUrl}/api/shutdown`, {
        method: 'POST',
        signal: AbortSignal.timeout(5000)
      });
    } else {
      proc.kill();
    }
  } catch {
    proc.kill();
  }
  // The backend may be finishing a counter read and draining its buffer.
  // Its shutdown allows up to 60 s for recording finalization.
  if (!(await waitForProcessExit(proc, 65000))) {
    proc.kill();
    if (!(await waitForProcessExit(proc, 2000))) {
      throw new Error('The backend did not stop; configuration was not reset.');
    }
  }
  backendUrl = null;
}

async function showStartupWindow() {
  startupWindow = new BrowserWindow({
    width: 480, height: 240, useContentSize: true, frame: false, resizable: false,
    maximizable: false, fullscreenable: false, show: false, backgroundColor: '#232a33',
    title: 'Starting OpenUFC', icon: path.join(app.getAppPath(), 'assets', 'icon.ico'),
    webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false }
  });
  startupWindow.on('closed', () => { startupWindow = null; });
  await startupWindow.loadFile(path.join(app.getAppPath(), 'ui', 'startup.html'));
  startupWindow.show();
}

function revealMainWindow() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  mainWindow.show();
  if (startupWindow) startupWindow.destroy();
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 980,
    show: false,
    minWidth: 1180,
    minHeight: 820,
    backgroundColor: '#00000000',
    transparent: true,
    title: 'Laser Measurement Platform',
    icon: path.join(app.getAppPath(), 'assets', 'icon.ico'),
    frame: false,
    titleBarStyle: 'hidden',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  });

  mainWindow.loadFile(path.join(app.getAppPath(), 'ui', 'index.html'));
  mainWindow.webContents.on('did-fail-load', (_event, code, description, _url, isMainFrame) => {
    if (!isMainFrame) return;
    if (startupWindow) startupWindow.destroy();
    dialog.showErrorBox('Could not open OpenUFC', `${description} (${code})`);
    app.quit();
  });

  for (const event of ['maximize', 'unmaximize']) {
    mainWindow.on(event, () => {
      mainWindow.webContents.send('window:maximized-changed', mainWindow.isMaximized());
    });
  }

  mainWindow.on('close', (event) => {
    if (allowWindowClose || process.argv.includes('--smoke')) {
      return;
    }
    event.preventDefault();
    mainWindow.webContents.send('app:close-requested');
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  if (process.argv.includes('--smoke')) {
    mainWindow.webContents.once('did-finish-load', () => {
      setTimeout(async () => {
        try {
          mainWindow.setSize(1180, 820);
          await mainWindow.webContents.executeJavaScript(`(${require('./smoke').toString()})()`);
          await mainWindow.webContents.executeJavaScript(`(${require('./smoke').checkPreferences.toString()})()`);
          if (nativeTheme.themeSource !== 'system') throw new Error('Auto appearance did not restore the system theme');
          for (const theme of ['dark', 'light', 'dark']) {
            nativeTheme.themeSource = theme;
            await mainWindow.webContents.executeJavaScript(`(${require('./smoke').checkAppearance.toString()})('${theme}')`);
          }
          nativeTheme.themeSource = 'system';
          await stopBackend();
          app.exit(0);
        } catch (error) {
          fs.writeFileSync(path.join(app.getPath('temp'), 'openufc-smoke-error.txt'), error && error.stack ? error.stack : String(error));
          console.error(`[smoke] ${error && error.stack ? error.stack : error}`);
          await stopBackend().catch(() => {});
          app.exit(1);
        }
      }, 1200);
    });
  }
}

ipcMain.handle('backend:get-url', () => backendUrl);
ipcMain.handle('app:get-version', () => app.getVersion());
ipcMain.handle('app:set-color-mode', (_event, mode) => setColorMode(mode));
ipcMain.handle('app:ready', revealMainWindow);
ipcMain.handle('library:open-folder', async () => {
  const response = await fetch(`${backendUrl}/api/library`);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || 'Could not locate the Library folder');
  const folder = payload.library_dir;
  if (typeof folder !== 'string' || !path.isAbsolute(folder)) throw new Error('Invalid Library folder');
  fs.mkdirSync(folder, { recursive: true });
  const error = await shell.openPath(folder);
  if (error) throw new Error(error);
});
ipcMain.handle('window:is-maximized', () => mainWindow?.isMaximized() ?? false);

ipcMain.handle('window:minimize', () => {
  if (mainWindow) mainWindow.minimize();
});

ipcMain.handle('window:toggle-maximize', () => {
  if (!mainWindow) return;
  if (mainWindow.isMaximized()) {
    mainWindow.unmaximize();
  } else {
    mainWindow.maximize();
  }
});

ipcMain.handle('window:close', () => {
  if (mainWindow) mainWindow.close();
});

ipcMain.handle('window:allow-close', () => {
  allowWindowClose = true;
  if (mainWindow) mainWindow.close();
});

ipcMain.handle('app:reset-config', async () => {
  if (resettingConfig) return { ok: false, error: 'Configuration reset is already in progress.' };
  resettingConfig = true;
  let backendStopped = false;
  try {
    await stopBackend();
    backendStopped = true;
    const configPath = configFilePath();
    fs.rmSync(configPath, { force: true });
    if (fs.existsSync(configPath)) {
      throw new Error('The configuration file could not be deleted.');
    }
    scheduleRelaunch();
    return { ok: true };
  } catch (error) {
    resettingConfig = false;
    if (backendStopped) scheduleRelaunch();
    throw error;
  }
});

ipcMain.handle('dialog:select-directory', async (_event, options = {}) => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: options.title || 'Select folder',
    defaultPath: options.defaultPath,
    properties: ['openDirectory']
  });
  return result.canceled ? null : result.filePaths[0];
});

ipcMain.handle('dialog:save-csv', async (_event, options = {}) => {
  const result = await dialog.showSaveDialog(mainWindow, {
    title: options.title || 'Save CSV',
    defaultPath: options.defaultPath,
    filters: [{ name: 'CSV files', extensions: ['csv'] }, { name: 'All files', extensions: ['*'] }]
  });
  return result.canceled ? null : result.filePath;
});

if (process.argv.includes('--smoke')) {
  app.setPath('userData', fs.mkdtempSync(path.join(app.getPath('temp'), 'openufc-smoke-')));
  nativeTheme.themeSource = 'dark';
}

app.whenReady().then(async () => {
  try {
    await showStartupWindow();
    await startBackend();
    if (quitting) return;
    if (startupWindow) await startupWindow.webContents.executeJavaScript("document.getElementById('startupStatus').textContent = 'Loading workspace…'");
    if (!process.argv.includes('--smoke')) {
      const config = JSON.parse(fs.readFileSync(configFilePath(), 'utf8'));
      setColorMode(config.platform?.color_mode || 'auto');
    }
    createWindow();
  } catch (error) {
    if (process.argv.includes('--smoke')) {
      console.error(`[smoke] Backend startup failed: ${error && error.stack ? error.stack : error}`);
      await stopBackend().catch(() => {});
      app.exit(1);
      return;
    }
    dialog.showErrorBox('Laser Measurement Platform startup failed', String(error && error.message ? error.message : error));
    if (startupWindow) startupWindow.destroy();
    app.quit();
  }
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('before-quit', (event) => {
  if (!backendProcess || quitting) {
    return;
  }
  event.preventDefault();
  quitting = true;
  stopBackend().finally(() => app.quit());
});
