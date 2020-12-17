import React from 'react';
import ErrorBanner from '../components/errorBanner';
import { LoginContext } from '../components/loginContext';
import TokenInfo from '../components/tokenInfo';
import useError from '../hooks/error';
import useLogin from '../hooks/login';

export default function Home() {
  const { error, onError } = useError();
  const { csrf, username, scopes } = useLogin(onError);

  return (
    <LoginContext.Provider value={{ csrf, username, scopes }}>
      <ErrorBanner error={error} id="error" />
      <TokenInfo onError={onError} />
    </LoginContext.Provider>
  );
}
