// WEB DIR MAP — Electron main process
const { app, BrowserWindow, ipcMain, dialog } = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const fs = require('fs');

let mainWindow;
let activeProcess = null;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 960,
    height: 900,
    minWidth: 700,
    minHeight: 720,
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false,
    },
    backgroundColor: '#0e0d0c',
    autoHideMenuBar: true,
    title: 'WEB DIR MAP v1.0',
  });
  mainWindow.loadFile('index.html');
}

app.whenReady().then(createWindow);
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });

ipcMain.handle('cancel-mapping', async () => {
  if (activeProcess) {
    try { activeProcess.kill('SIGTERM'); } catch (_) {}
    try { activeProcess.kill('SIGKILL'); } catch (_) {}
    activeProcess = null;
    return true;
  }
  return false;
});

// Locate a standalone binary (PyInstaller) — preferred for end-users.
function findStandaloneBinary() {
  const exe = process.platform === 'win32' ? 'web_dir_mapper.exe' : 'web_dir_mapper';
  const candidates = [
    path.join(process.resourcesPath || '', exe),
    path.join(process.resourcesPath || '', 'bin', exe),
    path.join(__dirname, 'bin', exe),
    path.join(__dirname, exe),
  ];
  for (const c of candidates) {
    try { if (c && fs.existsSync(c)) return c; } catch (_) {}
  }
  return null;
}

function findPythonScript() {
  const candidates = [
    path.join(process.resourcesPath || '', 'web_dir_mapper.py'),
    path.join(__dirname, 'web_dir_mapper.py'),
  ];
  for (const c of candidates) {
    try { if (c && fs.existsSync(c)) return c; } catch (_) {}
  }
  return null;
}

ipcMain.handle('map-web', async (event, options) => {
  return new Promise((resolve, reject) => {
    const payload = JSON.stringify({
      url: options.url || '',
      hidden_extensions: options.hidden_extensions || '',
      hide_files: !!options.hide_files,
      max_depth: options.max_depth || null,
      max_items: options.max_items || null,
      format_type: options.format_type || 'uml',
      detect_sensitive: options.detect_sensitive !== false,
      query_string: options.query_string || '',
      special_files: options.special_files || '',
      special_dirs: options.special_dirs || '',
      special_words: options.special_words || '',
    });

    const handleProcess = (proc) => {
      activeProcess = proc;
      let out = '', err = '';
      proc.stdout.on('data', d => out += d.toString('utf8'));
      proc.stderr.on('data', d => err += d.toString('utf8'));
      proc.on('error', e => { activeProcess = null; reject(e); });
      proc.on('close', (code, signal) => {
        activeProcess = null;
        if (signal === 'SIGTERM' || signal === 'SIGKILL') return reject(new Error('CANCELADO'));
        if (code !== 0) return reject(new Error(err.trim() || 'Erro ao processar'));
        try { resolve(JSON.parse(out)); }
        catch (e) { reject(new Error('Resposta inválida: ' + e.message)); }
      });
      try { proc.stdin.write(payload); proc.stdin.end(); } catch (_) {}
    };

    const standalone = findStandaloneBinary();
    if (standalone) {
      try {
        const proc = spawn(standalone, [], {
          stdio: ['pipe', 'pipe', 'pipe'],
          env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
        });
        handleProcess(proc);
        return;
      } catch (_) { /* fallback */ }
    }

    const scriptPath = findPythonScript();
    if (!scriptPath) {
      return reject(new Error('web_dir_mapper não encontrado (binário ou script Python).'));
    }

    const wrapper = `
import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
sys.path.insert(0, r'${path.dirname(scriptPath).replace(/\\/g, '\\\\')}')
from web_dir_mapper import map_web_api
d = json.loads(sys.stdin.read())
print(map_web_api(
    url=d.get('url',''),
    hidden_extensions=d.get('hidden_extensions','') or '',
    hide_files=bool(d.get('hide_files', False)),
    max_depth=d.get('max_depth'),
    max_items=d.get('max_items'),
    format_type=d.get('format_type','uml') or 'uml',
    detect_sensitive=bool(d.get('detect_sensitive', True)),
    query_string=d.get('query_string','') or '',
    special_files=d.get('special_files','') or '',
    special_dirs=d.get('special_dirs','') or '',
    special_words=d.get('special_words','') or '',
), end='')
`;

    const tryRun = (cmd, fallback) => {
      const proc = spawn(cmd, ['-c', wrapper], {
        env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
        stdio: ['pipe', 'pipe', 'pipe'],
      });
      activeProcess = proc;
      let out = '', err = '';
      proc.stdout.on('data', d => out += d.toString('utf8'));
      proc.stderr.on('data', d => err += d.toString('utf8'));
      proc.on('error', e => {
        if (e.code === 'ENOENT' && fallback) return tryRun(fallback, null);
        activeProcess = null;
        reject(new Error('Python não encontrado. Instale Python 3.8+ ou use a versão com binário embutido.'));
      });
      proc.on('close', (code, signal) => {
        activeProcess = null;
        if (signal === 'SIGTERM' || signal === 'SIGKILL') return reject(new Error('CANCELADO'));
        if (code !== 0) return reject(new Error(err.trim() || 'Erro ao processar'));
        try { resolve(JSON.parse(out)); }
        catch (e) { reject(new Error('Resposta inválida: ' + e.message)); }
      });
      try { proc.stdin.write(payload); proc.stdin.end(); } catch (_) {}
    };

    const first = process.platform === 'win32' ? 'python' : 'python3';
    const second = process.platform === 'win32' ? 'py' : 'python';
    tryRun(first, second);
  });
});

ipcMain.handle('save-file', async (event, { content, extension }) => {
  const filters = [];
  if (extension === 'md') filters.push({ name: 'Markdown', extensions: ['md'] });
  else if (extension === 'json') filters.push({ name: 'JSON', extensions: ['json'] });
  else if (extension === 'txt') filters.push({ name: 'Text', extensions: ['txt'] });
  filters.push({ name: 'Todos os Arquivos', extensions: ['*'] });

  const result = await dialog.showSaveDialog(mainWindow, {
    filters,
    defaultPath: `web_dir_map.${extension}`,
    title: `Salvar como .${extension}`,
  });
  if (!result.canceled && result.filePath) {
    try {
      fs.writeFileSync(result.filePath, content, 'utf-8');
      return { success: true, path: result.filePath };
    } catch (err) { return { success: false, error: err.message }; }
  }
  return { success: false, canceled: true };
});
