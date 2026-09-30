import Markdown from "react-markdown"

type DevelopMarkdownProps = {
  children: string
}

export function DevelopMarkdown({ children }: DevelopMarkdownProps) {
  return (
    <div className="space-y-2 break-words [&_a]:underline [&_code]:rounded-sm [&_code]:bg-black/10 [&_code]:px-1 [&_ol]:list-decimal [&_ol]:pl-5 [&_pre]:overflow-x-auto [&_pre]:rounded-sm [&_pre]:bg-black/10 [&_pre]:p-3 [&_ul]:list-disc [&_ul]:pl-5">
      <Markdown
        components={{
          a: ({ href, children: linkChildren }) => (
            <a href={href} rel="noreferrer" target="_blank">
              {linkChildren}
            </a>
          ),
        }}
        skipHtml
      >
        {children}
      </Markdown>
    </div>
  )
}
