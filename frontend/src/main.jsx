import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './theme.css'
import './App.css'
import App from './App.jsx'
import PublicDashboard from './components/PublicDashboard.jsx'

// Public share links (/share/<token>) render a read-only dashboard with no
// auth. Everything else is the authenticated app.
const shareMatch = window.location.pathname.match(/^\/share\/([A-Za-z0-9_-]+)/)

createRoot(document.getElementById('root')).render(
  <StrictMode>
    {shareMatch ? <PublicDashboard token={shareMatch[1]} /> : <App />}
  </StrictMode>,
)
