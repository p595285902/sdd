'use strict';
const { spawn } = require('node:child_process');

class BoundedCommand {
  constructor(command, args, options, { spawnProcess = spawn, timeout = 600_000, cleanupTimeout = 180_000 } = {}) {
    this.cleanupTimeout = cleanupTimeout;
    this.child = spawnProcess(command, args, options);
    this.output = [];
    this.bytes = 0;
    this.closed = false;
    this.done = new Promise((resolve, reject) => {
      const collect = chunk => {
        this.bytes += chunk.length;
        if (this.bytes > 20 * 1024 * 1024) {
          this.failure ||= new Error('Command-validation log exceeded its capture limit');
          this.child.kill('SIGTERM');
        } else this.output.push(Buffer.from(chunk));
      };
      this.child.stdout.on('data', collect);
      this.child.stderr.on('data', collect);
      this.child.once('error', () => { this.failure ||= new Error('Command-validation runner could not be launched'); });
      this.child.once('close', (code, signal) => {
        this.closed = true;
        clearTimeout(this.timer);
        const output = Buffer.concat(this.output).toString('utf8');
        this.output = [];
        if (this.failure) reject(this.failure);
        else resolve({ code, signal, output });
      });
    });
    this.done.catch(() => {});
    this.expired = new Promise((_, reject) => {
      this.timer = setTimeout(() => {
        this.failure ||= new Error('Command-validation runner exceeded its invocation deadline');
        this.stop().then(() => reject(this.failure), reject);
      }, timeout);
    });
    this.expired.catch(() => {});
  }
  async execute() { return Promise.race([this.done, this.expired]); }
  async stop() {
    if (this.closed) return this.done.catch(() => {});
    this.stopping ||= (async () => {
      this.child.kill('SIGTERM'); // Allow the runner's actual owned finally teardown.
      let timer;
      try {
        await Promise.race([this.done.catch(() => {}), new Promise((_, reject) => {
          timer = setTimeout(() => reject(new Error('Command-validation cleanup deadline exceeded; child ownership remains retained')), this.cleanupTimeout);
        })]);
      } finally { clearTimeout(timer); }
    })();
    return this.stopping;
  }
}
module.exports = { BoundedCommand };
