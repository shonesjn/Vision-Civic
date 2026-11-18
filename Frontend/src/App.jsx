import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './context/AuthContext';
import { ThemeProvider } from './context/ThemeContext';
import MainLayout from './layouts/MainLayout';

import Landing from './pages/Landing';

import { Toaster } from './components/ui/sonner';
import { TooltipProvider } from './components/ui/tooltip';

export default function App() {
  return (
    <ThemeProvider>
      <TooltipProvider delayDuration={200}>
        <AuthProvider>
          <BrowserRouter>
            <Toaster />
            <Routes>
              {/* Main Application Layout with Home View */}
              <Route path="/" element={<MainLayout />}>
                {/* 1. Home Page */}
                <Route index element={<Landing />} />

                {/* Redirects to Home */}
                <Route path="live-monitoring" element={<Navigate to="/" replace />} />
                <Route path="upload-video" element={<Navigate to="/" replace />} />

                {/* Obsolete/Alternate redirects to Home */}
                <Route path="landing" element={<Navigate to="/" replace />} />
                <Route path="dashboard" element={<Navigate to="/" replace />} />
                <Route path="past-events" element={<Navigate to="/" replace />} />
                <Route path="analytics" element={<Navigate to="/" replace />} />
                <Route path="profile" element={<Navigate to="/" replace />} />
                <Route path="user-management" element={<Navigate to="/" replace />} />
                <Route path="login" element={<Navigate to="/" replace />} />
                <Route path="signup" element={<Navigate to="/" replace />} />
              </Route>

              {/* Catch-all fallback */}
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </BrowserRouter>
        </AuthProvider>
      </TooltipProvider>
    </ThemeProvider>
  );
}

