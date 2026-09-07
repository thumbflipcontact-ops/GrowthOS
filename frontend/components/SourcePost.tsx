import type { ContentItem } from "@/lib/types";

export function originalPostUrl(item: ContentItem): string | null {
  if (item.target_platform === "twitter" && item.target_ref) {
    return `https://twitter.com/i/web/status/${item.target_ref}`;
  }
  if (item.target_platform === "reddit" && item.target_ref?.startsWith("t3_")) {
    // Reddit's own short-link scheme — resolves a submission's fullname (what
    // plugins/reddit/plugin.py's _to_plugin_result sets as target_ref, since search only
    // ever returns submissions, never individual comments) straight to its real permalink,
    // with no extra API call needed.
    return `https://redd.it/${item.target_ref.slice(3)}`;
  }
  return null;
}

export function SourcePost({ item }: { item: ContentItem }) {
  if (!item.source_title && !item.source_body) {
    // Older items predating source_title/source_body, or the source knowledge_item was
    // deleted — fall back to the short quotes the drafting agent originally cited.
    if (item.evidence.length === 0) return null;
    return (
      <div className="content-body" style={{ fontStyle: "italic", fontSize: 13 }}>
        <strong style={{ fontStyle: "normal" }}>Replying to a post that said:</strong>{" "}
        {item.evidence.map((quote, i) => (
          <span key={i}>
            {i > 0 && " … "}
            &ldquo;{quote}&rdquo;
          </span>
        ))}
      </div>
    );
  }
  return (
    <div className="content-body" style={{ fontSize: 13 }}>
      <strong>Replying to:</strong>
      {item.source_title && (
        <div style={{ fontWeight: 600, marginTop: 4 }}>{item.source_title}</div>
      )}
      {item.source_body && (
        <div style={{ marginTop: 4, whiteSpace: "pre-wrap" }}>{item.source_body}</div>
      )}
    </div>
  );
}
