export interface Point { x: number; y: number }
export interface Bounds { left: number; top: number; width: number; height: number }
const clamp = (value: number) => Math.max(0, Math.min(1, value))
// The transformed image plane's live bounds incorporate fit scale, zoom and pan.
export function imagePoint(client: Point, bounds: Bounds): Point {
  return { x: clamp((client.x - bounds.left) / bounds.width), y: clamp((client.y - bounds.top) / bounds.height) }
}
export function boundingBox(start: Point, end: Point) {
  return { x: Math.min(start.x, end.x), y: Math.min(start.y, end.y),
    width: Math.abs(end.x - start.x), height: Math.abs(end.y - start.y) }
}
export function fitScale(viewWidth: number, viewHeight: number, imageWidth: number, imageHeight: number) {
  return Math.min(viewWidth / imageWidth, viewHeight / imageHeight)
}
