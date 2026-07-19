import { cpSync, rmSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const frontendDir = path.dirname(path.dirname(fileURLToPath(import.meta.url)))
const distDir = path.join(frontendDir, 'dist')
const targetDir = path.join(frontendDir, '..', 'vc_control', 'static', 'app')

if (existsSync(targetDir)) {
  rmSync(targetDir, { recursive: true, force: true })
}
cpSync(distDir, targetDir, { recursive: true })
console.log(`Copied ${distDir} -> ${targetDir}`)
