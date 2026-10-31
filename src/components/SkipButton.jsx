// "Skip intro" / "Skip recap" / "Next episode": sits on the video, above the control bar. The parent positions it in a
// `relative` frame and decides when it shows.
export default function SkipButton({ label, onClick }) {
  return <button type="button" className="btn btn-ghost absolute bottom-20 right-3 z-10 border border-white/60 bg-black/70 !px-4 !py-2 font-semibold sm:bottom-24" onClick={onClick}>{label}</button>
}
