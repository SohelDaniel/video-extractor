'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { api, socketManager } from '@/lib/api';

export default function ProcessingPage() {
  const router = useRouter();
  const [jobs, setJobs] = useState({});
  const [activeTab, setActiveTab] = useState(null);

  useEffect(() => {
    // Connect to Socket.IO
    socketManager.connect();

    // Load initial jobs
    api.getJobs().then(jobsArray => {
      const jobsMap = {};
      jobsArray.forEach(job => {
        jobsMap[job.video_id] = job;
      });
      setJobs(jobsMap);
      if (Object.keys(jobsMap).length > 0 && !activeTab) {
        setActiveTab(Object.keys(jobsMap)[0]);
      }
    });

    // Socket event handlers
    const handleJobStarted = (data) => {
      setJobs(prev => ({
        ...prev,
        [data.video_id]: {
          video_id: data.video_id,
          url: data.url,
          status: 'processing',
          progress: 0,
          logs: []
        }
      }));
      if (!activeTab) {
        setActiveTab(data.video_id);
      }
    };

    const handleJobUpdate = (data) => {
      setJobs(prev => ({
        ...prev,
        [data.video_id]: {
          ...prev[data.video_id],
          logs: [...(prev[data.video_id]?.logs || []), data.log],
          progress: data.progress !== null ? data.progress : prev[data.video_id]?.progress
        }
      }));
    };

    const handleJobCompleted = (data) => {
      setJobs(prev => ({
        ...prev,
        [data.video_id]: {
          ...prev[data.video_id],
          status: 'completed',
          progress: 100,
          segments: data.segments,
          frames: data.frames,
          duration: data.duration
        }
      }));
    };

    const handleJobFailed = (data) => {
      setJobs(prev => ({
        ...prev,
        [data.video_id]: {
          ...prev[data.video_id],
          status: 'failed',
          error: data.error
        }
      }));
    };

    socketManager.onJobStarted(handleJobStarted);
    socketManager.onJobUpdate(handleJobUpdate);
    socketManager.onJobCompleted(handleJobCompleted);
    socketManager.onJobFailed(handleJobFailed);

    return () => {
      socketManager.offJobStarted(handleJobStarted);
      socketManager.offJobUpdate(handleJobUpdate);
      socketManager.offJobCompleted(handleJobCompleted);
      socketManager.offJobFailed(handleJobFailed);
    };
  }, [activeTab]);

  const jobsList = Object.values(jobs);
  const activeJob = activeTab ? jobs[activeTab] : null;

  const getStatusColor = (status) => {
    switch (status) {
      case 'processing': return 'text-yellow-400 bg-yellow-400/10 border-yellow-400/20';
      case 'completed': return 'text-green-400 bg-green-400/10 border-green-400/20';
      case 'failed': return 'text-red-400 bg-red-400/10 border-red-400/20';
      default: return 'text-gray-400 bg-gray-400/10 border-gray-400/20';
    }
  };

  const getStatusIcon = (status) => {
    switch (status) {
      case 'processing': return '⏳';
      case 'completed': return '✅';
      case 'failed': return '❌';
      default: return '⏸️';
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
                New Transcription
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
        <div className="mb-6">
          <h2 className="text-3xl font-bold mb-2">Active Processing</h2>
          <p className="text-gray-400">Monitor your transcription jobs in real-time</p>
        </div>

        {jobsList.length === 0 ? (
          <div className="text-center py-20">
            <div className="text-6xl mb-4">🎬</div>
            <h3 className="text-2xl font-bold mb-2">No Active Jobs</h3>
            <p className="text-gray-400 mb-6">Start a new transcription to see it here</p>
            <button
              onClick={() => router.push('/')}
              className="px-6 py-3 bg-gradient-to-r from-purple-600 to-purple-800 hover:from-purple-500 hover:to-purple-700 rounded-lg font-bold transition-all"
            >
              Start New Transcription
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-12 gap-6">
            {/* Jobs List */}
            <div className="col-span-4 space-y-3">
              {jobsList.map(job => (
                <div
                  key={job.video_id}
                  onClick={() => setActiveTab(job.video_id)}
                  className={`p-4 rounded-lg border cursor-pointer transition-all ${
                    activeTab === job.video_id
                      ? 'bg-purple-500/10 border-purple-500'
                      : 'bg-gray-900 border-gray-800 hover:border-gray-700'
                  }`}
                >
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <span className="text-xl">{getStatusIcon(job.status)}</span>
                      <span className="font-mono text-sm font-bold">
                        {job.video_id?.substring(0, 8)}
                      </span>
                    </div>
                    <span className={`px-2 py-1 rounded text-xs font-bold uppercase border ${getStatusColor(job.status)}`}>
                      {job.status}
                    </span>
                  </div>
                  
                  {job.status === 'processing' && job.progress !== undefined && (
                    <div className="mt-3">
                      <div className="flex justify-between text-xs text-gray-400 mb-1">
                        <span>Progress</span>
                        <span>{job.progress}%</span>
                      </div>
                      <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
                        <div
                          className="h-full processing-bg"
                          style={{ width: `${job.progress}%` }}
                        />
                      </div>
                    </div>
                  )}

                  {job.status === 'completed' && (
                    <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
                      <div className="text-gray-400">
                        <span className="text-green-400">{job.segments || 0}</span> segments
                      </div>
                      <div className="text-gray-400">
                        <span className="text-green-400">{job.frames || 0}</span> frames
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>

            {/* Job Details */}
            <div className="col-span-8">
              {activeJob ? (
                <div className="bg-gray-900 border border-gray-800 rounded-lg">
                  {/* Header */}
                  <div className="p-6 border-b border-gray-800">
                    <div className="flex items-center justify-between mb-4">
                      <h3 className="text-xl font-bold">Job Details</h3>
                      {activeJob.status === 'completed' && (
                        <button
                          onClick={() => router.push(`/result/${activeJob.video_id}`)}
                          className="px-4 py-2 bg-gradient-to-r from-purple-600 to-purple-800 hover:from-purple-500 hover:to-purple-700 rounded-lg font-bold text-sm transition-all"
                        >
                          View Full Result
                        </button>
                      )}
                    </div>
                    <div className="grid grid-cols-2 gap-4 text-sm">
                      <div>
                        <span className="text-gray-400">Video ID:</span>
                        <span className="ml-2 font-mono">{activeJob.video_id}</span>
                      </div>
                      <div>
                        <span className="text-gray-400">Status:</span>
                        <span className={`ml-2 px-2 py-1 rounded text-xs font-bold uppercase border ${getStatusColor(activeJob.status)}`}>
                          {activeJob.status}
                        </span>
                      </div>
                    </div>
                    {activeJob.url && (
                      <div className="mt-3 text-sm">
                        <span className="text-gray-400">URL:</span>
                        <div className="mt-1 px-3 py-2 bg-black rounded border border-gray-800 font-mono text-xs break-all">
                          {activeJob.url}
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Progress */}
                  {activeJob.status === 'processing' && activeJob.progress !== undefined && (
                    <div className="p-6 border-b border-gray-800">
                      <div className="flex justify-between text-sm mb-2">
                        <span className="font-bold">Progress</span>
                        <span className="text-purple-400 font-bold">{activeJob.progress}%</span>
                      </div>
                      <div className="h-3 bg-black rounded-full overflow-hidden">
                        <div
                          className="h-full processing-bg"
                          style={{ width: `${activeJob.progress}%` }}
                        />
                      </div>
                    </div>
                  )}

                  {/* Live Logs */}
                  <div className="p-6">
                    <h4 className="text-sm font-bold uppercase tracking-wide mb-3 text-gray-400">Live Logs</h4>
                    <div className="bg-black border border-gray-800 rounded-lg p-4 h-96 overflow-y-auto font-mono text-xs">
                      {activeJob.logs && activeJob.logs.length > 0 ? (
                        activeJob.logs.map((log, idx) => (
                          <div key={idx} className="py-1 text-gray-300">
                            {log}
                          </div>
                        ))
                      ) : (
                        <div className="text-gray-500">Waiting for logs...</div>
                      )}
                    </div>
                  </div>
                </div>
              ) : (
                <div className="bg-gray-900 border border-gray-800 rounded-lg p-12 text-center">
                  <p className="text-gray-400">Select a job to view details</p>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}