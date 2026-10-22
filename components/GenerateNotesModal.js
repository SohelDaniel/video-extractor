'use client';

import { useState } from 'react';

const NOTE_TYPES = [
  { value: 'full', label: 'Full Lecture Notes', description: 'Comprehensive notes covering all topics' },
  { value: 'summary', label: 'Summary', description: 'Concise overview of the main topics and takeaways' },
  { value: 'definitions', label: 'Key Definitions & Theorems', description: 'Only definitions, theorems, and formulas' },
  { value: 'custom', label: 'Custom Prompt', description: 'Provide your own instructions' },
];

export default function GenerateNotesModal({ isOpen, onClose, onGenerate, isGenerating }) {
  const [noteType, setNoteType] = useState('full');
  const [customPrompt, setCustomPrompt] = useState('');
  const [languages, setLanguages] = useState({ en: true, he: false });

  if (!isOpen) return null;

  const toggleLanguage = (lang) => {
    setLanguages(prev => ({ ...prev, [lang]: !prev[lang] }));
  };

  const selectedLanguages = Object.entries(languages)
    .filter(([, v]) => v)
    .map(([k]) => k);

  const canGenerate = selectedLanguages.length > 0 && !isGenerating &&
    (noteType !== 'custom' || customPrompt.trim().length > 0);

  const handleGenerate = () => {
    onGenerate({
      languages: selectedLanguages,
      noteType,
      customPrompt: noteType === 'custom' ? customPrompt.trim() : null,
    });
  };

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-gray-900 border border-gray-700 rounded-xl p-6 w-full max-w-md mx-4"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-xl font-bold mb-5">Generate Notes</h2>

        {/* Note Type */}
        <div className="mb-5">
          <label className="text-sm font-bold text-gray-400 uppercase mb-2 block">Note Type</label>
          <div className="space-y-2">
            {NOTE_TYPES.map(({ value, label, description }) => (
              <label
                key={value}
                className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-all ${
                  noteType === value
                    ? 'border-purple-500 bg-purple-500/10'
                    : 'border-gray-800 bg-black hover:border-gray-700'
                }`}
              >
                <input
                  type="radio"
                  name="noteType"
                  value={value}
                  checked={noteType === value}
                  onChange={() => setNoteType(value)}
                  className="mt-0.5 flex-shrink-0"
                />
                <div>
                  <div className="font-medium text-sm">{label}</div>
                  <div className="text-xs text-gray-500 mt-0.5">{description}</div>
                </div>
              </label>
            ))}
          </div>
        </div>

        {/* Custom Prompt Textarea */}
        {noteType === 'custom' && (
          <div className="mb-5">
            <label className="text-sm font-bold text-gray-400 uppercase mb-2 block">Your Instructions</label>
            <textarea
              value={customPrompt}
              onChange={(e) => setCustomPrompt(e.target.value)}
              placeholder="e.g., List all examples given in the lecture..."
              rows={3}
              className="w-full px-3 py-2 bg-black border border-gray-800 rounded-lg text-sm focus:border-purple-500 focus:ring-2 focus:ring-purple-500/20 outline-none transition-all resize-none"
            />
          </div>
        )}

        {/* Language Selection */}
        <div className="mb-6">
          <label className="text-sm font-bold text-gray-400 uppercase mb-2 block">Languages</label>
          <div className="flex gap-4">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={languages.en}
                onChange={() => toggleLanguage('en')}
              />
              <span className="text-sm">English</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={languages.he}
                onChange={() => toggleLanguage('he')}
              />
              <span className="text-sm">Hebrew</span>
            </label>
          </div>
          {selectedLanguages.length === 0 && (
            <p className="text-xs text-red-400 mt-1">Select at least one language</p>
          )}
        </div>

        {/* Actions */}
        <div className="flex gap-3">
          <button
            onClick={onClose}
            disabled={isGenerating}
            className="flex-1 px-4 py-2.5 bg-gray-800 hover:bg-gray-700 disabled:opacity-50 rounded-lg font-bold text-sm transition-all"
          >
            Cancel
          </button>
          <button
            onClick={handleGenerate}
            disabled={!canGenerate}
            className="flex-1 px-4 py-2.5 bg-gradient-to-r from-purple-600 to-purple-800 hover:from-purple-500 hover:to-purple-700 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg font-bold text-sm transition-all"
          >
            {isGenerating ? 'Generating...' : 'Generate'}
          </button>
        </div>
      </div>
    </div>
  );
}
