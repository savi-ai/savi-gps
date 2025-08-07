import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { ThemeProvider, createTheme } from '@mui/material';
import CssBaseline from '@mui/material/CssBaseline';
import Navigation from './components/Navigation';
import SimpleRAGPage from './components/SimpleRAGPage';
import DeveloperPage from './components/DeveloperPage';

const theme = createTheme({
  palette: {
    primary: {
      main: '#1976d2',
    },
    secondary: {
      main: '#dc004e',
    },
  },
  typography: {
    fontFamily: '"Roboto", "Helvetica", "Arial", sans-serif',
  },
});

function App() {
  return (
    <Router>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        <Navigation />
        <Routes>
          <Route path="/" element={<SimpleRAGPage />} />
          <Route path="/developer" element={<Navigate to="/developer/upload" replace />} />
          <Route path="/developer/upload" element={<DeveloperPage />} />
          <Route path="/developer/test" element={<DeveloperPage />} />
        </Routes>
      </ThemeProvider>
    </Router>
  );
}

export default App; 