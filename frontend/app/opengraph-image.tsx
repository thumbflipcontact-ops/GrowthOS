import { ImageResponse } from "next/og";

export const size = { width: 1200, height: 630 };
export const contentType = "image/png";
export const alt = "Threadly — AI finds your next customer on X.";

export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: "72px",
          background: "#fbfaf8",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <div
            style={{
              width: 56,
              height: 56,
              borderRadius: 16,
              background: "linear-gradient(135deg, #4f46e5, #7c3aed, #ec4899)",
            }}
          />
          <div style={{ fontSize: 34, fontWeight: 700, color: "#171717" }}>Threadly</div>
        </div>

        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            fontSize: 58,
            fontWeight: 700,
            lineHeight: 1.2,
            letterSpacing: "-0.02em",
            color: "#171717",
          }}
        >
          Your next customer is tweeting right now.{" "}
          <span
            style={{
              background: "linear-gradient(100deg, #4f46e5, #7c3aed 55%, #ec4899)",
              backgroundClip: "text",
              color: "transparent",
            }}
          >
            AI finds them before you scroll past.
          </span>
        </div>

        <div style={{ display: "flex", fontSize: 26, color: "#666666" }}>
          usethreadly.co · 7-day free trial · founding pricing from $9/mo
        </div>
      </div>
    ),
    { ...size }
  );
}
