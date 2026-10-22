'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { useRouter, useParams } from 'next/navigation';
import dynamic from 'next/dynamic';
import { api, socketManager } from '@/lib/api';

const PdfViewer = dynamic(() => import('@/components/PdfViewer'), { ssr: false });
const GenerateNotesModal = dynamic(() => import('@/components/GenerateNotesModal'), { ssr: false });

const LANGUAGES = [
  'Original', 'Spanish', 'French', 'German', 'Arabic', 'Russian',
  'Chinese (Simplified)', 'Japanese', 'Korean', 'Portuguese',
  'Italian', 'Hindi', 'Turkish', 'Hebrew'
];

export default function ResultPage() {
  const router = useRouter();
  const params = useParams();
  const videoId = params.id;

  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selectedSegment, setSelectedSegment] = useState(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [isGeneratingNotes, setIsGeneratingNotes] = useState(false);
  const [notesProgress, setNotesProgress] = useState({ stage: '', message: '', progress: 0 });
  const [activeTab, setActiveTab] = useState('transcript');

  // Multi-note state
  const [notesList, setNotesList] = useState([]);
  const [notesEnabled, setNotesEnabled] = useState(false);
  const [viewingNoteId, setViewingNoteId] = useState(null);
  const [showGenerateModal, setShowGenerateModal] = useState(false);

  // Fullscreen state: null | 'video' | 'pdf'
  const [fullscreenPanel, setFullscreenPanel] = useState(null);

  // Translation state
  const [selectedLanguage, setSelectedLanguage] = useState('Original');
  const [translatedSegments, setTranslatedSegments] = useState({});
  const [isTranslating, setIsTranslating] = useState(false);
  const [availableTranslations, setAvailableTranslations] = useState([]);

  const [videoError, setVideoError] = useState(null);

  const videoRef = useRef(null);
  const splitContainerRef = useRef(null);
  const [splitPercent, setSplitPercent] = useState(50);
  const [isDragging, setIsDragging] = useState(false);

  // Detect source type
  const sourceType = result?.video?.source_type || 'video';
  const isPdf = sourceType === 'pdf';

  useEffect(() => {
    loadResult();
  }, [videoId]);

  const loadResult = async () => {
    setLoading(true);
    try {
      const data = await api.getResult(videoId);
      setResult(data);

      // For PDFs, default to Notes tab; for videos, select first segment
      if (data.video?.source_type === 'pdf') {
        setActiveTab('pdfs');
      } else {
        if (data.segments && data.segments.length > 0) {
          setSelectedSegment(data.segments[0]);
        }
      }

      // Load notes information
      const notesData = await api.getNotes(videoId);
      setNotesList(notesData.notes || []);
      setNotesEnabled(notesData.notes_enabled || false);
    } catch (error) {
      console.error('Error loading result:', error);
    } finally {
      setLoading(false);
    }
  };

  const refreshNotes = async () => {
    try {
      const notesData = await api.getNotes(videoId);
      setNotesList(notesData.notes || []);
      setNotesEnabled(notesData.notes_enabled || false);
    } catch (error) {
      console.error('Error refreshing notes:', error);
    }
  };

  // Load available translations on mount (video only)
  useEffect(() => {
    if (videoId && !isPdf) {
      api.getTranslations(videoId).then(data => {
        if (data.translations) {
          setAvailableTranslations(data.translations);
        }
      }).catch(() => {});
    }
  }, [videoId, isPdf]);

  useEffect(() => {
    // Connect to Socket.IO for notes progress
    const { socketManager } = require('@/lib/api');
    socketManager.connect();

    const handleNotesProgress = (data) => {
      if (data.video_id === videoId) {
        setNotesProgress({
          stage: data.stage,
          message: data.message,
          progress: data.progress || 0
        });
        if (data.stage === 'failed') {
          setIsGeneratingNotes(false);
        }
      }
    };

    const handleNotesCompleted = (data) => {
      if (data.video_id === videoId) {
        setIsGeneratingNotes(false);
        if (data.failed) {
          setNotesProgress({ stage: 'failed', message: 'Notes generation failed', progress: 0 });
        } else {
          setNotesProgress({ stage: 'done', message: 'Notes generated successfully!', progress: 100 });
          refreshNotes();
        }
      }
    };

    socketManager.onNotesProgress(handleNotesProgress);
    socketManager.onNotesCompleted(handleNotesCompleted);

    return () => {
      socketManager.offNotesProgress(handleNotesProgress);
      socketManager.offNotesCompleted(handleNotesCompleted);
    };
  }, [videoId]);

  // BroadcastChannel listener: receive seek commands from other tabs (video only)
  useEffect(() => {
    if (isPdf) return;
    const channel = new BroadcastChannel('video-seek');
    channel.onmessage = (event) => {
      if (event.data.videoId === videoId && videoRef.current) {
        videoRef.current.currentTime = event.data.seekTo;
        videoRef.current.play().catch(() => {});
        window.focus();
        channel.postMessage({ ack: true });
      }
    };
    return () => channel.close();
  }, [videoId, isPdf]);

  // Timestamp seek: if opened with ?t= param, signal existing tab or seek locally (video only)
  useEffect(() => {
    if (isPdf) return;
    const params = new URLSearchParams(window.location.search);
    const t = params.get('t');
    if (!t) return;

    const channel = new BroadcastChannel('video-seek');
    channel.postMessage({ videoId, seekTo: parseFloat(t) });
    const timer = setTimeout(() => {
      if (videoRef.current) {
        videoRef.current.currentTime = parseFloat(t);
        videoRef.current.play().catch(() => {});
      }
    }, 500);
    channel.onmessage = (event) => {
      if (event.data.ack) {
        clearTimeout(timer);
        window.close();
      }
    };
    return () => { clearTimeout(timer); channel.close(); };
  }, [videoId, isPdf]);

  const handleGenerateNotes = async ({ languages, noteType, customPrompt }) => {
    setShowGenerateModal(false);
    setIsGeneratingNotes(true);
    setNotesProgress({ stage: 'starting', message: 'Initiating notes generation...', progress: 0 });
    setActiveTab('pdfs');

    try {
      const response = await api.generateNotes(videoId, languages, noteType, customPrompt);

      if (!response.success) {
        alert(response.error || 'Failed to start notes generation');
        setIsGeneratingNotes(false);
      }
    } catch (error) {
      console.error('Exception in handleGenerateNotes:', error);
      alert('Failed to start notes generation');
      setIsGeneratingNotes(false);
    }
  };

  const handleDeleteNote = async (noteId) => {
    if (!confirm('Delete this note? The PDF file will be permanently removed.')) return;
    try {
      const res = await api.deleteNote(noteId);
      if (res.success) {
        if (viewingNoteId === noteId) setViewingNoteId(null);
        refreshNotes();
      } else {
        alert(res.error || 'Failed to delete note');
      }
    } catch (error) {
      alert('Failed to delete note');
    }
  };

  const handleSegmentClick = (segment) => {
    setSelectedSegment(segment);
    if (videoRef.current) {
      videoRef.current.currentTime = segment.start_time;
    }
  };

  const handleTimestampClick = useCallback((seconds) => {
    if (isPdf) return; // No video to seek for PDF sources
    if (videoRef.current) {
      videoRef.current.currentTime = seconds;
      videoRef.current.play().catch(() => {});
      // If PDF is fullscreen, exit so user can see the video
      setFullscreenPanel(null);
      videoRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }, [isPdf]);

  // Resizable split divider logic
  const startDragging = useCallback((e) => {
    e.preventDefault();
    setIsDragging(true);
    document.body.classList.add('resizing');
  }, []);

  useEffect(() => {
    if (!isDragging) return;

    const handleMouseMove = (e) => {
      if (!splitContainerRef.current) return;
      const rect = splitContainerRef.current.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const percent = (x / rect.width) * 100;
      setSplitPercent(Math.min(70, Math.max(30, percent)));
    };

    const handleMouseUp = () => {
      setIsDragging(false);
      document.body.classList.remove('resizing');
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDragging]);

  const handleLanguageChange = async (language) => {
    setSelectedLanguage(language);
    if (language === 'Original') return;

    // Already loaded in state
    if (translatedSegments[language]) return;

    // Fetch (may be cached on backend or need translation)
    setIsTranslating(true);
    try {
      const data = await api.translateTranscript(videoId, language);
      if (data.success && data.segments) {
        setTranslatedSegments(prev => ({ ...prev, [language]: data.segments }));
        // Update available translations list
        if (!availableTranslations.includes(language)) {
          setAvailableTranslations(prev => [...prev, language]);
        }
      } else {
        alert(data.error || 'Translation failed');
        setSelectedLanguage('Original');
      }
    } catch (error) {
      console.error('Translation error:', error);
      alert('Translation failed');
      setSelectedLanguage('Original');
    } finally {
      setIsTranslating(false);
    }
  };

  const formatTime = (seconds) => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  const downloadTranscript = (format) => {
    if (!result) return;

    let content = '';
    let filename = '';
    let mimeType = '';

    switch (format) {
      case 'txt':
        content = result.segments.map(seg =>
          `[${formatTime(seg.start_time)} -> ${formatTime(seg.end_time)}] ${seg.text}`
        ).join('\n');
        filename = `transcript_${videoId}.txt`;
        mimeType = 'text/plain';
        break;

      case 'srt':
        content = result.segments.map((seg, idx) => {
          const start = formatTimeSRT(seg.start_time);
          const end = formatTimeSRT(seg.end_time);
          return `${idx + 1}\n${start} --> ${end}\n${seg.text.trim()}\n`;
        }).join('\n');
        filename = `subtitles_${videoId}.srt`;
        mimeType = 'text/plain';
        break;

      case 'json':
        content = JSON.stringify(result, null, 2);
        filename = `transcript_${videoId}.json`;
        mimeType = 'application/json';
        break;
    }

    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  };

  const formatTimeSRT = (seconds) => {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    const ms = Math.floor((seconds % 1) * 1000);
    return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')},${ms.toString().padStart(3, '0')}`;
  };

  // Determine which segments to display
  const displaySegments = selectedLanguage !== 'Original' && translatedSegments[selectedLanguage]
    ? translatedSegments[selectedLanguage]
    : result?.segments || [];

  const filteredSegments = displaySegments.filter(seg =>
    seg.text.toLowerCase().includes(searchQuery.toLowerCase())
  );

  // Find the currently viewed note object
  const viewingNote = viewingNoteId ? notesList.find(n => n.id === viewingNoteId) : null;

  // Fullscreen helpers
  const showLeftPanel = fullscreenPanel !== 'pdf';
  const showRightPanel = fullscreenPanel !== 'video';
  const showDivider = !fullscreenPanel;

  if (loading) {
    return (
      <div className="min-h-screen bg-black flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin text-6xl mb-4">&#8987;</div>
          <p className="text-gray-400 text-lg">Loading result...</p>
        </div>
      </div>
    );
  }

  if (!result || !result.video) {
    return (
      <div className="min-h-screen bg-black flex items-center justify-center">
        <div className="text-center">
          <div className="text-6xl mb-4">&#10060;</div>
          <h2 className="text-2xl font-bold mb-2">Result Not Found</h2>
          <p className="text-gray-400 mb-6">This transcription doesn't exist or failed</p>
          <button
            onClick={() => router.push('/library')}
            className="px-6 py-3 bg-gradient-to-r from-purple-600 to-purple-800 hover:from-purple-500 hover:to-purple-700 rounded-lg font-bold transition-all"
          >
            Back to Library
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-black">
      {/* Navigation */}
      <nav className="border-b border-gray-900">
        <div className="max-w-7xl mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <span className="text-3xl">&#127916;</span>
              <h1 className="text-2xl font-bold gradient-text">Transcriber Pro</h1>
            </div>
            <div className="flex items-center gap-4">
              <button
                onClick={() => router.push('/')}
                className="px-4 py-2 bg-gray-900 hover:bg-gray-800 rounded-lg border border-gray-800 transition-colors text-sm"
              >
                New Upload
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

      {/* Content */}
      <div className="max-w-7xl mx-auto px-6 py-8">
        {/* Header */}
        <div className="mb-6">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-3">
              {isPdf && (
                <span className="px-2 py-1 bg-red-500/20 text-red-400 text-xs font-bold rounded uppercase">PDF</span>
              )}
              <h2 className="text-3xl font-bold">{result.video.title || (isPdf ? 'Untitled Document' : 'Untitled Video')}</h2>
            </div>
            <div className="flex gap-3">
              {isPdf ? (
                <a
                  href={api.getFileUrl(videoId, 'source.pdf')}
                  download
                  className="px-4 py-2 bg-gray-900 hover:bg-gray-800 rounded-lg border border-gray-800 transition-colors text-sm font-bold"
                >
                  Download Source PDF
                </a>
              ) : (
                <>
                  <button
                    onClick={() => downloadTranscript('txt')}
                    className="px-4 py-2 bg-gray-900 hover:bg-gray-800 rounded-lg border border-gray-800 transition-colors text-sm font-bold"
                  >
                    Download TXT
                  </button>
                  <button
                    onClick={() => downloadTranscript('srt')}
                    className="px-4 py-2 bg-gray-900 hover:bg-gray-800 rounded-lg border border-gray-800 transition-colors text-sm font-bold"
                  >
                    Download SRT
                  </button>
                  <button
                    onClick={() => downloadTranscript('json')}
                    className="px-4 py-2 bg-gray-900 hover:bg-gray-800 rounded-lg border border-gray-800 transition-colors text-sm font-bold"
                  >
                    Download JSON
                  </button>
                </>
              )}
            </div>
          </div>

          {/* Stats */}
          {isPdf ? (
            <div className="grid grid-cols-2 gap-4">
              <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 text-center">
                <div className="text-3xl font-bold text-purple-400">PDF</div>
                <div className="text-sm text-gray-400 uppercase mt-1">Source</div>
              </div>
              <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 text-center">
                <div className="text-3xl font-bold text-purple-400">{result.video.language || 'N/A'}</div>
                <div className="text-sm text-gray-400 uppercase mt-1">Language</div>
              </div>
            </div>
          ) : (
            <div className="grid grid-cols-4 gap-4">
              <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 text-center">
                <div className="text-3xl font-bold text-purple-400">{result.segments?.length || 0}</div>
                <div className="text-sm text-gray-400 uppercase mt-1">Segments</div>
              </div>
              <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 text-center">
                <div className="text-3xl font-bold text-purple-400">{result.video.frame_count || 0}</div>
                <div className="text-sm text-gray-400 uppercase mt-1">Frames</div>
              </div>
              <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 text-center">
                <div className="text-3xl font-bold text-purple-400">
                  {result.video.duration ? `${result.video.duration.toFixed(1)}s` : 'N/A'}
                </div>
                <div className="text-sm text-gray-400 uppercase mt-1">Duration</div>
              </div>
              <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 text-center">
                <div className="text-3xl font-bold text-purple-400">{result.video.language || 'N/A'}</div>
                <div className="text-sm text-gray-400 uppercase mt-1">Language</div>
              </div>
            </div>
          )}
        </div>

        {/* Main Content - Split Screen */}
        <div ref={splitContainerRef} className="flex" style={{ minHeight: '70vh' }}>
          {/* Left Panel: Video Player OR Source PDF Viewer */}
          {showLeftPanel && (
            <div style={{ width: fullscreenPanel === 'video' ? '100%' : `${splitPercent}%` }} className="flex-shrink-0">
              <div className="bg-gray-900 border border-gray-800 rounded-lg p-6 sticky top-6">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-lg font-bold">{isPdf ? 'Source PDF' : 'Video Player'}</h3>
                  <button
                    onClick={() => setFullscreenPanel(fullscreenPanel === 'video' ? null : 'video')}
                    className="px-2 py-1 bg-gray-800 hover:bg-gray-700 rounded text-xs transition-all"
                    title={fullscreenPanel === 'video' ? 'Exit Fullscreen' : 'Fullscreen'}
                  >
                    {fullscreenPanel === 'video' ? 'Exit Fullscreen' : 'Fullscreen'}
                  </button>
                </div>
                {isPdf ? (
                  <PdfViewer
                    pdfUrl={api.getFileUrl(videoId, 'source.pdf')}
                    title="Source PDF"
                  />
                ) : (
                  <>
                    <video
                      ref={videoRef}
                      controls
                      preload="metadata"
                      className="w-full rounded-lg bg-black"
                      onError={(e) => {
                        const code = e.target.error?.code;
                        const msg = e.target.error?.message || 'Unknown error';
                        const errorMap = { 1: 'MEDIA_ERR_ABORTED', 2: 'MEDIA_ERR_NETWORK', 3: 'MEDIA_ERR_DECODE', 4: 'MEDIA_ERR_SRC_NOT_SUPPORTED' };
                        setVideoError(`${errorMap[code] || 'MEDIA_ERR_UNKNOWN'}: ${msg}`);
                        console.error('[Video] Error:', errorMap[code], msg);
                      }}
                    >
                      <source
                        src={api.getVideoUrl(videoId, 'video.mp4')}
                        type="video/mp4"
                        onError={() => {
                          setVideoError('Failed to load video source');
                          console.error('[Video] Source failed to load');
                        }}
                      />
                      Your browser does not support the video tag.
                    </video>
                    {videoError && (
                      <div className="mt-2 p-3 bg-red-900/50 border border-red-700 rounded-lg text-red-200 text-sm">
                        <span>Video playback error: {videoError}</span>
                        <button
                          className="ml-3 px-2 py-1 bg-red-700 hover:bg-red-600 rounded text-xs text-white transition-all"
                          onClick={() => {
                            setVideoError(null);
                            if (videoRef.current) {
                              videoRef.current.src = api.getVideoUrl(videoId, 'video.mp4');
                              videoRef.current.load();
                            }
                          }}
                        >
                          Retry
                        </button>
                      </div>
                    )}
                  </>
                )}
              </div>
            </div>
          )}

          {/* Divider */}
          {showDivider && (
            <div
              onMouseDown={startDragging}
              className="w-1.5 bg-gray-800 hover:bg-purple-500 cursor-col-resize flex-shrink-0 transition-colors"
            />
          )}

          {/* Right: Tabbed Panel */}
          {showRightPanel && (
            <div style={{ width: fullscreenPanel === 'pdf' ? '100%' : `${100 - splitPercent}%` }} className="flex-shrink-0 overflow-hidden">
              <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden sticky top-6">
                {/* Tab Bar */}
                <div className="flex border-b border-gray-800">
                  {!isPdf && (
                    <button
                      onClick={() => setActiveTab('transcript')}
                      className={`tab-button flex-1 py-3 ${activeTab === 'transcript' ? 'active' : ''}`}
                    >
                      Transcript
                    </button>
                  )}
                  <button
                    onClick={() => setActiveTab('pdfs')}
                    className={`tab-button flex-1 py-3 ${activeTab === 'pdfs' ? 'active' : ''}`}
                  >
                    Notes
                  </button>
                  {fullscreenPanel === 'pdf' && (
                    <button
                      onClick={() => setFullscreenPanel(null)}
                      className="px-3 py-2 text-xs text-purple-400 hover:text-purple-300 font-bold transition-colors"
                    >
                      Exit Fullscreen
                    </button>
                  )}
                </div>

                {/* Tab Content */}
                <div className="p-4">
                  {/* Transcript Tab (video only) */}
                  {activeTab === 'transcript' && !isPdf && (
                    <div>
                      {/* Language Dropdown */}
                      <div className="mb-3">
                        <select
                          value={selectedLanguage}
                          onChange={(e) => handleLanguageChange(e.target.value)}
                          disabled={isTranslating}
                          className="w-full px-3 py-2 bg-black border border-gray-800 rounded-lg text-sm focus:border-purple-500 focus:ring-2 focus:ring-purple-500/20 outline-none transition-all disabled:opacity-50"
                        >
                          {LANGUAGES.map(lang => (
                            <option key={lang} value={lang}>
                              {lang}{availableTranslations.includes(lang) ? ' (cached)' : ''}
                            </option>
                          ))}
                        </select>
                        {isTranslating && (
                          <div className="mt-2 text-xs text-purple-400 flex items-center gap-2">
                            <span className="animate-spin inline-block">&#9697;</span>
                            Translating...
                          </div>
                        )}
                      </div>

                      {/* Search */}
                      <input
                        type="text"
                        placeholder="Search transcription..."
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        className="w-full px-4 py-2 bg-black border border-gray-800 rounded-lg mb-3 focus:border-purple-500 focus:ring-2 focus:ring-purple-500/20 outline-none transition-all text-sm"
                      />

                      <div className="flex items-center justify-between mb-2">
                        <span className="text-sm text-gray-400">{filteredSegments.length} segments</span>
                        {selectedLanguage !== 'Original' && (
                          <span className="text-xs text-purple-400 bg-purple-400/10 px-2 py-1 rounded">
                            {selectedLanguage}
                          </span>
                        )}
                      </div>

                      {/* Segments */}
                      <div className="space-y-2 max-h-[500px] overflow-y-auto">
                        {filteredSegments.map((segment, idx) => (
                          <div
                            key={idx}
                            onClick={() => handleSegmentClick(segment)}
                            className={`p-3 rounded-lg cursor-pointer transition-all ${
                              selectedSegment?.start_time === segment.start_time
                                ? 'bg-purple-600 border border-purple-500'
                                : 'bg-black border border-gray-800 hover:border-gray-700'
                            }`}
                          >
                            <div className="flex items-center justify-between mb-2">
                              <span className="text-xs font-mono font-bold text-purple-400">
                                {formatTime(segment.start_time)} &rarr; {formatTime(segment.end_time)}
                              </span>
                              <span className="text-xs text-gray-500">#{idx + 1}</span>
                            </div>
                            <p className="text-sm leading-relaxed line-clamp-2">{segment.text}</p>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Notes Tab */}
                  {activeTab === 'pdfs' && (
                    <div>
                      {/* Header with Generate button */}
                      <div className="flex items-center justify-between mb-4">
                        <h3 className="text-lg font-bold">AI Notes</h3>
                        <div className="flex items-center gap-2">
                          {fullscreenPanel !== 'pdf' && viewingNoteId && (
                            <button
                              onClick={() => setFullscreenPanel('pdf')}
                              className="px-2 py-1 bg-gray-800 hover:bg-gray-700 rounded text-xs transition-all"
                              title="Fullscreen PDF"
                            >
                              Fullscreen
                            </button>
                          )}
                          {notesEnabled && (
                            <button
                              onClick={() => setShowGenerateModal(true)}
                              disabled={isGeneratingNotes}
                              className="px-3 py-1.5 bg-gradient-to-r from-purple-600 to-purple-800 hover:from-purple-500 hover:to-purple-700 disabled:opacity-50 rounded-lg text-xs font-bold transition-all"
                            >
                              + Generate
                            </button>
                          )}
                        </div>
                      </div>

                      {/* Progress bar when generating */}
                      {isGeneratingNotes && (
                        <div className="mb-4">
                          <div className="flex justify-between text-sm mb-2">
                            <span className="text-gray-400">{notesProgress.stage || 'Preparing'}</span>
                            <span className="text-yellow-400 font-bold">{notesProgress.progress || 0}%</span>
                          </div>
                          <div className="h-3 bg-black rounded-full overflow-hidden">
                            <div
                              className="h-full processing-bg"
                              style={{ width: `${notesProgress.progress || 0}%` }}
                            />
                          </div>
                          <div className="bg-black border border-gray-800 rounded-lg p-3 mt-2">
                            <div className="text-sm text-yellow-400 font-mono">
                              {notesProgress.message || 'Starting...'}
                            </div>
                            <div className="text-xs text-gray-500 mt-1">
                              This may take 30-90 seconds...
                            </div>
                          </div>
                        </div>
                      )}

                      {/* Failure message */}
                      {!isGeneratingNotes && notesProgress.stage === 'failed' && (
                        <div className="mb-4 p-3 bg-red-900/20 border border-red-800 rounded-lg">
                          <div className="text-sm text-red-400 font-medium">Generation failed</div>
                          <div className="text-xs text-red-300/70 mt-1">{notesProgress.message}</div>
                        </div>
                      )}

                      {/* Notes list */}
                      {notesList.length > 0 ? (
                        <div className="space-y-2 max-h-[250px] overflow-y-auto mb-4">
                          {notesList.map((note) => (
                            <div
                              key={note.id}
                              className={`p-3 rounded-lg border transition-all ${
                                viewingNoteId === note.id
                                  ? 'border-purple-500 bg-purple-500/10'
                                  : 'border-gray-800 bg-black hover:border-gray-700'
                              }`}
                            >
                              <div className="flex items-center justify-between mb-1">
                                <span className="text-sm font-medium truncate flex-1 mr-2">{note.display_name}</span>
                                <span className="text-xs text-gray-500 flex-shrink-0">
                                  {note.created_at ? new Date(note.created_at).toLocaleDateString() : ''}
                                </span>
                              </div>
                              <div className="flex items-center gap-2 mt-2">
                                <button
                                  onClick={() => setViewingNoteId(viewingNoteId === note.id ? null : note.id)}
                                  className={`px-2.5 py-1 rounded text-xs font-bold transition-all ${
                                    viewingNoteId === note.id
                                      ? 'bg-purple-600 hover:bg-purple-500'
                                      : 'bg-gray-800 hover:bg-gray-700'
                                  }`}
                                >
                                  {viewingNoteId === note.id ? 'Close' : 'View'}
                                </button>
                                <a
                                  href={api.getFileUrl(videoId, note.filename)}
                                  download
                                  className="px-2.5 py-1 bg-blue-600 hover:bg-blue-500 rounded text-xs font-bold transition-all"
                                >
                                  Download
                                </a>
                                <button
                                  onClick={() => handleDeleteNote(note.id)}
                                  className="px-2.5 py-1 bg-red-900/50 hover:bg-red-800 rounded text-xs font-bold transition-all text-red-300"
                                >
                                  Delete
                                </button>
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : !isGeneratingNotes && notesEnabled ? (
                        <div className="text-center py-6">
                          <p className="text-gray-400 mb-4 text-sm">
                            No notes generated yet. Click "+ Generate" to create AI notes.
                          </p>
                        </div>
                      ) : !notesEnabled && !isGeneratingNotes ? (
                        <div className="text-center py-6">
                          <h3 className="text-lg font-bold mb-2">Notes Generation Disabled</h3>
                          <p className="text-gray-400 text-sm">
                            Set API keys on the backend to enable AI notes generation.
                          </p>
                        </div>
                      ) : null}

                      {/* Inline PDF Viewer */}
                      {viewingNote && (
                        <div className="mt-2">
                          <PdfViewer
                            pdfUrl={api.getFileUrl(videoId, viewingNote.filename)}
                            title={viewingNote.display_name}
                            onTimestampClick={isPdf ? undefined : handleTimestampClick}
                          />
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>

      </div>

      {/* Generate Notes Modal */}
      <GenerateNotesModal
        isOpen={showGenerateModal}
        onClose={() => setShowGenerateModal(false)}
        onGenerate={handleGenerateNotes}
        isGenerating={isGeneratingNotes}
      />
    </div>
  );
}
