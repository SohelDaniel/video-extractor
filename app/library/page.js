'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { api, API_URL } from '@/lib/api';

export default function Library() {
  const router = useRouter();
  const [videos, setVideos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editingId, setEditingId] = useState(null);
  const [editTitle, setEditTitle] = useState('');

  useEffect(() => {
    loadVideos();
  }, []);

  const loadVideos = async () => {
    try {
      const data = await api.getHistory();
      setVideos(data);
    } catch (error) {
      console.error('Error loading videos:', error);
    } finally {
      setLoading(false);
    }
  };

  const formatDate = (dateStr) => {
    return new Date(dateStr).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  const formatDuration = (seconds) => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  const handleDelete = async (e, videoId, title) => {
    e.stopPropagation(); // Prevent navigation when clicking delete

    if (!confirm(`Delete "${title || 'Untitled Video'}"? This will permanently remove the video and all associated files.`)) {
      return;
    }

    try {
      const result = await api.deleteVideo(videoId);
      if (result.success) {
        // Reload videos after deletion
        loadVideos();
      } else {
        alert(result.error || 'Failed to delete video');
      }
    } catch (error) {
      console.error('Error deleting video:', error);
      alert('Failed to delete video');
    }
  };

  const handleEdit = (e, video) => {
    e.stopPropagation();
    setEditingId(video.video_id);
    setEditTitle(video.title || 'Untitled Video');
  };

  const saveEdit = async (videoId) => {
    if (!editTitle.trim()) return;
    try {
      const response = await fetch(`${API_URL}/api/video/${videoId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: editTitle.trim() }),
      });
      const result = await response.json();
      if (result.success) {
        setEditingId(null);
        loadVideos();
      } else {
        alert(result.error || 'Failed to update title');
      }
    } catch (error) {
      console.error('Error updating title:', error);
      alert('Failed to update title');
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
              <button
                onClick={() => router.push('/')}
                className="px-4 py-2 bg-gray-900 hover:bg-gray-800 rounded-lg border border-gray-800 transition-colors text-sm"
              >
                New Upload
              </button>
              <button
                onClick={() => router.push('/processing')}
                className="px-4 py-2 bg-gray-900 hover:bg-gray-800 rounded-lg border border-gray-800 transition-colors text-sm"
              >
                Processing
              </button>
            </div>
          </div>
        </div>
      </nav>

      {/* Main Content */}
      <div className="max-w-7xl mx-auto px-6 py-12">
        <div className="mb-8">
          <h2 className="text-3xl font-bold mb-2">Library</h2>
          <p className="text-gray-400">Click on any item to view transcription and notes</p>
        </div>

        {loading ? (
          <div className="text-center py-12">
            <div className="inline-block animate-spin rounded-full h-12 w-12 border-b-2 border-purple-500"></div>
            <p className="mt-4 text-gray-400">Loading videos...</p>
          </div>
        ) : videos.length === 0 ? (
          <div className="text-center py-12">
            <p className="text-gray-400 text-lg">No items yet</p>
            <button
              onClick={() => router.push('/')}
              className="mt-4 px-6 py-3 bg-purple-600 hover:bg-purple-500 rounded-lg font-medium transition-colors"
            >
              Upload Your First File
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {videos.map((video) => (
              <div
                key={video.video_id}
                onClick={() => router.push(`/result/${video.video_id}`)}
                className="group bg-gray-900 border border-gray-800 rounded-lg overflow-hidden cursor-pointer hover:border-purple-500 transition-all transform hover:scale-[1.02]"
              >
                {/* Thumbnail */}
                <div className="relative aspect-video bg-gray-800">
                  {video.source_type === 'pdf' ? (
                    <div className="w-full h-full flex flex-col items-center justify-center gap-2">
                      <span className="text-5xl">&#128196;</span>
                      <span className="px-2 py-1 bg-red-500/20 text-red-400 text-xs font-bold rounded uppercase">PDF</span>
                    </div>
                  ) : video.thumbnail ? (
                    <img
                      src={`${API_URL}/api/files/${video.video_id}/${video.thumbnail}`}
                      alt="Video thumbnail"
                      className="w-full h-full object-cover"
                    />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center text-4xl">
                      🎥
                    </div>
                  )}
                  {video.source_type !== 'pdf' && video.duration && (
                    <div className="absolute bottom-2 right-2 px-2 py-1 bg-black/80 rounded text-xs">
                      {formatDuration(video.duration)}
                    </div>
                  )}
                  {/* Edit & Delete buttons */}
                  <button
                    onClick={(e) => handleEdit(e, video)}
                    className="absolute top-2 right-12 p-2 bg-gray-700 hover:bg-gray-600 rounded-lg transition-colors opacity-0 group-hover:opacity-100"
                    title="Edit title"
                  >
                    ✏️
                  </button>
                  <button
                    onClick={(e) => handleDelete(e, video.video_id, video.title)}
                    className="absolute top-2 right-2 p-2 bg-red-600 hover:bg-red-500 rounded-lg transition-colors opacity-0 group-hover:opacity-100"
                    title="Delete video"
                  >
                    🗑️
                  </button>
                </div>

                {/* Info */}
                <div className="p-4">
                  {editingId === video.video_id ? (
                    <div className="flex items-center gap-2 mb-2" onClick={(e) => e.stopPropagation()}>
                      <input
                        type="text"
                        value={editTitle}
                        onChange={(e) => setEditTitle(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') saveEdit(video.video_id);
                          if (e.key === 'Escape') setEditingId(null);
                        }}
                        autoFocus
                        className="flex-1 px-2 py-1 bg-gray-800 border border-gray-700 rounded text-sm focus:outline-none focus:border-purple-500"
                      />
                      <button
                        onClick={(e) => { e.stopPropagation(); saveEdit(video.video_id); }}
                        className="px-2 py-1 bg-purple-600 hover:bg-purple-500 rounded text-xs"
                      >
                        Save
                      </button>
                      <button
                        onClick={(e) => { e.stopPropagation(); setEditingId(null); }}
                        className="px-2 py-1 bg-gray-700 hover:bg-gray-600 rounded text-xs"
                      >
                        Cancel
                      </button>
                    </div>
                  ) : (
                    <h3 className="font-bold text-lg mb-2 truncate">{video.title || 'Untitled Video'}</h3>
                  )}
                  <div className="space-y-1 text-sm text-gray-400">
                    <p>{formatDate(video.created_at)}</p>
                    {video.segment_count && (
                      <p>{video.segment_count} segments</p>
                    )}
                    {video.status && (
                      <span className={`inline-block px-2 py-1 rounded text-xs ${
                        video.status === 'completed' ? 'bg-green-500/20 text-green-400' :
                        video.status === 'processing' ? 'bg-yellow-500/20 text-yellow-400' :
                        'bg-red-500/20 text-red-400'
                      }`}>
                        {video.status}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
