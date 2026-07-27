import { serve } from '@hono/node-server'
import { createHash } from 'node:crypto'
import { Hono } from 'hono'

const app = new Hono()

app.get('/health', (c) => c.text('ok'))
app.post('/upload', async (c) => {
  const form = await c.req.formData()
  const file = form.get('file')
  if (typeof file === 'string' || file === null) {
    return c.json({ error: 'file required' }, 400)
  }

  const digest = createHash('sha256')
  let size = 0
  for await (const chunk of file.stream()) {
    size += chunk.byteLength
    digest.update(chunk)
  }
  return c.json({
    size,
    sha256: digest.digest('hex'),
    temp_disk_bytes: 0,
  })
})

if (process.env.BENCH_IMPORT_ONLY !== '1') {
  const port = Number.parseInt(process.env.BENCH_PORT ?? '3000', 10)
  serve({ fetch: app.fetch, hostname: '127.0.0.1', port })
}

export default app
