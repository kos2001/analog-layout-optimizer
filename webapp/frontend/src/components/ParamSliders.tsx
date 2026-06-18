import type { Config, ParamKey, Params } from "../types";

const LABELS: Record<ParamKey, string> = {
  w_finger: "Finger width  W",
  l: "Gate length  L",
  finger_pitch: "Poly pitch",
  guard_gap: "Guard-ring gap",
  gr_width: "Guard-ring width",
};

// DRC floor for each parameter (for marking the slider's minimum-legal point).
function floorFor(key: ParamKey, cfg: Config): number | null {
  switch (key) {
    case "l":
      return cfg.rules.min_l;
    case "w_finger":
      return cfg.rules.min_w;
    case "finger_pitch":
      return cfg.rules.min_poly_pitch;
    case "guard_gap":
      return cfg.rules.min_gr_gap;
    case "gr_width":
      return cfg.rules.min_gr_width;
    default:
      return null;
  }
}

interface Props {
  config: Config;
  params: Params;
  disabled?: boolean;
  onChange: (next: Params) => void;
}

export default function ParamSliders({
  config,
  params,
  disabled,
  onChange,
}: Props) {
  return (
    <div className="sliders">
      {config.order.map((key) => {
        const [lo, hi] = config.bounds[key];
        const floor = floorFor(key, config);
        const val = params[key];
        return (
          <div className="slider-row" key={key}>
            <label htmlFor={`s-${key}`}>
              <span className="slider-name">{LABELS[key]}</span>
              <span className="slider-val">{val.toFixed(3)} µm</span>
            </label>
            <input
              id={`s-${key}`}
              type="range"
              min={lo}
              max={hi}
              step={0.005}
              value={val}
              disabled={disabled}
              onChange={(e) =>
                onChange({ ...params, [key]: Number(e.target.value) })
              }
            />
            <div className="slider-meta">
              <span>{lo}</span>
              {floor != null && (
                <span className="drc-floor">DRC≥{floor}</span>
              )}
              <span>{hi}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
