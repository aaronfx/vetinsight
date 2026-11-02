import { describe, expect, it } from 'vitest'
import { boundingBox, fitScale, imagePoint } from './geometry'

describe('Image coordinate invariants', () => {
  it('keeps the same normalized box across fit, zoom, pan and viewport resize', () => {
    const source = { width: 1000, height: 500 }
    for (const [viewWidth, viewHeight, zoom, panX, panY] of [[800, 600, 1, 0, 0], [800, 600, 2.5, -250, 70], [360, 450, 1.5, 40, -20]]) {
      const scale = fitScale(viewWidth, viewHeight, source.width, source.height) * zoom
      const bounds = { left: (viewWidth - source.width * scale) / 2 + panX, top: (viewHeight - source.height * scale) / 2 + panY,
        width: source.width * scale, height: source.height * scale }
      const start = imagePoint({ x: bounds.left + bounds.width * .1, y: bounds.top + bounds.height * .2 }, bounds)
      const end = imagePoint({ x: bounds.left + bounds.width * .4, y: bounds.top + bounds.height * .6 }, bounds)
      const box = boundingBox(start, end)
      expect(box.x).toBeCloseTo(.1); expect(box.y).toBeCloseTo(.2)
      expect(box.width).toBeCloseTo(.3); expect(box.height).toBeCloseTo(.4)
    }
  })
  it('supports reverse drawing and clips at image boundaries', () => {
    const bounds = { left: 30, top: 40, width: 100, height: 200 }
    expect(imagePoint({ x: -40, y: 400 }, bounds)).toEqual({ x: 0, y: 1 })
    expect(boundingBox({ x: .6, y: .8 }, { x: .1, y: .2 })).toMatchObject({ x: .1, y: .2, width: .5 })
  })
})
