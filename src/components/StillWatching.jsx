import { useEffect, useRef } from 'react'

// Blocks the player until the viewer answers. The primary button takes focus so Enter keeps watching.
export default function StillWatching({ onContinue, onStop, className = '', autoFocus = true }) {
  const keep = useRef(null)
  useEffect(() => { if (autoFocus) keep.current?.focus() }, [autoFocus])
  return (
    <div role="alertdialog" aria-modal="true" aria-labelledby="still-h" aria-describedby="still-d"
      className={`grid place-items-center bg-black p-6 text-center ${className}`}>
      <div className="max-w-sm space-y-3">
        <h2 id="still-h" className="text-xl font-bold">Are you still watching?</h2>
        <p id="still-d" className="text-sm text-muted">Nothing has been pressed for a while, so playback is paused. This saves your data and keeps your screen free for someone else.</p>
        <div className="flex flex-wrap justify-center gap-2">
          <button ref={keep} type="button" className="btn btn-primary" onClick={onContinue}>Keep watching</button>
          <button type="button" className="btn btn-ghost" onClick={onStop}>Stop</button>
        </div>
      </div>
    </div>
  )
}
