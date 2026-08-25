/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./src/**/*.{js,ts,jsx,tsx}",
    "./src/sidepanel/index.html",
  ],
  theme: {
    extend: {
      colors: {
        sf: {
          blue: '#0176d3',
          dark: '#032d60',
          light: '#e8f4fd',
          gray: '#706e6b',
          success: '#2e844a',
          error: '#ea001e',
          warning: '#fe9339',
        },
      },
      fontFamily: {
        sans: ['Salesforce Sans', 'Arial', 'Helvetica', 'sans-serif'],
        mono: ['SFMono-Regular', 'Consolas', 'Liberation Mono', 'Menlo', 'monospace'],
      },
    },
  },
  plugins: [],
}

