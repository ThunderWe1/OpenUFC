const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const root = path.resolve(__dirname, '..');
const buildRoot = path.join(root, 'build');
const buildId = `${new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14)}-${process.pid}`;

function run(command, args) {
  const result = spawnSync(command, args, {
    cwd: root,
    stdio: 'inherit',
    windowsHide: true
  });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`${command} exited with code ${result.status}`);
}

function works(python) {
  if (!fs.existsSync(python)) return false;
  const result = spawnSync(python, ['-c', 'import PyInstaller, numpy, pyvisa, pyvisa_py, telnetlib3'], {
    cwd: root,
    stdio: 'ignore',
    windowsHide: true
  });
  return !result.error && result.status === 0;
}

function buildPython() {
  const candidates = [
    path.join(root, '.build-venv', 'Scripts', 'python.exe'),
    path.join(root, '.build-venv-current', 'Scripts', 'python.exe')
  ];
  const existing = candidates.find(works);
  if (existing) return existing;

  const venv = path.join(root, `.build-venv-${buildId}`);
  run('py', ['-3', '-m', 'venv', venv]);
  const python = path.join(venv, 'Scripts', 'python.exe');
  run(python, ['-m', 'pip', 'install', '-r', path.join(root, 'requirements-build.txt')]);
  return python;
}

const python = buildPython();
const backendDir = path.join(buildRoot, `backend-${buildId}`);
const workDir = path.join(buildRoot, `pyinstaller-${buildId}`);
const specDir = path.join(buildRoot, `spec-${buildId}`);
run(python, [
  '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--console',
  '--name', 'openufc-backend', '--distpath', backendDir, '--workpath', workDir,
  '--specpath', specDir, '--collect-submodules', 'pyvisa',
  '--collect-submodules', 'pyvisa_py', '--collect-all', 'telnetlib3', 'main.py'
]);

const packageJson = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));
const builderConfig = JSON.parse(JSON.stringify(packageJson.build));
builderConfig.extraResources[0].from = path.relative(root, path.join(backendDir, 'openufc-backend'));
builderConfig.directories.output = path.relative(root, path.join(root, `dist-${buildId}`));
fs.mkdirSync(buildRoot, { recursive: true });
fs.writeFileSync(
  path.join(buildRoot, 'electron-builder-generated.json'),
  `${JSON.stringify(builderConfig, null, 2)}\n`,
  'utf8'
);
console.log(`Backend output: ${path.join(backendDir, 'openufc-backend')}`);
console.log(`Electron-builder config: ${path.join(buildRoot, 'electron-builder-generated.json')}`);
