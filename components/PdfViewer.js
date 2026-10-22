'use client';

import { useState, useCallback, useRef, useEffect } from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import 'react-pdf/dist/Page/TextLayer.css';
import 'react-pdf/dist/Page/AnnotationLayer.css';

export default function PdfViewer({ pdfUrl, title = 'PDF Viewer', onTimestampClick }) {
  const [numPages, setNumPages] = useState(null);
  const [scale, setScale] = useState(1.0);
  const [workerReady, setWorkerReady] = useState(false);
  const containerRef = useRef(null);

  useEffect(() => {
    pdfjs.GlobalWorkerOptions.workerSrc = `//unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;
    setWorkerReady(true);
  }, []);

  const onDocumentLoadSuccess = useCallback(({ numPages }) => {
    setNumPages(numPages);
  }, []);

  const handleZoomIn = () => {
    setScale(prev => Math.min(prev + 0.25, 2.0));
  };

  const handleZoomOut = () => {
    setScale(prev => Math.max(prev - 0.25, 0.5));
  };

  const handleOpenNewTab = () => {
    window.open(pdfUrl, '_blank');
  };

  const handleContainerClick = useCallback((e) => {
    // Walk up from click target to find <a> tags
    let el = e.target;
    while (el && el !== containerRef.current) {
      if (el.tagName === 'A' && el.href) {
        try {
          const url = new URL(el.href);
          const t = url.searchParams.get('t');
          if (t !== null && onTimestampClick) {
            e.preventDefault();
            e.stopPropagation();
            onTimestampClick(parseFloat(t));
            return;
          }
        } catch {
          // Not a valid URL, ignore
        }
      }
      el = el.parentElement;
    }
  }, [onTimestampClick]);

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
      {/* Header */}
      <div className="bg-gray-800 border-b border-gray-700 px-4 py-3 flex items-center justify-between">
        <h3 className="font-bold text-lg">{title}</h3>

        {/* Controls */}
        <div className="flex items-center gap-4">
          {/* Zoom Controls */}
          <div className="flex items-center gap-2 border border-gray-700 rounded-lg px-2 py-1">
            <button
              onClick={handleZoomOut}
              disabled={scale <= 0.5}
              className="px-2 py-1 hover:bg-gray-700 rounded disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              title="Zoom out"
            >
              -
            </button>
            <span className="text-xs text-gray-400 min-w-[3rem] text-center">
              {Math.round(scale * 100)}%
            </span>
            <button
              onClick={handleZoomIn}
              disabled={scale >= 2.0}
              className="px-2 py-1 hover:bg-gray-700 rounded disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              title="Zoom in"
            >
              +
            </button>
          </div>

          {/* Open in new tab button */}
          <button
            onClick={handleOpenNewTab}
            className="px-3 py-1 bg-blue-600 hover:bg-blue-500 rounded text-sm transition-colors"
          >
            Open in New Tab
          </button>
        </div>
      </div>

      {/* PDF Content using react-pdf */}
      <div
        ref={containerRef}
        onClick={handleContainerClick}
        className="bg-gray-950 overflow-y-auto pdf-viewer-container"
        style={{ height: '70vh' }}
      >
        {workerReady ? (
          <Document
            file={pdfUrl}
            onLoadSuccess={onDocumentLoadSuccess}
            loading={
              <div className="flex items-center justify-center h-full">
                <p className="text-gray-400">Loading PDF...</p>
              </div>
            }
            error={
              <div className="flex items-center justify-center h-full">
                <p className="text-red-400">Failed to load PDF.</p>
              </div>
            }
          >
            {numPages && Array.from({ length: numPages }, (_, i) => (
              <div key={i} className="flex justify-center mb-4">
                <Page
                  pageNumber={i + 1}
                  scale={scale}
                  renderTextLayer={true}
                  renderAnnotationLayer={true}
                />
              </div>
            ))}
          </Document>
        ) : (
          <div className="flex items-center justify-center h-full">
            <p className="text-gray-400">Loading PDF...</p>
          </div>
        )}
      </div>
    </div>
  );
}
