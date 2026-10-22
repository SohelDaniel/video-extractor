import './globals.css'

export const metadata = {
  title: 'Video Transcriber Pro',
  description: 'AI-powered video transcription and lecture notes',
}

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <div className="min-h-screen bg-black text-white">
          {children}
        </div>
      </body>
    </html>
  )
}