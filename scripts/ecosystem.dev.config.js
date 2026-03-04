// 注意：项目路径含空格，PM2 无法直接处理，使用 ~/.autoc 软链接绕过
// 创建方式：ln -sfn "/Users/gniu/AIWorkspace/01. Concept/autoc" ~/.autoc
const path = require('path');
const os = require('os');
const PROJECT_DIR = path.join(os.homedir(), '.autoc');

module.exports = {
  apps: [
    {
      name: 'autoc-backend',
      script: path.join(PROJECT_DIR, 'scripts/start-backend.sh'),
      cwd: PROJECT_DIR,
      instances: 1,
      exec_mode: 'fork',
      autorestart: true,
      watch: [path.join(PROJECT_DIR, 'autoc')],
      ignore_watch: [
        'workspace', '.autoc', '__pycache__', 'node_modules',
        '*.pyc', '.git', 'logs', 'web', '.venv', 'tests',
        '.autoc_state', '.autoc_experience', '*.db', '*.db-*',
      ],
      watch_delay: 2000,
      max_memory_restart: '1G',
      env: {
        NODE_ENV: 'development',
        PYTHONUNBUFFERED: '1'
      },
      error_file: path.join(PROJECT_DIR, 'logs/dev-backend-error.log'),
      out_file: path.join(PROJECT_DIR, 'logs/dev-backend-out.log'),
      log_file: path.join(PROJECT_DIR, 'logs/dev-backend-combined.log'),
      time: true,
      merge_logs: true,
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z'
    },
    {
      name: 'autoc-frontend',
      script: 'npm',
      args: 'run dev',
      cwd: path.join(PROJECT_DIR, 'web'),
      interpreter: 'none',
      instances: 1,
      exec_mode: 'fork',
      autorestart: true,
      watch: false,
      env: {
        NODE_ENV: 'development'
      },
      error_file: path.join(PROJECT_DIR, 'logs/dev-frontend-error.log'),
      out_file: path.join(PROJECT_DIR, 'logs/dev-frontend-out.log'),
      log_file: path.join(PROJECT_DIR, 'logs/dev-frontend-combined.log'),
      time: true,
      merge_logs: true,
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z'
    }
  ]
};
