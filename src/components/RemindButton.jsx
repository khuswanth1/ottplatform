import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { BellIcon, CheckIcon } from './icons'

// "Remind me" for a title that is not out yet. Pressing again cancels. The server ends the reminder once the
// notification exists, so the button goes back to its resting state after release.
export default function RemindButton({ id, className = 'btn btn-ghost' }) {
  const { user, profileId } = useAuth()
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['reminder-ids', profileId], queryFn: () => api('/reminders/ids'), enabled: !!user && !!profileId })
  const on = !!q.data?.includes(id)
  const toggle = useMutation({
    mutationFn: () => api(`/reminders/${id}`, { method: on ? 'DELETE' : 'PUT' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['reminder-ids'] }),
  })
  if (!user) return <Link to="/login" className={className}><BellIcon /> Remind me</Link>
  return (
    <>
      <button type="button" className={className} aria-pressed={on} disabled={toggle.isPending || q.isLoading} onClick={() => toggle.mutate()}>
        {on ? <><CheckIcon /> Reminder set</> : <><BellIcon /> Remind me</>}
      </button>
      {toggle.isError && <span role="alert" className="text-xs text-warn">{toggle.error.message}</span>}
    </>
  )
}
