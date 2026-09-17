import next from 'eslint-config-next';

const config = [
  ...next,
  {
    ignores: ['e2e/**'],
  },
];

export default config;
