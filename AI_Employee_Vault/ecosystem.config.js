/**
 * PM2 Ecosystem Configuration — Silver Tier
 *
 * Manages all long-running watcher processes.
 *
 * Usage:
 *   pm2 start ecosystem.config.js     # Start all watchers
 *   pm2 list                          # View process status
 *   pm2 logs                          # View all logs
 *   pm2 save                          # Persist process list
 *   pm2 startup                       # Auto-start on boot
 *   pm2 stop all                      # Stop all processes
 *   pm2 restart all                   # Restart all processes
 */

module.exports = {
  apps: [
    {
      name: "file-watcher",
      script: "Skills/File_System_Watcher/fs_watcher.py",
      interpreter: "python",
      cwd: __dirname,
      watch: false,
      autorestart: true,
      max_restarts: 10,
      restart_delay: 5000,
      env: {
        VAULT_PATH: __dirname,
      },
    },
    {
      name: "gmail-watcher",
      script: "Skills/Gmail_Watcher/gmail_watcher.py",
      interpreter: "python",
      cwd: __dirname,
      watch: false,
      autorestart: true,
      max_restarts: 10,
      restart_delay: 10000,
      env: {
        VAULT_PATH: __dirname,
      },
    },
    {
      name: "approval-gate",
      script: "Skills/Approval_Gate/approval_gate.py",
      interpreter: "python",
      args: "--watch",
      cwd: __dirname,
      watch: false,
      autorestart: true,
      max_restarts: 10,
      restart_delay: 5000,
      env: {
        VAULT_PATH: __dirname,
      },
    },
    {
      name: "approval-watcher",
      script: "Skills/Approval_Watcher/approval_watcher.py",
      interpreter: "python",
      cwd: __dirname,
      watch: false,
      autorestart: true,
      max_restarts: 10,
      restart_delay: 5000,
      env: {
        VAULT_PATH: __dirname,
      },
    },
  ],
};
