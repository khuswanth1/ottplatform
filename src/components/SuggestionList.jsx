import { Link } from 'react-router-dom'

// Typeahead list under the navbar search box. Pure display: the parent owns focus, the active index and navigation.
export default function SuggestionList({ options, active = -1, onPick }) {
  if (!options.length) return null
  return (
    <ul id="search-suggestions" role="listbox" aria-label="Title suggestions" className="absolute left-0 right-0 top-full z-50 mt-1 card p-1 text-sm shadow-xl">
      {options.map((o, i) => (
        <li key={o.id} id={`sugg-${i}`} role="option" aria-selected={i === active}>
          <Link to={`/title/${o.id}`} onClick={() => onPick?.(o)} className={`block truncate rounded px-3 py-2 hover:bg-raised ${i === active ? 'bg-raised' : ''}`}>
            {o.name}{o.year ? <span className="text-muted"> · {o.year}</span> : null}
          </Link>
        </li>
      ))}
    </ul>
  )
}
