import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import AuthProvider from './Auth'
import { PublicResearchPage } from './Research'

const isPublicResearch = window.location.pathname === '/research'
if (isPublicResearch) document.title = 'VetInsight — Research workspace'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {isPublicResearch ? <PublicResearchPage /> : <AuthProvider><App /></AuthProvider>}
  </StrictMode>,
)
