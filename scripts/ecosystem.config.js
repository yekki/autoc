// 注意：项目路径含空格，PM2 无法直接处理，使用 ~/.autoc 软链接绕过
// 创建方式：ln -sfn "/Users/gniu/AIWorkspace/01. Concept/autoc" ~/.autoc
const path = require('path');
const os = require('os');
const PROJECT_DIR = path.join(os.homedir(), '.autoc');

module.exports = {
  apps: [
    {
      name: 'autoc-web',
      script: path.join(PROJECT_DIR, 'scripts/start-backend.sh'),
      cwd: PROJECT_DIR,
      instances: 1,
      exec_mode: 'fork',
      autorestart: true,
      watch: false,
      max_memory_restart: '1G',
      env: {
        NODE_ENV: 'production',
        PYTHONUNBUFFERED: '1'
      },
      error_file: path.join(PROJECT_DIR, 'logs/autoc-web-error.log'),
      out_file: path.join(PROJECT_DIR, 'logs/autoc-web-out.log'),
      log_file: path.join(PROJECT_DIR, 'logs/autoc-web-combined.log'),
      time: true,
      merge_logs: true,
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z'
    }
  ]
};
