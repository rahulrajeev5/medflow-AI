import React from 'react';
import ReactDOM from 'react-dom/client';
import { AuthProvider } from 'react-oidc-context';

import App from './App';
import './styles.css';

const cognitoAuthConfig = {
  authority:
    'https://cognito-idp.eu-central-1.amazonaws.com/eu-central-1_t23sf3Gb5',
  client_id: '3pd6tem71q5vf35cbn3rqchhpt',
  redirect_uri: 'http://localhost:5173',
  response_type: 'code',
  scope: 'openid email profile',
};

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <AuthProvider {...cognitoAuthConfig}>
      <App />
    </AuthProvider>
  </React.StrictMode>,
);