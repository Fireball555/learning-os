import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import Admin from './Admin.jsx'
import { applyTheme } from './themes.js'
import './index.css'
applyTheme()
const isAdmin = window.location.pathname.startsWith('/admin')
ReactDOM.createRoot(document.getElementById('root')).render(isAdmin ? <Admin /> : <App />)
