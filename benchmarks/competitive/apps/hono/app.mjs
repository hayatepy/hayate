import { serve } from '@hono/node-server'
import { Hono } from 'hono'

const app = new Hono()

app.get('/text', (c) => c.text('hello'))
app.get('/items/:id', (c) => {
  const id = c.req.param('id')
  return c.json({ id, name: `item-${id}` })
})
app.post('/echo', async (c) => {
  const data = await c.req.json()
  const message = data.message
  return c.json({ message, length: message.length })
})

for (let index = 0; index < 64; index += 1) {
  app.get(`/route${index}/:key`, (c) => c.text('ok'))
}

if (process.env.BENCH_IMPORT_ONLY !== '1') {
  const port = Number.parseInt(process.env.BENCH_PORT ?? '3000', 10)
  serve({ fetch: app.fetch, hostname: '127.0.0.1', port })
}

export default app
