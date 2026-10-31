import { Bell, Check, Download, Film, Flag, Globe, Heart, Lock, Maximize, Menu, Minimize, Pause, PictureInPicture2, Play, Plus, Search, Settings, SkipBack, SkipForward, ThumbsDown, ThumbsUp, Volume2, VolumeX, X } from 'lucide-react'

// Thin wrappers: consistent inline sizing, decorative by default (buttons carry aria-labels).
const make = (Icon) => function WrappedIcon({ fill, size = 18, ...rest }) {
  return <Icon aria-hidden="true" size={size} className="inline-block align-[-3px]" fill={fill ? 'currentColor' : 'none'} {...rest} />
}

export const BellIcon = make(Bell)
export const CheckIcon = make(Check)
export const DownloadIcon = make(Download)
export const FilmIcon = make(Film)
export const GlobeIcon = make(Globe)
export const HeartIcon = make(Heart)
export const FullscreenIcon = make(Maximize)
export const MinimizeIcon = make(Minimize)
export const LockIcon = make(Lock)
export const MenuIcon = make(Menu)
export const PauseIcon = make(Pause)
export const FlagIcon = make(Flag)
export const PipIcon = make(PictureInPicture2)
export const PlayIcon = make(Play)
export const PlusIcon = make(Plus)
export const SearchIcon = make(Search)
export const SettingsIcon = make(Settings)
export const SkipBackIcon = make(SkipBack)
export const SkipForwardIcon = make(SkipForward)
export const ThumbsDownIcon = make(ThumbsDown)
export const ThumbsUpIcon = make(ThumbsUp)
export const Volume2Icon = make(Volume2)
export const VolumeXIcon = make(VolumeX)
export const XIcon = make(X)
