/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Status colors
        'status-open': '#3b82f6',      // blue-500
        'status-progress': '#eab308',   // yellow-500
        'status-blocked': '#ef4444',    // red-500
        'status-closed': '#22c55e',     // green-500
        // Type colors
        'type-epic': '#8b5cf6',         // violet-500
        'type-feature': '#06b6d4',      // cyan-500
        'type-task': '#6366f1',         // indigo-500
        'type-bug': '#f43f5e',          // rose-500
        'type-chore': '#78716c',        // stone-500
        // Priority colors
        'priority-urgent': '#dc2626',   // red-600
        'priority-high': '#ea580c',     // orange-600
        'priority-normal': '#2563eb',   // blue-600
        'priority-low': '#65a30d',      // lime-600
      },
    },
  },
  plugins: [],
};
