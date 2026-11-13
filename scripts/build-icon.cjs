const { app, BrowserWindow } = require('electron');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const assets = path.join(__dirname, '../assets');
const sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256];
app.disableHardwareAcceleration();

app.whenReady().then(async () => {
  const window = new BrowserWindow({ show: false, webPreferences: { sandbox: true } });
  await window.loadURL('about:blank');
  const svg = fs.readFileSync(path.join(assets, 'icon.svg'), 'utf8');
  const images = await window.webContents.executeJavaScript(`(async () => {
    const image = new Image();
    image.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(${JSON.stringify(svg)});
    await image.decode();
    return ${JSON.stringify(sizes)}.map((size) => {
      const canvas = document.createElement('canvas');
      canvas.width = canvas.height = size;
      canvas.getContext('2d').drawImage(image, 0, 0, size, size);
      return canvas.toDataURL('image/png').split(',')[1];
    });
  })()`);
  const pngs = images.map((data) => Buffer.from(data, 'base64'));
  const directory = Buffer.alloc(6 + 16 * sizes.length);
  directory.writeUInt16LE(1, 2);
  directory.writeUInt16LE(sizes.length, 4);
  let offset = directory.length;
  pngs.forEach((png, index) => {
    assert.equal(png.readUInt32BE(16), sizes[index]);
    assert.equal(png.readUInt32BE(20), sizes[index]);
    const entry = 6 + index * 16;
    directory[entry] = directory[entry + 1] = sizes[index] % 256;
    directory.writeUInt16LE(1, entry + 4);
    directory.writeUInt16LE(32, entry + 6);
    directory.writeUInt32LE(png.length, entry + 8);
    directory.writeUInt32LE(offset, entry + 12);
    offset += png.length;
  });
  const icon = Buffer.concat([directory, ...pngs]);
  assert.equal(icon.length, offset);
  fs.writeFileSync(path.join(assets, 'icon.ico'), icon);
  fs.writeFileSync(path.join(assets, 'icon.png'), pngs.at(-1));
  window.setContentSize(480, 240);
  await window.loadFile(path.join(__dirname, '../ui/startup.html'));
  await window.webContents.executeJavaScript('document.fonts.ready');
  await window.webContents.insertCSS('.spinner { animation: none; }');
  const capture = (await window.webContents.capturePage()).resize({ width: 480, height: 240 });
  const pixels = capture.toBitmap();
  const stride = 480 * 3;
  const bitmap = Buffer.alloc(54 + stride * 240);
  bitmap.write('BM');
  bitmap.writeUInt32LE(bitmap.length, 2);
  bitmap.writeUInt32LE(54, 10);
  bitmap.writeUInt32LE(40, 14);
  bitmap.writeInt32LE(480, 18);
  bitmap.writeInt32LE(240, 22);
  bitmap.writeUInt16LE(1, 26);
  bitmap.writeUInt16LE(24, 28);
  bitmap.writeUInt32LE(stride * 240, 34);
  for (let y = 0; y < 240; y += 1) {
    for (let x = 0; x < 480; x += 1) {
      pixels.copy(bitmap, 54 + (239 - y) * stride + x * 3, (y * 480 + x) * 4, (y * 480 + x) * 4 + 3);
    }
  }
  assert.equal(pixels.length, 480 * 240 * 4);
  assert.equal(bitmap.length, bitmap.readUInt32LE(2));
  fs.writeFileSync(path.join(assets, 'startup.bmp'), bitmap);
  fs.writeFileSync(path.join(assets, 'startup.png'), capture.toPNG());
  console.log('Built icons at ' + sizes.join(', ') + ' px and the portable startup card.');
  app.quit();
}).catch((error) => {
  console.error(error);
  app.exit(1);
});
