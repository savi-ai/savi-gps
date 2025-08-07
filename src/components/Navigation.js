import React from 'react';
import { AppBar, Toolbar, Typography, Button, Box, Tabs, Tab } from '@mui/material';
import { Link as RouterLink, useLocation, useNavigate } from 'react-router-dom';

function Navigation() {
  const location = useLocation();
  const navigate = useNavigate();

  const handleTabChange = (event, newValue) => {
    if (newValue === 0) {
      navigate('/developer/upload');
    } else if (newValue === 1) {
      navigate('/developer/test');
    }
  };

  // Determine which tab is active based on current route
  const getActiveTab = () => {
    if (location.pathname === '/developer/upload') return 0;
    if (location.pathname === '/developer/test') return 1;
    return 0; // default to upload tab
  };

  return (
    <AppBar position="static">
      <Toolbar>
        <Typography variant="h6" component="div" sx={{ flexGrow: 1 }}>
          RAG Experimentation Tool
        </Typography>
        <Box sx={{ display: 'flex', gap: 2, alignItems: 'center' }}>
          <Button 
            color="inherit" 
            component={RouterLink} 
            to="/" 
            sx={{ 
              backgroundColor: location.pathname === '/' ? 'rgba(255, 255, 255, 0.1)' : 'transparent' 
            }}
          >
            Use Cases
          </Button>
          
          {/* Developer Tabs */}
          <Box sx={{ display: 'flex', alignItems: 'center' }}>
            <Tabs 
              value={getActiveTab()} 
              onChange={handleTabChange}
              sx={{ 
                '& .MuiTab-root': { 
                  color: 'white',
                  textTransform: 'none',
                  minWidth: 'auto',
                  px: 2
                },
                '& .Mui-selected': {
                  backgroundColor: 'rgba(255, 255, 255, 0.1)',
                  borderRadius: 1
                }
              }}
            >
              <Tab label="Upload Data" />
              <Tab label="Test" />
            </Tabs>
          </Box>
        </Box>
      </Toolbar>
    </AppBar>
  );
}

export default Navigation; 