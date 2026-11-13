const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');
const { EventEmitter } = require('node:events');

const source = fs.readFileSync(path.join(__dirname, '../electron/main.js'), 'utf8');

function loadMain(packaged) {
  const handlers = new Map();
  const nativeTheme = { themeSource: 'system' };
  const windows = [];
  class BrowserWindow extends EventEmitter {
    constructor(options) {
      super();
      this.visible = Boolean(options.show);
      this.destroyed = false;
      this.webContents = new EventEmitter();
      windows.push(this);
    }
    async loadFile() {}
    show() { this.visible = true; }
    isDestroyed() { return this.destroyed; }
    destroy() { this.destroyed = true; this.emit('closed'); }
  }
  const child = new EventEmitter();
  child.stdout = new EventEmitter();
  child.stderr = new EventEmitter();
  const app = {
    isPackaged: packaged,
    getAppPath: () => path.resolve('source'),
    getPath: () => path.resolve('user-data'),
    getVersion: () => '0.1.0',
    whenReady: () => new Promise(() => {}),
    on: () => {}
  };
  const context = vm.createContext({
    require: (name) => {
      if (name === 'electron') return { app, nativeTheme, BrowserWindow, ipcMain: { handle: (key, fn) => handlers.set(key, fn) } };
      if (name === 'node:child_process') return { spawn: () => child };
      if (name === 'node:fs') return { mkdirSync: () => {} };
      return require(name);
    },
    process: { argv: [], env: { OPENUFC_PYTHON: 'development-python' }, resourcesPath: path.resolve('resources') },
    setTimeout: () => {},
    __dirname: path.resolve('electron'),
    console
  });
  vm.runInContext(source, context);
  return { context, child, handlers, nativeTheme, windows };
}

test('packaged app uses its bundled backend and persistent settings directory', () => {
  const { context, handlers } = loadMain(true);
  const command = vm.runInContext('backendCommand()', context);
  assert.equal(command.command, path.resolve('resources/backend/openufc-backend.exe'));
  assert.equal(command.cwd, path.resolve('user-data'));
  assert.equal(command.args.join(' '), '--server --port 0');
  assert.equal(vm.runInContext('configFilePath()', context), path.join(command.cwd, 'config.json'));
  assert.equal(handlers.get('app:get-version')(), '0.1.0');
});

test('development app retains its Python override and project settings', () => {
  const { context } = loadMain(false);
  const command = vm.runInContext('backendCommand()', context);
  assert.equal(command.command, 'development-python');
  assert.equal(command.args[0], path.resolve('source/main.py'));
  assert.equal(command.cwd, path.resolve('source'));
  assert.equal(vm.runInContext('configFilePath()', context), path.resolve('source/config.json'));
  context.process.argv.push('--smoke');
  assert.equal(vm.runInContext('backendCommand().cwd', context), path.resolve('user-data'));
});

test('backend launch errors are reported instead of crashing the main process', async () => {
  const { context, child } = loadMain(true);
  const started = vm.runInContext('startBackend()', context);
  child.emit('error', new Error('ENOENT'));
  await assert.rejects(started, /Could not start the backend: ENOENT/);
});

test('appearance IPC accepts only the three supported modes', () => {
  const { handlers, nativeTheme } = loadMain(false);
  for (const [mode, source] of [['dark', 'dark'], ['light', 'light'], ['auto', 'system']]) {
    handlers.get('app:set-color-mode')(null, mode);
    assert.equal(nativeTheme.themeSource, source);
  }
  assert.throws(() => handlers.get('app:set-color-mode')(null, 'invalid'), /Invalid color mode/);
  assert.equal(nativeTheme.themeSource, 'system');
});

test('startup card remains visible until the renderer reports ready', async () => {
  const { context, handlers, windows } = loadMain(false);
  await vm.runInContext('showStartupWindow()', context);
  assert.equal(windows[0].visible, true);
  vm.runInContext('createWindow()', context);
  assert.equal(windows[1].visible, false);
  assert.equal(windows[0].destroyed, false);
  handlers.get('app:ready')();
  assert.equal(windows[1].visible, true);
  assert.equal(windows[0].destroyed, true);
});
