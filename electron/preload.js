const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('openUfc', {
  appVersion: () => ipcRenderer.invoke('app:get-version'),
  ready: () => ipcRenderer.invoke('app:ready'),
  openLibraryFolder: () => ipcRenderer.invoke('library:open-folder'),
  setColorMode: (mode) => ipcRenderer.invoke('app:set-color-mode', mode),
  onBackendError: (callback) => {
    ipcRenderer.on('backend:error', (_event, message) => callback(message));
  },
  backendUrl: () => ipcRenderer.invoke('backend:get-url'),
  minimizeWindow: () => ipcRenderer.invoke('window:minimize'),
  toggleMaximizeWindow: () => ipcRenderer.invoke('window:toggle-maximize'),
  isWindowMaximized: () => ipcRenderer.invoke('window:is-maximized'),
  onMaximizedChanged: (callback) => {
    ipcRenderer.on('window:maximized-changed', (_event, maximized) => callback(maximized));
  },
  closeWindow: () => ipcRenderer.invoke('window:close'),
  allowCloseWindow: () => ipcRenderer.invoke('window:allow-close'),
  resetConfig: () => ipcRenderer.invoke('app:reset-config'),
  onCloseRequested: (callback) => {
    ipcRenderer.on('app:close-requested', () => callback());
  },
  selectDirectory: (options) => ipcRenderer.invoke('dialog:select-directory', options),
  saveCsv: (options) => ipcRenderer.invoke('dialog:save-csv', options)
});
