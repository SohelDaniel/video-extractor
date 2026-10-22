const { app, BrowserWindow, Menu, Tray, dialog } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const waitOn = require('wait-on');

// Keep references to prevent garbage collection
let mainWindow = null;
let tray = null;
let backendProcess = null;
let isQuitting = false;

const isDev = process.env.NODE_ENV === 'development' || process.env.DEV === 'true';
const BACKEND_PORT = 5001;
const FRONTEND_PORT = 3000;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1000,
    minHeight: 600,
    backgroundColor: '#000000',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      enableRemoteModule: false,
      webSecurity: true
    },
    icon: path.join(__dirname, '../assets/icon.png'), // We'll create this
    show: false // Don't show until ready-to-show
  });

  // Show window when ready (prevents white flash)
  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
  });

  // Load the app
  const startUrl = isDev
    ? `http://localhost:${FRONTEND_PORT}`
    : `file://${path.join(__dirname, '../out/index.html')}`;

  mainWindow.loadURL(startUrl);

  // Open DevTools in development
  if (isDev) {
    mainWindow.webContents.openDevTools();
  }

  // Handle window close (minimize to tray instead of quit)
  mainWindow.on('close', (event) => {
    if (!isQuitting) {
      event.preventDefault();
      mainWindow.hide();
      return false;
    }
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  // Create application menu
  createMenu();
}

function createMenu() {
  const template = [
    {
      label: 'File',
      submenu: [
        {
          label: 'New Transcription',
          accelerator: 'CmdOrCtrl+N',
          click: () => {
            if (mainWindow) {
              mainWindow.webContents.send('navigate', '/');
            }
          }
        },
        { type: 'separator' },
        {
          label: 'Quit',
          accelerator: 'CmdOrCtrl+Q',
          click: () => {
            isQuitting = true;
            app.quit();
          }
        }
      ]
    },
    {
      label: 'View',
      submenu: [
        {
          label: 'Library',
          accelerator: 'CmdOrCtrl+L',
          click: () => {
            if (mainWindow) {
              mainWindow.webContents.send('navigate', '/library');
            }
          }
        },
        {
          label: 'Processing',
          accelerator: 'CmdOrCtrl+P',
          click: () => {
            if (mainWindow) {
              mainWindow.webContents.send('navigate', '/processing');
            }
          }
        },
        { type: 'separator' },
        { role: 'reload' },
        { role: 'forceReload' },
        { role: 'toggleDevTools' }
      ]
    },
    {
      label: 'Window',
      submenu: [
        { role: 'minimize' },
        { role: 'zoom' },
        { type: 'separator' },
        { role: 'close' }
      ]
    },
    {
      label: 'Help',
      submenu: [
        {
          label: 'About',
          click: () => {
            dialog.showMessageBox(mainWindow, {
              type: 'info',
              title: 'Transcriber Pro',
              message: 'Transcriber Pro v1.0.0',
              detail: 'AI-powered video transcription and lecture notes generator'
            });
          }
        }
      ]
    }
  ];

  const menu = Menu.buildFromTemplate(template);
  Menu.setApplicationMenu(menu);
}

function createTray() {
  // We'll create a tray icon later
  const trayIconPath = path.join(__dirname, '../assets/tray-icon.png');

  if (fs.existsSync(trayIconPath)) {
    tray = new Tray(trayIconPath);

    const contextMenu = Menu.buildFromTemplate([
      {
        label: 'Show App',
        click: () => {
          mainWindow.show();
        }
      },
      {
        label: 'Quit',
        click: () => {
          isQuitting = true;
          app.quit();
        }
      }
    ]);

    tray.setToolTip('Transcriber Pro');
    tray.setContextMenu(contextMenu);

    tray.on('click', () => {
      mainWindow.show();
    });
  }
}

async function startBackend() {
  return new Promise((resolve, reject) => {
    console.log('[Electron] Starting Flask backend...');

    // Determine Python path
    let pythonPath;
    let serverPath;

    if (isDev) {
      // Development: Try multiple Python locations
      const possiblePaths = [
        path.join(__dirname, '../backend/venv/bin/python'),       // macOS / Linux venv
        path.join(__dirname, '../backend/venv/Scripts/python.exe'),
        'python',  // System Python
        'python3', // Alternative system Python
        'py',      // Windows Python launcher
      ];

      pythonPath = null;
      for (const pyPath of possiblePaths) {
        if (fs.existsSync(pyPath) || pyPath === 'python' || pyPath === 'python3' || pyPath === 'py') {
          pythonPath = pyPath;
          console.log('[Electron] Using Python from:', pythonPath);
          break;
        }
      }

      serverPath = path.join(__dirname, '../backend/server.py');
    } else {
      // Production: Use bundled Python
      pythonPath = path.join(process.resourcesPath, 'backend/venv/Scripts/python.exe');
      serverPath = path.join(process.resourcesPath, 'backend/server.py');
    }

    // Check if we found Python (only check path if it's a file path, not a command)
    if (!pythonPath) {
      console.error('[Electron] No Python installation found');
      dialog.showErrorBox(
        'Backend Error',
        'Python not found. Please ensure Python is installed and available in PATH.'
      );
      reject(new Error('Python not found'));
      return;
    }

    // Start the backend process
    const env = { ...process.env };
    env.PYTHONUNBUFFERED = '1'; // Disable Python output buffering

    backendProcess = spawn(pythonPath, [serverPath], {
      cwd: path.dirname(serverPath),
      env: env,
      windowsHide: true
    });

    backendProcess.stdout.on('data', (data) => {
      console.log(`[Backend] ${data.toString().trim()}`);
    });

    backendProcess.stderr.on('data', (data) => {
      console.error(`[Backend Error] ${data.toString().trim()}`);
    });

    backendProcess.on('error', (error) => {
      console.error('[Electron] Failed to start backend:', error);
      dialog.showErrorBox('Backend Error', `Failed to start backend: ${error.message}`);
      reject(error);
    });

    backendProcess.on('exit', (code, signal) => {
      console.log(`[Backend] Process exited with code ${code} and signal ${signal}`);
      backendProcess = null;
    });

    // Wait for backend to be ready
    console.log('[Electron] Waiting for backend to start...');
    waitOn({
      resources: [`http://localhost:${BACKEND_PORT}/api/device-info`],
      timeout: 30000,
      interval: 1000
    }).then(() => {
      console.log('[Electron] Backend is ready!');
      resolve();
    }).catch((err) => {
      console.error('[Electron] Backend failed to start:', err);
      dialog.showErrorBox('Backend Error', 'Backend server failed to start within 30 seconds.');
      reject(err);
    });
  });
}

function stopBackend() {
  if (backendProcess) {
    console.log('[Electron] Stopping backend process...');
    backendProcess.kill('SIGTERM');

    // Force kill after 5 seconds if still running
    setTimeout(() => {
      if (backendProcess) {
        console.log('[Electron] Force killing backend process...');
        backendProcess.kill('SIGKILL');
      }
    }, 5000);
  }
}

// App lifecycle
app.whenReady().then(async () => {
  try {
    // Start backend first
    await startBackend();

    // Wait for frontend (only in dev mode)
    if (isDev) {
      console.log('[Electron] Waiting for frontend dev server...');
      await waitOn({
        resources: [`http://localhost:${FRONTEND_PORT}`],
        timeout: 60000
      });
      console.log('[Electron] Frontend dev server is ready!');
    }

    // Create window
    createWindow();
    createTray();

  } catch (error) {
    console.error('[Electron] Startup error:', error);
    dialog.showErrorBox('Startup Error', `Failed to start application: ${error.message}`);
    app.quit();
  }
});

app.on('window-all-closed', () => {
  // On macOS, apps stay active until Cmd+Q
  if (process.platform !== 'darwin') {
    isQuitting = true;
    app.quit();
  }
});

app.on('activate', () => {
  if (mainWindow === null) {
    createWindow();
  } else {
    mainWindow.show();
  }
});

app.on('before-quit', () => {
  isQuitting = true;
});

app.on('will-quit', () => {
  stopBackend();
});

// Handle uncaught exceptions
process.on('uncaughtException', (error) => {
  console.error('[Electron] Uncaught exception:', error);
  dialog.showErrorBox('Application Error', `An unexpected error occurred: ${error.message}`);
});
