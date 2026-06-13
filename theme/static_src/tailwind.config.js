/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    // Templates
    '../../templates/**/*.html',
    '../../**/templates/**/*.html',
    // Theme
    './src/**/*.css',
  ],
  theme: {
    extend: {
      colors: {
        // White-label overridable via CSS custom properties
        brand: {
          primary: 'var(--brand-primary, #4f46e5)',
          'primary-hover': 'var(--brand-primary-hover, #4338ca)',
          secondary: 'var(--brand-secondary, #7c3aed)',
        },
      },
    },
  },
  plugins: [],
}
