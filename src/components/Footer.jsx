export default function Footer() {
  return (
    <footer className="mt-8 px-4 py-8 text-xs text-muted sm:px-12">
      <p>
        <a href="https://www.themoviedb.org" target="_blank" rel="noopener noreferrer" className="font-semibold text-text underline">The Movie Database (TMDB)</a>
        {' '}supplies title data and artwork.
      </p>
      <p className="mt-2">
        CineVerse only plays titles whose rights have been verified for your country. Other titles link to the licensed
        service that offers them. This product uses the TMDB API but is not endorsed or certified by TMDB.
        Streaming availability data by Watchmode and JustWatch.
      </p>
    </footer>
  )
}
