import React from 'react';
import { Box, Typography } from '@mui/material';
import { Psychology as PsychologyIcon } from '@mui/icons-material';

const Logo = () => {
  return (
    <Box sx={{ 
      display: 'flex', 
      alignItems: 'center', 
      gap: 2,
      cursor: 'pointer'
    }}>
      <PsychologyIcon 
        sx={{ 
          fontSize: 36, 
          color: 'white',
          filter: 'drop-shadow(0 1px 2px rgba(0,0,0,0.1))'
        }} 
      />
      <Typography 
        variant="h5" 
        component="div" 
        sx={{ 
          fontWeight: 700,
          letterSpacing: '0.5px',
          color: 'white',
          textShadow: '0 1px 2px rgba(0,0,0,0.1)',
          userSelect: 'none'
        }}
      >
        RAG Experimentation Tool
      </Typography>
    </Box>
  );
};

export default Logo; 