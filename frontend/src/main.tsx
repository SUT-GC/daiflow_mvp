import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './styles/global.css'

// Apply saved theme
const savedTheme = localStorage.getItem('daiflow-theme') || 'dark'
document.documentElement.setAttribute('data-theme', savedTheme)
document.body.setAttribute('data-theme', savedTheme)

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
