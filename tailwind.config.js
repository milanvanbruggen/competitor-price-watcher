/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./static/**/*.js"
  ],
  theme: {
    fontSize: {
      'xs': '0.75rem',    // 12px
      'sm': '0.875rem',   // 14px
      'base': '1rem',     // 16px
      'lg': '1.125rem',   // 18px
      'xl': '1.25rem',    // 20px
      '2xl': '1.5rem'     // 24px
    },
    extend: {
      fontFamily: {
        mono: ['Consolas', 'Monaco', 'monospace']
      },
      colors: {
        status: {
          info: '#3498db',
          success: '#2ecc71',
          error: '#e74c3c',
          warning: '#f1c40f'
        }
      }
    },
  },
  plugins: [
    require('@tailwindcss/forms')
  ],
}

