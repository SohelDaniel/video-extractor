// API Configuration and Socket.IO setup
import { io } from 'socket.io-client';

export const API_URL = 'http://localhost:5001';
const socket = io(API_URL, {
  autoConnect: false,
  reconnection: true,
  reconnectionDelay: 1000,
  reconnectionAttempts: 5
});

// API helper functions
export const api = {
  // Get device info
  getDeviceInfo: async () => {
    const res = await fetch(`${API_URL}/api/device-info`);
    return res.json();
  },

  // Start processing videos
  processVideos: async (urls, language = 'en', interval = 5, autoGenerateNotes = false) => {
    const res = await fetch(`${API_URL}/api/process`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ urls, language, interval, autoGenerateNotes })
    });
    return res.json();
  },

  // Get all active jobs
  getJobs: async () => {
    const res = await fetch(`${API_URL}/api/jobs`);
    return res.json();
  },

  // Get specific job
  getJob: async (videoId) => {
    const res = await fetch(`${API_URL}/api/job/${videoId}`);
    return res.json();
  },

  // Get history
  getHistory: async () => {
    const res = await fetch(`${API_URL}/api/history`);
    return res.json();
  },

  // Get result with segments
  getResult: async (videoId) => {
    const res = await fetch(`${API_URL}/api/result/${videoId}`);
    return res.json();
  },

  // Get file URL
  getFileUrl: (videoId, filename) => {
    return `${API_URL}/api/files/${videoId}/${filename}`;
  },

  // Get video URL with cache-busting to avoid stale Electron cache
  getVideoUrl: (videoId, filename) => {
    return `${API_URL}/api/files/${videoId}/${filename}?v=${Date.now()}`;
  },

  // Generate lecture notes
  generateNotes: async (videoId, languages = ['en', 'he'], noteType = 'full', customPrompt = null) => {
    try {
      const body = { languages, note_type: noteType };
      if (noteType === 'custom' && customPrompt) {
        body.custom_prompt = customPrompt;
      }
      const res = await fetch(`${API_URL}/api/generate-notes/${videoId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      return await res.json();
    } catch (error) {
      console.error('[API] generateNotes error:', error);
      throw error;
    }
  },

  // Get notes information
  getNotes: async (videoId) => {
    const res = await fetch(`${API_URL}/api/notes/${videoId}`);
    return res.json();
  },

  // Delete a single note
  deleteNote: async (noteId) => {
    const res = await fetch(`${API_URL}/api/note/${noteId}`, {
      method: 'DELETE'
    });
    return res.json();
  },

  // Translate transcript segments
  translateTranscript: async (videoId, language) => {
    const res = await fetch(`${API_URL}/api/translate/${videoId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ language })
    });
    return res.json();
  },

  // Get available cached translations
  getTranslations: async (videoId) => {
    const res = await fetch(`${API_URL}/api/translations/${videoId}`);
    return res.json();
  },

  // Upload PDF
  uploadPdf: async (file, title, language) => {
    const formData = new FormData();
    formData.append('pdf', file);
    formData.append('title', title);
    formData.append('language', language);
    const res = await fetch(`${API_URL}/api/upload-pdf`, {
      method: 'POST',
      body: formData
    });
    return res.json();
  },

  // Delete video
  deleteVideo: async (videoId) => {
    const res = await fetch(`${API_URL}/api/video/${videoId}`, {
      method: 'DELETE'
    });
    return res.json();
  }
};

// Socket.IO event handlers
export const socketManager = {
  connect: () => {
    if (!socket.connected) {
      socket.connect();
    }
  },

  disconnect: () => {
    if (socket.connected) {
      socket.disconnect();
    }
  },

  onJobUpdate: (callback) => {
    socket.on('job_update', callback);
  },

  onJobStarted: (callback) => {
    socket.on('job_started', callback);
  },

  onJobCompleted: (callback) => {
    socket.on('job_completed', callback);
  },

  onJobFailed: (callback) => {
    socket.on('job_failed', callback);
  },

  offJobUpdate: (callback) => {
    socket.off('job_update', callback);
  },

  offJobStarted: (callback) => {
    socket.off('job_started', callback);
  },

  offJobCompleted: (callback) => {
    socket.off('job_completed', callback);
  },

  offJobFailed: (callback) => {
    socket.off('job_failed', callback);
  },

  onNotesProgress: (callback) => {
    socket.on('notes_progress', callback);
  },

  offNotesProgress: (callback) => {
    socket.off('notes_progress', callback);
  },

  onNotesCompleted: (callback) => {
    socket.on('notes_completed', callback);
  },

  offNotesCompleted: (callback) => {
    socket.off('notes_completed', callback);
  }
};

export default socket;