'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { api, API_URL } from '@/lib/api';

export default function Home() {
  const router = useRouter();
  const [deviceInfo, setDeviceInfo] = useState(null);
  const [uploadMode, setUploadMode] = useState('video'); // 'video' | 'pdf'
  const [selectedFile, setSelectedFile] = useState(null);
  const [title, setTitle] = useState('');
  const [language, setLanguage] = useState('en');
  const [interval, setInterval] = useState(5);
  const [autoGenerateNotes, setAutoGenerateNotes] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    api.getDeviceInfo().then(setDeviceInfo);
  }, []);

  const handleFileChange = (e) => {
    const file = e.target.files[0];
    if (file) {
      if (uploadMode === 'video') {
        if (!file.type.startsWith('video/')) {
          alert('Please select a video file');
          e.target.value = '';
          return;
        }
      } else {
        if (file.type !== 'application/pdf' && !file.name.toLowerCase().endsWith('.pdf')) {
          alert('Please select a PDF file');
          e.target.value = '';
          return;
        }
        if (file.size > 30 * 1024 * 1024) {
          alert('PDF must be under 30MB');
          e.target.value = '';
          return;
        }
      }
      setSelectedFile(file);
      // Auto-fill title from filename (strip extension)
      if (!title) {
        const nameWithoutExt = file.name.replace(/\.[^/.]+$/, '');
        setTitle(nameWithoutExt);
      }
    }
  };

  const handleModeSwitch = (mode) => {
    setUploadMode(mode);
    setSelectedFile(null);
    setTitle('');
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setIsSubmitting(true);

    if (!selectedFile) {
      alert(`Please select a ${uploadMode === 'pdf' ? 'PDF' : 'video'} file`);
      setIsSubmitting(false);
      return;
    }

    try {
      if (uploadMode === 'pdf') {
        const result = await api.uploadPdf(selectedFile, title, language);
        if (result.success) {
          router.push(`/result/${result.video_id}`);
        } else {
          alert(result.error || 'Failed to upload PDF');
        }
      } else {
        const formData = new FormData();
        formData.append('video', selectedFile);
        formData.append('title', title);
        formData.append('language', language);
        formData.append('interval', interval);
        formData.append('autoGenerateNotes', autoGenerateNotes);

        const response = await fetch(`${API_URL}/api/upload`, {
          method: 'POST',
          body: formData,
        });

        const result = await response.json();
        if (result.success) {
          router.push('/processing');
        } else {
          alert(result.error || 'Failed to upload file');
        }
      }
    } catch (error) {
      console.error(`Error uploading ${uploadMode}:`, error);
      alert(`Failed to upload ${uploadMode}`);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-black">
      {/* Navigation */}
      <nav className="border-b border-gray-900">
        <div className="max-w-7xl mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <span className="text-3xl">🎬</span>
              <h1 className="text-2xl font-bold gradient-text">Transcriber Pro</h1>
            </div>
            <div className="flex items-center gap-4">
              {deviceInfo && (
                <div className="flex items-center gap-2 px-4 py-2 bg-gray-900 rounded-lg border border-gray-800">
                  <span className="text-sm">⚡</span>
                  {deviceInfo.device === 'mlx' ? (
                    <>
                      <span className="px-2 py-1 bg-green-500 text-black text-xs font-bold rounded">GPU</span>
                      <span className="text-sm text-gray-400">{deviceInfo.name}</span>
                    </>
                  ) : (
                    <>
                      <span className="px-2 py-1 bg-gray-600 text-white text-xs font-bold rounded">CPU</span>
                      <span className="text-sm text-gray-400">CPU Mode</span>
                    </>
                  )}
                </div>
              )}
              <button
                onClick={() => router.push('/processing')}
                className="px-4 py-2 bg-gray-900 hover:bg-gray-800 rounded-lg border border-gray-800 transition-colors text-sm"
              >
                View Processing
              </button>
              <button
                onClick={() => router.push('/library')}
                className="px-4 py-2 bg-gray-900 hover:bg-gray-800 rounded-lg border border-gray-800 transition-colors text-sm"
              >
                Library
              </button>
            </div>
          </div>
        </div>
      </nav>

      {/* Main Content */}
      <div className="max-w-4xl mx-auto px-6 py-12">
        <div className="text-center mb-12">
          <h2 className="text-4xl font-bold mb-4">AI-Powered Notes & Transcription</h2>
          <p className="text-gray-400 text-lg">Upload videos or PDFs and generate AI-powered notes</p>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="bg-gray-900 border border-gray-800 rounded-lg p-8">
          {/* Upload Mode Toggle */}
          <div className="flex mb-8 bg-black rounded-lg p-1 border border-gray-800">
            <button
              type="button"
              onClick={() => handleModeSwitch('video')}
              className={`flex-1 py-3 rounded-lg font-bold text-sm uppercase tracking-wide transition-all ${
                uploadMode === 'video'
                  ? 'bg-purple-600 text-white'
                  : 'text-gray-400 hover:text-white'
              }`}
            >
              Video Upload
            </button>
            <button
              type="button"
              onClick={() => handleModeSwitch('pdf')}
              className={`flex-1 py-3 rounded-lg font-bold text-sm uppercase tracking-wide transition-all ${
                uploadMode === 'pdf'
                  ? 'bg-purple-600 text-white'
                  : 'text-gray-400 hover:text-white'
              }`}
            >
              PDF Upload
            </button>
          </div>

          <div className="mb-6">
            <label className="block text-sm font-bold uppercase tracking-wide mb-3">
              {uploadMode === 'pdf' ? 'Document Title' : 'Video Title'}
            </label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Enter a title (auto-filled from filename)"
              className="w-full px-4 py-3 bg-black border border-gray-800 rounded-lg focus:border-purple-500 focus:ring-2 focus:ring-purple-500/20 outline-none transition-all"
            />
          </div>

          <div className="mb-6">
            <label className="block text-sm font-bold uppercase tracking-wide mb-3">
              {uploadMode === 'pdf' ? 'Select PDF File' : 'Select Video File'}
            </label>
            <div className="relative">
              <input
                key={uploadMode} // Reset input when mode changes
                type="file"
                accept={uploadMode === 'pdf' ? 'application/pdf,.pdf' : 'video/*'}
                onChange={handleFileChange}
                className="w-full px-4 py-3 bg-black border border-gray-800 rounded-lg focus:border-purple-500 focus:ring-2 focus:ring-purple-500/20 outline-none transition-all file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:bg-purple-600 file:text-white file:cursor-pointer hover:file:bg-purple-500"
                required
              />
            </div>
            {selectedFile && (
              <p className="mt-2 text-sm text-green-400">
                Selected: {selectedFile.name} ({(selectedFile.size / 1024 / 1024).toFixed(2)} MB)
              </p>
            )}
            <p className="mt-2 text-xs text-gray-500">
              {uploadMode === 'pdf'
                ? 'Upload PDF files (textbooks, papers, handwritten notes). Max 30MB.'
                : 'Upload video files directly from your computer (MP4, MKV, AVI, MOV, etc.)'}
            </p>
          </div>

          <div className={`grid ${uploadMode === 'pdf' ? 'grid-cols-1' : 'grid-cols-2'} gap-6 mb-6`}>
            <div>
              <label className="block text-sm font-bold uppercase tracking-wide mb-3">
                Language
              </label>
              <select
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
                className="w-full px-4 py-3 bg-black border border-gray-800 rounded-lg focus:border-purple-500 focus:ring-2 focus:ring-purple-500/20 outline-none transition-all"
              >
                <option value="en">English</option>
                <option value="he">Hebrew (עברית)</option>
                <option value="ar">Arabic</option>
                <option value="es">Spanish</option>
                <option value="fr">French</option>
                <option value="de">German</option>
                <option value="zh">Chinese</option>
              </select>
            </div>

            {uploadMode === 'video' && (
              <div>
                <label className="block text-sm font-bold uppercase tracking-wide mb-3">
                  Frame Interval
                </label>
                <select
                  value={interval}
                  onChange={(e) => setInterval(Number(e.target.value))}
                  className="w-full px-4 py-3 bg-black border border-gray-800 rounded-lg focus:border-purple-500 focus:ring-2 focus:ring-purple-500/20 outline-none transition-all"
                >
                  <option value="0">At each segment</option>
                  <option value="3">Every 3 seconds</option>
                  <option value="5">Every 5 seconds</option>
                  <option value="10">Every 10 seconds</option>
                  <option value="30">Every 30 seconds</option>
                </select>
              </div>
            )}
          </div>

          {uploadMode === 'video' && (
            <div className="mb-6 bg-gray-900 border border-purple-500/20 rounded-lg p-4">
              <label className="flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  checked={autoGenerateNotes}
                  onChange={(e) => setAutoGenerateNotes(e.target.checked)}
                  className="w-5 h-5 text-purple-600 bg-black border-gray-800 rounded focus:ring-purple-500 focus:ring-2"
                />
                <div className="ml-3">
                  <span className="text-sm font-bold text-white">Auto-generate AI Lecture Notes</span>
                  <p className="text-xs text-gray-400 mt-1">
                    Automatically create English + Hebrew PDFs with LaTeX formatting after transcription completes (requires Claude API)
                  </p>
                </div>
              </label>
            </div>
          )}

          <button
            type="submit"
            disabled={isSubmitting}
            className="w-full py-4 bg-gradient-to-r from-purple-600 to-purple-800 hover:from-purple-500 hover:to-purple-700 rounded-lg font-bold uppercase tracking-wide transition-all disabled:opacity-50 disabled:cursor-not-allowed transform hover:scale-[1.02] active:scale-[0.98]"
          >
            {isSubmitting
              ? 'Uploading...'
              : uploadMode === 'pdf'
                ? 'Upload PDF'
                : 'Upload & Transcribe'}
          </button>
        </form>
      </div>
    </div>
  );
}
