interface IframeTabProps {
  url: string
}

export function IframeTab({ url }: IframeTabProps) {
  if (!url) {
    return (
      <div className="h-full flex items-center justify-center text-[var(--text-secondary)]">
        No URL configured
      </div>
    )
  }

  return <iframe src={url} className="w-full h-full border-0" loading="lazy" />
}
