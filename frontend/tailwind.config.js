const rgb = (name) => `rgb(var(--${name}) / <alpha-value>)`;

/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: rgb("ink"), panel: rgb("panel"), raised: rgb("raised"),
        line: rgb("line"), "line-strong": rgb("line-strong"),
        text: rgb("text"), muted: rgb("muted"), faint: rgb("faint"),
        iris: rgb("iris"), cobalt: rgb("cobalt"),
        danger: rgb("danger"), amber: rgb("amber"), ok: rgb("ok"), quiet: rgb("quiet"),
      },
      fontFamily: {
        sans: ['"Geist Variable"', "ui-sans-serif", "system-ui", "sans-serif"],
        display: ['"Newsreader Variable"', "ui-serif", "Georgia", "serif"],
        mono: ['"Geist Mono Variable"', "ui-monospace", "monospace"],
      },
      borderRadius: { control: "7px", panel: "11px" },
      keyframes: {
        reveal: { from: { opacity: "0", transform: "translateY(-2px)" }, to: { opacity: "1", transform: "none" } },
        spin: { to: { transform: "rotate(360deg)" } },
      },
      animation: { reveal: "reveal 140ms ease-out" },
    },
  },
  plugins: [],
};
