module.exports = {
  platform: 'github',
  token: process.env.RENOVATE_TOKEN || process.env.GITHUB_TOKEN,
  repositories: ['KRoperUK/fill-er-up'],
  gitAuthor: 'Renovate Bot <bot@renovateapp.com>',
};
