// Starts a throwaway API for the end-to-end run: fresh SQLite database, migrations, seed data, then uvicorn on :8001.
// It never reads backend/.env (ENV_FILE points at a file that does not exist) and talks to no outside service.
import { spawn, spawnSync } from 'node:child_process'
import { existsSync, mkdirSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const backend = path.resolve(here, '..', '..', 'backend')
const dir = path.join(tmpdir(), 'ott-e2e')
mkdirSync(dir, { recursive: true })
const db = path.join(dir, 'e2e.db')
for (const f of [db, `${db}-journal`]) if (existsSync(f)) rmSync(f)

const env = {
  ...process.env,
  ENV_FILE: 'none.env', ENV: 'test', DATABASE_URL: `sqlite:///${db.replaceAll('\\', '/')}`, REDIS_URL: '',
  REQUIRE_EMAIL_VERIFICATION: 'false', CORS_ORIGINS: 'http://localhost:5174', FRONTEND_URL: 'http://localhost:5174',
  DEFAULT_COUNTRY: 'US', COOKIE_SECURE: 'false', TMDB_READ_TOKEN: '', TMDB_API_KEY: '', WATCHMODE_API_KEY: '', SMTP_HOST: '',
  STRIPE_SECRET_KEY: '', STRIPE_WEBHOOK_SECRET: '',
}
const run = (args) => {
  const r = spawnSync('python', args, { cwd: backend, env, stdio: 'inherit' })
  if (r.status !== 0) process.exit(r.status ?? 1)
}
run(['-m', 'alembic', 'upgrade', 'head'])
run([path.join(here, 'seed.py')])
const api = spawn('python', ['-m', 'uvicorn', 'app.main:app', '--port', '8001', '--log-level', 'warning'], { cwd: backend, env, stdio: 'inherit' })
const stop = () => { api.kill(); process.exit(0) }
process.on('SIGINT', stop)
process.on('SIGTERM', stop)
api.on('exit', (code) => process.exit(code ?? 0))
