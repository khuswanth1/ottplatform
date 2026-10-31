import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  DownloadIcon,
  FullscreenIcon,
  MinimizeIcon,
  FlagIcon,
  PauseIcon,
  PipIcon,
  PlayIcon,
  SettingsIcon,
  SkipBackIcon,
  SkipForwardIcon,
  Volume2Icon,
  VolumeXIcon,
  XIcon,
} from './icons'
import { api, buildQuery, getProfileId } from '../api/client'
import { activeMarker, formatTime } from '../lib/utils'
import { isIdle } from '../lib/stillWatching'
import StillWatching from './StillWatching'
import ReportProblem from './ReportProblem'
import SkipButton from './SkipButton'

const SAVE_EVERY_MS = 15_000
const HEARTBEAT_MS = 30_000
const STREAM_ERROR = 'This stream could not be played. It may have expired or be unavailable.'

// YouTube's own player: start playing, no related-video suggestions from other channels at the end
const embedSrc = (url) => (/^https:\/\/www\.youtube-nocookie\.com\/embed\//.test(url) && !url.includes('?') ? `${url}?autoplay=1&rel=0&playsinline=1` : url)

export default function Player({ session, titleId, episodeId, onNext, onPrev, onEnded, onStop }) {
  const videoRef = useRef(null)
  const wrapRef = useRef(null)
  const lastSaved = useRef(-1)
  const engine = useRef(null)
  const progress = useRef({ pos: 0, dur: 0 })
  const [playing, setPlaying] = useState(false)
  const [time, setTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [volume, setVolume] = useState(1)
  const [muted, setMuted] = useState(false)
  const [levels, setLevels] = useState([])
  const [level, setLevel] = useState(-1)
  const [error, setError] = useState('')
  const [fullscreen, setFullscreen] = useState(false)
  const [inPip, setInPip] = useState(false)
  const [reporting, setReporting] = useState(false)
  const canPip = typeof document !== 'undefined' && !!document.pictureInPictureEnabled
  const [subs, setSubs] = useState(-1)
  const [rate, setRate] = useState(1)
  const [audioTracks, setAudioTracks] = useState([])
  const [audio, setAudio] = useState(0)
  const [showSettings, setShowSettings] = useState(false)
  const [showControls, setShowControls] = useState(true)
  const controlsTimeout = useRef(null)

  const markers = useQuery({
    queryKey: ['markers', titleId, episodeId || null],
    queryFn: () => api(`/titles/${titleId}/markers`, { params: { episode_id: episodeId || undefined } }),
    staleTime: 10 * 60_000,
    retry: false,
  })
  const [stopped, setStopped] = useState('')
  const [asking, setAsking] = useState(false)
  const lastInput = useRef(Date.now())

  const triggerControls = useCallback(() => {
    setShowControls(true)
    clearTimeout(controlsTimeout.current)
    if (playing && !showSettings) {
      controlsTimeout.current = setTimeout(() => setShowControls(false), 3500)
    }
  }, [playing, showSettings])

  useEffect(() => {
    if (!playing || showSettings) {
      setShowControls(true)
      clearTimeout(controlsTimeout.current)
    } else {
      triggerControls()
    }
  }, [playing, showSettings, triggerControls])

  const handleSeek = useCallback((t) => {
    const v = videoRef.current
    if (!v) return
    const max = Number.isFinite(v.duration) ? v.duration : Infinity
    v.currentTime = Math.max(0, Math.min(t, max))
  }, [])

  const save = useCallback(
    (keepalive = false) => {
      const { pos, dur } = progress.current
      if (!dur || session.kind === 'embed') return
      const p = Math.floor(pos)
      if (p === lastSaved.current) return
      lastSaved.current = p
      api('/watch-progress', {
        method: 'PUT',
        keepalive,
        body: {
          title_id: titleId,
          episode_id: episodeId || null,
          position_seconds: p,
          duration_seconds: Math.floor(dur),
        },
      }).catch(() => {})
    },
    [session.kind, titleId, episodeId],
  )

  useEffect(() => {
    const v = videoRef.current
    if (!v || session.kind === 'embed') return undefined
    let disposed = false
    setError('')
    const resume = () => {
      const pos = session.resume_position_seconds || 0
      if (pos > 5 && Number.isFinite(v.duration) && pos < v.duration - 5) v.currentTime = pos
    }
    v.addEventListener('loadedmetadata', resume, { once: true })
    ;(async () => {
      try {
        if (session.kind === 'hls' && !v.canPlayType('application/vnd.apple.mpegurl')) {
          const { default: Hls } = await import('hls.js')
          if (disposed) return
          if (!Hls.isSupported()) throw new Error('This browser cannot play HLS streams.')
          const hls = new Hls({ maxBufferLength: 15, backBufferLength: 15, startLevel: -1 })
          engine.current = {
            destroy: () => hls.destroy(),
            setLevel: (i) => { hls.currentLevel = i },
            setAudio: (i) => { hls.audioTrack = i },
          }
          hls.on(Hls.Events.AUDIO_TRACKS_UPDATED, (_, d) =>
            setAudioTracks(d.audioTracks.map((t, i) => ({ i, label: t.name || t.lang || `Track ${i + 1}` }))),
          )
          hls.on(Hls.Events.MANIFEST_PARSED, (_, d) => {
            setLevels(d.levels.map((l, i) => ({ i, label: l.height ? `${l.height}p` : `${Math.round(l.bitrate / 1000)}k` })))
            v.play().catch(() => {})
          })
          hls.on(Hls.Events.ERROR, (_, d) => { if (d.fatal) setError(STREAM_ERROR) })
          hls.loadSource(session.url)
          hls.attachMedia(v)
        } else if (session.kind === 'dash') {
          const dashjs = (await import('dashjs')).default
          if (disposed) return
          const p = dashjs.MediaPlayer().create()
          p.updateSettings({ streaming: { buffer: { bufferTimeDefault: 5, bufferTimeAtTopQuality: 10 } } })
          p.initialize(v, session.url, true)
          engine.current = {
            destroy: () => p.reset(),
            setLevel: (i) => {
              p.updateSettings({ streaming: { abr: { autoSwitchBitrate: { video: i < 0 } } } })
              if (i >= 0) p.setQualityFor('video', i)
            },
          }
          p.on('streamInitialized', () =>
            setLevels((p.getBitrateInfoListFor('video') || []).map((b, i) => ({ i, label: b.height ? `${b.height}p` : `${Math.round(b.bitrate / 1000)}k` }))),
          )
          p.on('error', () => setError(STREAM_ERROR))
        } else {
          v.src = session.url
          v.play().catch(() => {})
        }
      } catch (e) {
        setError(e.message || 'Could not start playback.')
      }
    })()
    return () => {
      disposed = true
      v.removeEventListener('loadedmetadata', resume)
      engine.current?.destroy()
      engine.current = null
      setLevels([])
      setLevel(-1)
    }
  }, [session.url, session.kind, session.resume_position_seconds])

  useEffect(() => {
    const t = setInterval(() => { if (videoRef.current && !videoRef.current.paused) save() }, SAVE_EVERY_MS)
    const onHide = () => { if (document.visibilityState === 'hidden') save(true) }
    document.addEventListener('visibilitychange', onHide)
    return () => { clearInterval(t); document.removeEventListener('visibilitychange', onHide); save(true) }
  }, [save])

  useEffect(() => {
    const touch = () => { lastInput.current = Date.now() }
    const events = ['pointerdown', 'keydown', 'touchstart']
    events.forEach((e) => document.addEventListener(e, touch, { passive: true }))
    const t = setInterval(() => {
      if (videoRef.current && !videoRef.current.paused && isIdle(lastInput.current)) {
        videoRef.current.pause()
        setAsking(true)
      }
    }, 30_000)
    return () => { clearInterval(t); events.forEach((e) => document.removeEventListener(e, touch)) }
  }, [])

  useEffect(() => {
    const t = setInterval(() => {
      api(`/playback/sessions/${session.session_id}/heartbeat`, { method: 'POST' }).catch((e) => {
        if (!['stream_limit', 'session_ended', 'entitlement_required', 'expired', 'territory_blocked', 'not_verified', 'no_rights'].includes(e.code)) return
        videoRef.current?.pause()
        setStopped(e.message)
      })
    }, HEARTBEAT_MS)
    return () => clearInterval(t)
  }, [session.session_id])

  useEffect(() => {
    const onFs = () => setFullscreen(document.fullscreenElement === wrapRef.current)
    document.addEventListener('fullscreenchange', onFs)
    return () => document.removeEventListener('fullscreenchange', onFs)
  }, [])

  const onKey = (e) => {
    const v = videoRef.current
    if (!v || ['INPUT', 'SELECT'].includes(e.target.tagName)) return
    if (e.key === ' ' || e.key === 'k') { e.preventDefault(); toggle() }
    else if (e.key === 'ArrowRight') handleSeek(v.currentTime + 10)
    else if (e.key === 'ArrowLeft') handleSeek(v.currentTime - 10)
    else if (e.key === 'm') v.muted = !v.muted
    else if (e.key === 'f') toggleFs()
  }

  const toggle = () => {
    const v = videoRef.current
    if (!v) return
    if (v.ended) v.currentTime = 0
    if (v.paused) v.play().catch(() => {})
    else v.pause()
  }

  const togglePip = async () => {
    try {
      if (document.pictureInPictureElement) await document.exitPictureInPicture()
      else await videoRef.current?.requestPictureInPicture?.()
    } catch { /* not allowed for this source, or the browser refused: leave the player as it is */ }
  }
  useEffect(() => {
    const v = videoRef.current
    if (!v) return undefined
    const on = () => setInPip(true)
    const off = () => setInPip(false)
    v.addEventListener('enterpictureinpicture', on)
    v.addEventListener('leavepictureinpicture', off)
    return () => { v.removeEventListener('enterpictureinpicture', on); v.removeEventListener('leavepictureinpicture', off) }
  }, [])
  const toggleFs = () => (document.fullscreenElement ? document.exitFullscreen() : wrapRef.current?.requestFullscreen?.())
  const changeLevel = (i) => { setLevel(i); engine.current?.setLevel(i) }
  const pickSubs = (i) => {
    setSubs(i)
    Array.from(videoRef.current?.textTracks || []).forEach((t, idx) => { t.mode = idx === i ? 'showing' : 'disabled' })
  }

  const keepWatching = () => { lastInput.current = Date.now(); setAsking(false); videoRef.current?.play?.() }
  const marker = activeMarker(markers.data, time)
  const skip = !marker ? null
    : marker.kind === 'credits' ? (onNext ? { label: 'Next episode', run: onNext } : null)
      : { label: marker.kind === 'recap' ? 'Skip recap' : 'Skip intro', run: () => { handleSeek(marker.end_s); wrapRef.current?.focus() } }

  if (stopped) {
    return (
      <div role="alert" className="grid aspect-video w-full place-items-center rounded-xl border border-line bg-surface/90 p-6 text-center">
        <div className="max-w-md space-y-3">
          <p className="font-semibold text-lg text-white">Playback stopped on this screen</p>
          <p className="text-sm text-text-muted">{stopped}</p>
          <Link to="/plans" className="btn btn-primary mt-2">See subscription plans</Link>
        </div>
      </div>
    )
  }

  if (session.kind === 'embed') {
    return (
      <div className="aspect-video w-full overflow-hidden rounded-xl border border-line bg-black shadow-2xl">
        <iframe title="Video player" src={embedSrc(session.url)} className="h-full w-full"
          allow="autoplay; fullscreen; picture-in-picture; encrypted-media" allowFullScreen
          sandbox="allow-scripts allow-same-origin allow-presentation" referrerPolicy="strict-origin-when-cross-origin" />
      </div>
    )
  }

  return (
    <div
      ref={wrapRef}
      tabIndex={0}
      onKeyDown={onKey}
      onMouseMove={triggerControls}
      onClick={() => { if (!showSettings) triggerControls() }}
      className="group relative aspect-video w-full overflow-hidden rounded-xl border border-line/80 bg-black shadow-2xl outline-none select-none"
      aria-label="Video player"
    >
      <video
        ref={videoRef}
        className="h-full w-full cursor-pointer"
        preload="metadata"
        autoPlay
        playsInline
        data-title-id={titleId}
        data-episode-id={episodeId || ''}
        onClick={toggle}
        onPlay={() => setPlaying(true)}
        onPause={() => { setPlaying(false); save() }}
        onTimeUpdate={(e) => {
          const v = e.currentTarget
          setTime(v.currentTime)
          progress.current.pos = v.currentTime
        }}
        onDurationChange={(e) => {
          const d = e.currentTarget.duration
          if (Number.isFinite(d)) { setDuration(d); progress.current.dur = d }
        }}
        onVolumeChange={(e) => { setVolume(e.currentTarget.volume); setMuted(e.currentTarget.muted) }}
        onEnded={() => { setPlaying(false); progress.current.pos = progress.current.dur; save(); onEnded?.() }}
        onError={() => { if (!engine.current) setError('This video could not be loaded. The source may have expired or be unavailable.') }}
      >
        {session.subtitles?.map((s) => <track key={s.url} kind="subtitles" src={s.url} srcLang={s.lang} label={s.label} />)}
      </video>

      {error && <div role="alert" className="absolute inset-0 grid place-items-center bg-black/90 p-6 text-center text-sm text-danger">{error}</div>}
      {reporting && <ReportProblem className="absolute inset-0 z-30" titleId={titleId} episodeId={episodeId} getPosition={() => progress.current.pos} onClose={() => { setReporting(false); wrapRef.current?.focus() }} />}
      {asking && <StillWatching className="absolute inset-0 z-20" onContinue={keepWatching} onStop={() => onStop?.()} />}
      {skip && <SkipButton label={skip.label} onClick={skip.run} />}

      <div
        className={`absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/95 via-black/70 to-transparent p-3 sm:p-4 space-y-2 transition-opacity duration-300 z-10 ${
          showControls ? 'opacity-100' : 'opacity-0 pointer-events-none'
        }`}
      >
        <div className="relative flex items-center group/scrub">
          <input
            aria-label="Seek time"
            type="range"
            min={0}
            max={duration || 0}
            step={1}
            value={Math.min(time, duration || 0)}
            className="w-full h-1.5 sm:h-2 bg-white/20 rounded-lg appearance-none cursor-pointer accent-brand transition-all hover:h-2.5"
            onChange={(e) => handleSeek(Number(e.target.value))}
          />
        </div>

        <div className="flex items-center justify-between text-white gap-2">
          <div className="flex items-center gap-1.5 sm:gap-2">
            {onPrev && (
              <button type="button" className="btn btn-ghost !p-2 !min-h-0 text-white hover:text-brand" onClick={onPrev} aria-label="Previous episode">
                <SkipBackIcon size={18} />
              </button>
            )}
            <button
              type="button"
              className="btn btn-ghost !p-2 sm:!px-3 sm:!py-1.5 !min-h-0 text-white hover:text-brand font-bold"
              onClick={toggle}
              aria-label={playing ? 'Pause' : 'Play'}
            >
              {playing ? <PauseIcon size={20} fill /> : <PlayIcon size={20} fill />}
            </button>
            {onNext && (
              <button type="button" className="btn btn-ghost !p-2 !min-h-0 text-white hover:text-brand" onClick={onNext} aria-label="Next episode">
                <SkipForwardIcon size={18} />
              </button>
            )}
            <span className="tabular-nums text-[11px] sm:text-xs font-medium text-text-muted pl-1">
              {formatTime(time)} <span className="opacity-60">/</span> {formatTime(duration)}
            </span>
          </div>

          <div className="flex items-center gap-1.5 sm:gap-2.5">
            <div className="hidden sm:flex items-center gap-1.5">
              <button
                type="button"
                className="btn btn-ghost !p-2 !min-h-0 text-white hover:text-brand"
                aria-label={muted ? 'Unmute' : 'Mute'}
                onClick={() => { if (videoRef.current) videoRef.current.muted = !muted }}
              >
                {muted || volume === 0 ? <VolumeXIcon size={18} /> : <Volume2Icon size={18} />}
              </button>
              <input
                aria-label="Volume slider"
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={muted ? 0 : volume}
                className="w-16 lg:w-20 h-1.5 bg-white/20 rounded-lg accent-brand cursor-pointer"
                onChange={(e) => {
                  const v = videoRef.current
                  if (v) { v.volume = Number(e.target.value); v.muted = false }
                }}
              />
            </div>

            <div className="hidden md:flex items-center gap-2">
              {session.subtitles?.length > 0 && (
                <select
                  aria-label="Subtitles"
                  className="bg-surface/80 border border-line text-xs rounded px-2 py-1 text-white focus:outline-none cursor-pointer"
                  value={subs}
                  onChange={(e) => pickSubs(Number(e.target.value))}
                >
                  <option value={-1}>Subtitles: Off</option>
                  {session.subtitles.map((s, i) => <option key={s.url} value={i}>{s.label}</option>)}
                </select>
              )}

              {audioTracks.length > 1 && (
                <select
                  aria-label="Audio track"
                  className="bg-surface/80 border border-line text-xs rounded px-2 py-1 text-white focus:outline-none cursor-pointer"
                  value={audio}
                  onChange={(e) => {
                    const i = Number(e.target.value)
                    setAudio(i)
                    engine.current?.setAudio?.(i)
                  }}
                >
                  {audioTracks.map((t) => <option key={t.i} value={t.i}>{t.label}</option>)}
                </select>
              )}

              <select
                aria-label="Playback speed"
                className="bg-surface/80 border border-line text-xs rounded px-2 py-1 text-white focus:outline-none cursor-pointer"
                value={rate}
                onChange={(e) => {
                  const r = Number(e.target.value)
                  setRate(r)
                  if (videoRef.current) videoRef.current.playbackRate = r
                }}
              >
                {[0.5, 0.75, 1, 1.25, 1.5, 2].map((r) => <option key={r} value={r}>{r}x</option>)}
              </select>

              {levels.length > 1 && (
                <select
                  aria-label="Quality"
                  className="bg-surface/80 border border-line text-xs rounded px-2 py-1 text-white focus:outline-none cursor-pointer"
                  value={level}
                  onChange={(e) => changeLevel(Number(e.target.value))}
                >
                  <option value={-1}>Quality: Auto</option>
                  {levels.map((l) => <option key={l.i} value={l.i}>{l.label}</option>)}
                </select>
              )}
            </div>

            {session.kind === 'mp4' && (
              <a
                href={`/api/v1/playback/${titleId}/download${buildQuery({ episode_id: episodeId, profile_id: getProfileId() })}`}
                target="_blank"
                rel="noopener noreferrer"
                className="btn btn-ghost !p-2 !min-h-0 text-white hover:text-brand"
                title="Download video"
                aria-label="Download video"
              >
                <DownloadIcon size={18} />
              </a>
            )}

            <div className="relative">
              <button
                type="button"
                className={`btn btn-ghost !p-2 !min-h-0 text-white hover:text-brand ${showSettings ? 'text-brand bg-raised' : ''}`}
                onClick={(e) => {
                  e.stopPropagation()
                  setShowSettings((s) => !s)
                }}
                aria-label="Playback settings"
                aria-expanded={showSettings}
              >
                <SettingsIcon size={18} />
              </button>

              {showSettings && (
                <div
                  className="absolute bottom-full right-0 mb-3 w-64 card p-3 shadow-2xl bg-surface/95 backdrop-blur-xl border border-line rounded-xl z-50 text-xs text-text space-y-3 animate-[fadein_.15s_ease-out]"
                  onClick={(e) => e.stopPropagation()}
                >
                  <div className="flex items-center justify-between border-b border-line pb-2 font-semibold text-white">
                    <span>Playback Settings</span>
                    <button type="button" onClick={() => setShowSettings(false)} className="text-muted hover:text-white">
                      <XIcon size={14} />
                    </button>
                  </div>

                  <div>
                    <label className="text-muted block mb-1">Playback Speed</label>
                    <div className="grid grid-cols-3 gap-1">
                      {[0.75, 1, 1.25, 1.5, 2].map((r) => (
                        <button
                          key={r}
                          type="button"
                          className={`px-2 py-1 rounded text-center font-medium transition-colors ${
                            rate === r ? 'bg-brand text-white' : 'bg-raised hover:bg-line text-text'
                          }`}
                          onClick={() => {
                            setRate(r)
                            if (videoRef.current) videoRef.current.playbackRate = r
                          }}
                        >
                          {r}x
                        </button>
                      ))}
                    </div>
                  </div>

                  {levels.length > 1 && (
                    <div>
                      <label className="text-muted block mb-1">Video Quality</label>
                      <select
                        aria-label="Quality setting"
                        className="w-full bg-raised border border-line rounded px-2 py-1.5 text-xs text-white"
                        value={level}
                        onChange={(e) => changeLevel(Number(e.target.value))}
                      >
                        <option value={-1}>Auto (Recommended)</option>
                        {levels.map((l) => <option key={l.i} value={l.i}>{l.label}</option>)}
                      </select>
                    </div>
                  )}

                  {session.subtitles?.length > 0 && (
                    <div>
                      <label className="text-muted block mb-1">Subtitles</label>
                      <select
                        aria-label="Subtitles setting"
                        className="w-full bg-raised border border-line rounded px-2 py-1.5 text-xs text-white"
                        value={subs}
                        onChange={(e) => pickSubs(Number(e.target.value))}
                      >
                        <option value={-1}>Off</option>
                        {session.subtitles.map((s, i) => <option key={s.url} value={i}>{s.label}</option>)}
                      </select>
                    </div>
                  )}

                  {audioTracks.length > 1 && (
                    <div>
                      <label className="text-muted block mb-1">Audio Language</label>
                      <select
                        aria-label="Audio track setting"
                        className="w-full bg-raised border border-line rounded px-2 py-1.5 text-xs text-white"
                        value={audio}
                        onChange={(e) => {
                          const i = Number(e.target.value)
                          setAudio(i)
                          engine.current?.setAudio?.(i)
                        }}
                      >
                        {audioTracks.map((t) => <option key={t.i} value={t.i}>{t.label}</option>)}
                      </select>
                    </div>
                  )}
                </div>
              )}
            </div>

            <button
              type="button"
              className="btn btn-ghost !p-2 !min-h-0 text-white hover:text-brand"
              onClick={() => setReporting(true)}
              aria-label="Report a problem"
            >
              <FlagIcon size={18} />
            </button>
            {canPip && (
              <button
                type="button"
                className="btn btn-ghost !p-2 !min-h-0 text-white hover:text-brand"
                onClick={togglePip}
                aria-pressed={inPip}
                aria-label={inPip ? 'Leave picture-in-picture' : 'Picture-in-picture'}
              >
                <PipIcon size={18} />
              </button>
            )}
            <button
              type="button"
              className="btn btn-ghost !p-2 !min-h-0 text-white hover:text-brand"
              onClick={toggleFs}
              aria-label={fullscreen ? 'Exit fullscreen' : 'Enter fullscreen'}
            >
              {fullscreen ? <MinimizeIcon size={18} /> : <FullscreenIcon size={18} />}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
