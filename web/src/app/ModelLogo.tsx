const logos: Record<string, string> = {
  anthropic: new URL("../assets/model-logos/anthropic.svg", import.meta.url).href,
  openai: new URL("../assets/model-logos/openai.svg", import.meta.url).href,
  cursor: new URL("../assets/model-logos/cursor.svg", import.meta.url).href,
  google: new URL("../assets/model-logos/google.svg", import.meta.url).href,
  xai: new URL("../assets/model-logos/xai.svg", import.meta.url).href,
  zai: new URL("../assets/model-logos/zai.svg", import.meta.url).href,
  moonshot: new URL("../assets/model-logos/moonshot.svg", import.meta.url).href,
  deepseek: new URL("../assets/model-logos/deepseek.svg", import.meta.url).href,
  minimax: new URL("../assets/model-logos/minimax.svg", import.meta.url).href,
  qwen: new URL("../assets/model-logos/qwen.svg", import.meta.url).href,
  xiaomi: new URL("../assets/model-logos/xiaomi.svg", import.meta.url).href,
};

export default function ModelLogo({ vendor }: { vendor: string }) {
  const src = logos[vendor];
  if (!src) return <span className={`dot vendor-${vendor}`} aria-hidden="true" />;
  return (
    <span className={`model-logo vendor-${vendor}`} aria-hidden="true">
      <img src={src} alt="" />
    </span>
  );
}
