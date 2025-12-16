import { useState, useEffect } from 'react';

export interface ElkSettings {
  // Core layout
  algorithm: 'layered' | 'force' | 'mrtree' | 'radial' | 'stress';
  direction: 'DOWN' | 'UP' | 'LEFT' | 'RIGHT';

  // Spacing
  nodeNodeSpacing: number;
  nodeNodeBetweenLayers: number;
  edgeNodeBetweenLayers: number;
  componentSpacing: number;

  // Layered-specific
  nodePlacement: 'NETWORK_SIMPLEX' | 'BRANDES_KOEPF' | 'LINEAR_SEGMENTS' | 'SIMPLE';
  crossingMinimization: 'LAYER_SWEEP' | 'INTERACTIVE';

  // Group padding
  groupPadding: number;
  groupHeaderHeight: number;
}

export const DEFAULT_ELK_SETTINGS: ElkSettings = {
  algorithm: 'layered',
  direction: 'DOWN',
  nodeNodeSpacing: 100,
  nodeNodeBetweenLayers: 150,
  edgeNodeBetweenLayers: 80,
  componentSpacing: 150,
  nodePlacement: 'NETWORK_SIMPLEX',
  crossingMinimization: 'LAYER_SWEEP',
  groupPadding: 60,
  groupHeaderHeight: 50,
};

interface ElkSettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  settings: ElkSettings;
  onSettingsChange: (settings: ElkSettings) => void;
}

export function ElkSettingsModal({
  isOpen,
  onClose,
  settings,
  onSettingsChange,
}: ElkSettingsModalProps) {
  const [localSettings, setLocalSettings] = useState<ElkSettings>(settings);

  useEffect(() => {
    setLocalSettings(settings);
  }, [settings]);

  if (!isOpen) return null;

  const handleChange = (key: keyof ElkSettings, value: string | number) => {
    setLocalSettings((prev) => ({ ...prev, [key]: value }));
  };

  const handleApply = () => {
    onSettingsChange(localSettings);
  };

  const handleReset = () => {
    setLocalSettings(DEFAULT_ELK_SETTINGS);
    onSettingsChange(DEFAULT_ELK_SETTINGS);
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-slate-800 border border-slate-700 rounded-xl shadow-2xl w-[600px] max-h-[85vh] overflow-hidden">
        {/* Header */}
        <div className="px-6 py-4 border-b border-slate-700 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-100">Layout Settings</h2>
            <p className="text-xs text-slate-400 mt-0.5">Configure ELK graph layout parameters</p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-slate-400 hover:text-slate-200 hover:bg-slate-700 rounded-lg transition-colors"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div className="px-6 py-4 overflow-y-auto max-h-[60vh] space-y-6">
          {/* Algorithm Section */}
          <section>
            <h3 className="text-sm font-medium text-slate-300 mb-3 flex items-center gap-2">
              <span className="w-1.5 h-1.5 bg-indigo-500 rounded-full"></span>
              Layout Algorithm
            </h3>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs text-slate-400 mb-1.5">Algorithm</label>
                <select
                  value={localSettings.algorithm}
                  onChange={(e) => handleChange('algorithm', e.target.value)}
                  className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded-lg text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                >
                  <option value="layered">Layered (Hierarchical)</option>
                  <option value="force">Force-Directed</option>
                  <option value="mrtree">MrTree</option>
                  <option value="radial">Radial</option>
                  <option value="stress">Stress</option>
                </select>
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1.5">Direction</label>
                <select
                  value={localSettings.direction}
                  onChange={(e) => handleChange('direction', e.target.value)}
                  className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded-lg text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                >
                  <option value="DOWN">Top → Bottom</option>
                  <option value="UP">Bottom → Top</option>
                  <option value="RIGHT">Left → Right</option>
                  <option value="LEFT">Right → Left</option>
                </select>
              </div>
            </div>
          </section>

          {/* Spacing Section */}
          <section>
            <h3 className="text-sm font-medium text-slate-300 mb-3 flex items-center gap-2">
              <span className="w-1.5 h-1.5 bg-emerald-500 rounded-full"></span>
              Node Spacing
            </h3>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs text-slate-400 mb-1.5">
                  Node-to-Node <span className="text-slate-500">({localSettings.nodeNodeSpacing}px)</span>
                </label>
                <input
                  type="range"
                  min="20"
                  max="200"
                  value={localSettings.nodeNodeSpacing}
                  onChange={(e) => handleChange('nodeNodeSpacing', parseInt(e.target.value))}
                  className="w-full h-2 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-emerald-500"
                />
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1.5">
                  Between Layers <span className="text-slate-500">({localSettings.nodeNodeBetweenLayers}px)</span>
                </label>
                <input
                  type="range"
                  min="50"
                  max="300"
                  value={localSettings.nodeNodeBetweenLayers}
                  onChange={(e) => handleChange('nodeNodeBetweenLayers', parseInt(e.target.value))}
                  className="w-full h-2 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-emerald-500"
                />
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1.5">
                  Edge-Node Gap <span className="text-slate-500">({localSettings.edgeNodeBetweenLayers}px)</span>
                </label>
                <input
                  type="range"
                  min="10"
                  max="150"
                  value={localSettings.edgeNodeBetweenLayers}
                  onChange={(e) => handleChange('edgeNodeBetweenLayers', parseInt(e.target.value))}
                  className="w-full h-2 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-emerald-500"
                />
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1.5">
                  Component Gap <span className="text-slate-500">({localSettings.componentSpacing}px)</span>
                </label>
                <input
                  type="range"
                  min="50"
                  max="300"
                  value={localSettings.componentSpacing}
                  onChange={(e) => handleChange('componentSpacing', parseInt(e.target.value))}
                  className="w-full h-2 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-emerald-500"
                />
              </div>
            </div>
          </section>

          {/* Layered Algorithm Options */}
          {localSettings.algorithm === 'layered' && (
            <section>
              <h3 className="text-sm font-medium text-slate-300 mb-3 flex items-center gap-2">
                <span className="w-1.5 h-1.5 bg-amber-500 rounded-full"></span>
                Layered Algorithm Options
              </h3>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs text-slate-400 mb-1.5">Node Placement</label>
                  <select
                    value={localSettings.nodePlacement}
                    onChange={(e) => handleChange('nodePlacement', e.target.value)}
                    className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded-lg text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                  >
                    <option value="NETWORK_SIMPLEX">Network Simplex</option>
                    <option value="BRANDES_KOEPF">Brandes & Köpf</option>
                    <option value="LINEAR_SEGMENTS">Linear Segments</option>
                    <option value="SIMPLE">Simple</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1.5">Crossing Minimization</label>
                  <select
                    value={localSettings.crossingMinimization}
                    onChange={(e) => handleChange('crossingMinimization', e.target.value)}
                    className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded-lg text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                  >
                    <option value="LAYER_SWEEP">Layer Sweep</option>
                    <option value="INTERACTIVE">Interactive</option>
                  </select>
                </div>
              </div>
            </section>
          )}

          {/* Group Settings */}
          <section>
            <h3 className="text-sm font-medium text-slate-300 mb-3 flex items-center gap-2">
              <span className="w-1.5 h-1.5 bg-purple-500 rounded-full"></span>
              Epic Group Settings
            </h3>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs text-slate-400 mb-1.5">
                  Group Padding <span className="text-slate-500">({localSettings.groupPadding}px)</span>
                </label>
                <input
                  type="range"
                  min="20"
                  max="100"
                  value={localSettings.groupPadding}
                  onChange={(e) => handleChange('groupPadding', parseInt(e.target.value))}
                  className="w-full h-2 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-purple-500"
                />
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1.5">
                  Header Height <span className="text-slate-500">({localSettings.groupHeaderHeight}px)</span>
                </label>
                <input
                  type="range"
                  min="30"
                  max="80"
                  value={localSettings.groupHeaderHeight}
                  onChange={(e) => handleChange('groupHeaderHeight', parseInt(e.target.value))}
                  className="w-full h-2 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-purple-500"
                />
              </div>
            </div>
          </section>

          {/* Presets */}
          <section>
            <h3 className="text-sm font-medium text-slate-300 mb-3 flex items-center gap-2">
              <span className="w-1.5 h-1.5 bg-cyan-500 rounded-full"></span>
              Quick Presets
            </h3>
            <div className="flex flex-wrap gap-2">
              <button
                onClick={() => setLocalSettings({
                  ...DEFAULT_ELK_SETTINGS,
                  nodeNodeSpacing: 60,
                  nodeNodeBetweenLayers: 80,
                  edgeNodeBetweenLayers: 40,
                  groupPadding: 40,
                })}
                className="px-3 py-1.5 bg-slate-700 hover:bg-slate-600 border border-slate-600 rounded-lg text-xs text-slate-300 transition-colors"
              >
                Compact
              </button>
              <button
                onClick={() => setLocalSettings({
                  ...DEFAULT_ELK_SETTINGS,
                  nodeNodeSpacing: 100,
                  nodeNodeBetweenLayers: 150,
                  edgeNodeBetweenLayers: 80,
                  groupPadding: 60,
                })}
                className="px-3 py-1.5 bg-slate-700 hover:bg-slate-600 border border-slate-600 rounded-lg text-xs text-slate-300 transition-colors"
              >
                Balanced
              </button>
              <button
                onClick={() => setLocalSettings({
                  ...DEFAULT_ELK_SETTINGS,
                  nodeNodeSpacing: 150,
                  nodeNodeBetweenLayers: 200,
                  edgeNodeBetweenLayers: 100,
                  componentSpacing: 200,
                  groupPadding: 80,
                })}
                className="px-3 py-1.5 bg-slate-700 hover:bg-slate-600 border border-slate-600 rounded-lg text-xs text-slate-300 transition-colors"
              >
                Spacious
              </button>
              <button
                onClick={() => setLocalSettings({
                  ...DEFAULT_ELK_SETTINGS,
                  direction: 'RIGHT',
                  nodeNodeSpacing: 80,
                  nodeNodeBetweenLayers: 200,
                  edgeNodeBetweenLayers: 60,
                })}
                className="px-3 py-1.5 bg-slate-700 hover:bg-slate-600 border border-slate-600 rounded-lg text-xs text-slate-300 transition-colors"
              >
                Flowchart (L→R)
              </button>
              <button
                onClick={() => setLocalSettings({
                  ...DEFAULT_ELK_SETTINGS,
                  algorithm: 'force',
                  nodeNodeSpacing: 120,
                })}
                className="px-3 py-1.5 bg-slate-700 hover:bg-slate-600 border border-slate-600 rounded-lg text-xs text-slate-300 transition-colors"
              >
                Force Graph
              </button>
            </div>
          </section>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-slate-700 flex items-center justify-between">
          <button
            onClick={handleReset}
            className="px-4 py-2 text-sm text-slate-400 hover:text-slate-200 transition-colors"
          >
            Reset to Defaults
          </button>
          <div className="flex gap-3">
            <button
              onClick={onClose}
              className="px-4 py-2 bg-slate-700 hover:bg-slate-600 rounded-lg text-sm text-slate-300 transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={() => {
                handleApply();
                onClose();
              }}
              className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 rounded-lg text-sm text-white font-medium transition-colors"
            >
              Apply Layout
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
