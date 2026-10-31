import { useEffect, useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { api } from '../api/client'
import { ErrorBox } from './ui'

export const REPORT_KINDS = [
  ['no_video', 'No picture'],
  ['no_sound', 'No sound'],
  ['buffering', 'Keeps stopping to load'],
  ['out_of_sync', 'Sound and picture are out of step'],
  ['subtitles', 'Subtitles are wrong or missing'],
  ['other', 'Something else'],
]

// Sits on top of the player. Key presses stay inside it so typing a space does not pause the video.
export default function ReportProblem({ titleId, episodeId, getPosition, onClose, className = '', autoFocus = true }) {
  const [kind, setKind] = useState('')
  const [note, setNote] = useState('')
  const first = useRef(null)
  useEffect(() => { if (autoFocus) first.current?.focus() }, [autoFocus])
  const send = useMutation({
    mutationFn: () => api('/playback/reports', {
      method: 'POST',
      body: { title_id: titleId, episode_id: episodeId || null, kind, note: note.trim() || null, position_seconds: Math.max(0, Math.floor(getPosition?.() || 0)) },
    }),
  })
  const stop = (e) => {
    e.stopPropagation()
    if (e.key === 'Escape') onClose()
  }
  return (
    <div role="dialog" aria-modal="true" aria-labelledby="report-h" onKeyDown={stop} onClick={(e) => e.stopPropagation()}
      className={`grid place-items-center overflow-y-auto bg-black/90 p-4 ${className}`}>
      <div className="w-full max-w-sm space-y-3">
        <h2 id="report-h" className="text-lg font-bold">Report a problem</h2>
        {send.isSuccess ? (
          <>
            <p role="status" className="text-sm text-muted">Thanks. Your report was sent and the team can see which title and moment it was.</p>
            <button type="button" className="btn btn-primary" autoFocus onClick={onClose}>Back to the video</button>
          </>
        ) : (
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (kind) send.mutate() }}>
            <fieldset className="space-y-1.5">
              <legend className="mb-1 text-sm text-muted">What went wrong?</legend>
              {REPORT_KINDS.map(([k, label], i) => (
                <label key={k} className="flex items-center gap-2 text-sm">
                  <input ref={i === 0 ? first : undefined} type="radio" name="report-kind" value={k} checked={kind === k} onChange={() => setKind(k)} />
                  {label}
                </label>
              ))}
            </fieldset>
            <label className="block text-sm">
              <span className="text-muted">Anything to add? (optional)</span>
              <textarea className="input mt-1 w-full" rows={3} maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />
            </label>
            <ErrorBox error={send.error} />
            <div className="flex gap-2">
              <button className="btn btn-primary" disabled={!kind || send.isPending}>{send.isPending ? 'Sending…' : 'Send report'}</button>
              <button type="button" className="btn btn-ghost" onClick={onClose}>Cancel</button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
